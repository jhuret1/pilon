"""Bounded extraction prefetch, batched BGE, ordered incremental concept discovery.

Only concept identities are organized here. Values retain their extraction provenance;
an exact source span does not certify the interpretation or audit precision.
"""
import copy
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from .pipeline import ground, signature
from .providers import PROMPT_V2
from .store import digest, Paused
from .identity import card,exact_matches,collisions,candidates as identity_candidates,normalized,FAMILIES,FAMILY_VERSION,ROUTING_VERSION,protect_identity_candidates


def grounded(text, item):
    original = ground(text,item)
    quote=item.get('quote')
    # Repair ONLY a unique literal quote, never a fuzzy/translated/shortened span.
    if original['proof_status']=='invalid_span' and isinstance(quote,str) and quote and text.count(quote)==1:
        start=text.index(quote)
        original=ground(text,{**item,'start':start,'end':start+len(quote)})
        original['alignment_repair']={'method':'unique_exact_substring','original_start':item.get('start'),'original_end':item.get('end')}
    return original


class EvidenceIndex:
    def __init__(self):
        self.matrix=np.empty((1024,1024),dtype=np.float32)
        self.fact_ids=[]

    def add(self, fid, vector):
        if len(self.fact_ids)==len(self.matrix):
            self.matrix=np.concatenate((self.matrix,np.empty_like(self.matrix)))
        self.matrix[len(self.fact_ids)]=vector
        self.fact_ids.append(fid)

    def nearest(self, vector, facts, k):
        if not self.fact_ids:
            return []
        scores=self.matrix[:len(self.fact_ids)] @ vector
        best={}
        for fid,score in zip(self.fact_ids,scores):
            best[fid]=max(best.get(fid,-2.),float(score))
        ordered=sorted(facts,key=lambda f:-best.get(f['id'],-2.))[:k]
        return [{**f,'similarity':best[f['id']]} for f in ordered if f['id'] in best]


def process_corpus(engine,run):
    store=engine.store
    cfg=run['config']
    contract=cfg['embedding_contract']
    canonical=cfg.get('purpose')=='canonical_corpus'
    guarded=cfg.get('routing_version')==ROUTING_VERSION
    provider=engine.provider_factory(store,run['id'],engine.key)
    if provider.embedding_contract != contract:
        raise ValueError('Embedding contract mismatch; refusing cache reuse.')
    provider.extraction_prompt=PROMPT_V2
    provider.retry_429=True
    # Prefix reuse includes all decisions, not just extraction/embedding caches.
    if not run['processed'] and cfg.get('reuse_run'):
        source=store.run(cfg['reuse_run'])
        n=len(source['rows'])
        if source['status']!='completed' or source['input_hash']!=digest(run['rows'][:n]):
            raise ValueError('Le snapshot réutilisé doit être le préfixe exact du corpus.')
        run['facts']=copy.deepcopy(source['facts'])
        for f in run['facts']:
            for field in ('vector','anchor_vectors','anchor_ids'):
                f.pop(field,None)
        for i in range(n):
            items=copy.deepcopy([e for e in source['extractions'] if e['review_index']==i])
            for e in items:
                if 'vector' in e:
                    e['embedding_id']=store.put_vector(e['embedding_text'],e.pop('vector'),model=contract)
                e['reused_from']=source['id']
            store.save_review(run['id'],i,'completed',items)
        run['processed']=n
        run['reused_reviews']=n
        run['reused_cost_usd']=cfg.get('reused_cost_usd',0)
        store.save(run)

    completed=store.extractions(run['id'])
    index=EvidenceIndex()
    vectors={}
    fact_vectors={}
    for e in completed:
        cid=e.get('embedding_id')
        if cid and e.get('fact_id'):
            if cid not in vectors:
                vectors[cid]=store.vector(cid)
            if vectors[cid] is None:
                raise ValueError('Cache BGE manquant : arrêt, aucun recalcul silencieux.')
            index.add(e['fact_id'],vectors[cid])
    if canonical:
        for f in run['facts']:
            text=card(f);cid=digest([contract,text])
            vector=store.vector(cid)
            if vector is None:
                vector=provider.embed([text])[0];store.put_vector(text,vector,model=contract)
            fact_vectors[f['id']]=np.asarray(vector,dtype=np.float32)
    run['storage']='review_results_v1'
    run['extractions']=[]
    local=threading.local()

    def extract(i):
        cached=store.review_result(run['id'],i)
        if cached:
            return cached['extractions']
        if engine.stop.is_set() or store.run(run['id'])['status']!='running':
            raise Paused('Pause demandée.')
        if not hasattr(local,'provider'):
            local.provider=engine.provider_factory(store,run['id'],engine.key)
            local.provider.extraction_prompt=PROMPT_V2
            local.provider.retry_429=True
        items=local.provider.extract(run['rows'][i]['text'])
        if len(items)>100:
            raise Paused('Plus de 100 assertions dans une review ; résultat brut conservé, examen nécessaire.')
        store.save_review(run['id'],i,'extracted',items)
        return items

    # A small bounded window prevents paying for the entire corpus ahead of governance.
    with ThreadPoolExecutor(max_workers=cfg.get('extraction_workers',3),thread_name_prefix='pilon-extract') as pool:
        pending={}
        next_index=run['processed']
        try:
            for i in range(run['processed'],len(run['rows'])):
                engine.checkpoint(run)
                while next_index<len(run['rows']) and len(pending)<6:
                    pending[next_index]=pool.submit(extract,next_index)
                    next_index+=1
                run['phase']='extraction'
                store.save(run)
                items=pending.pop(i).result()
                row=run['rows'][i]
                prepared=[]
                missing={}
                for n,item in enumerate(items):
                    e=grounded(row['text'],item)
                    e.update(id=digest([run['id'],i,n])[:16],review_index=i,language=row.get('language'),
                             route='invalid_evidence',fact_id=None,candidates=[],qualification_status='not_revalidated')
                    if e['usable'] and e['attributes']['subject'] != 'reviewed_item':
                        e['usable']=False
                        e['route']='not_applicable'
                    if e['usable']:
                        e['embedding_text']=card(e['attributes']) if canonical else signature(e,cfg['signature'])
                        cid=digest([contract,e['embedding_text']])
                        e['embedding_id']=cid
                        if cid not in vectors:
                            v=store.vector(cid)
                            if v is None:
                                missing[cid]=e['embedding_text']
                            else:
                                vectors[cid]=v
                    prepared.append(e)
                run['phase']='embedding'
                store.save(run)
                missing=list(missing.items())
                for start in range(0,len(missing),32):
                    batch=missing[start:start+32]
                    result=provider.embed([text for _,text in batch])
                    if len(result)!=len(batch):
                        raise ValueError('Lot BGE incomplet.')
                    for (cid,text),v in zip(batch,result):
                        if store.put_vector(text,v,model=contract)!=cid:
                            raise ValueError('Identité du vecteur incohérente.')
                        vectors[cid]=np.asarray(v,dtype=np.float32)
                run['phase']='ontology_enrichment'
                store.save(run)
                # Do not expose mutations until the whole review commits successfully.
                facts=copy.deepcopy(run['facts'])
                added=[]
                for e in prepared:
                    if not e['usable']:
                        continue
                    v=vectors[e['embedding_id']]
                    candidates=(identity_candidates(e['attributes'],v,facts,fact_vectors,cfg['k']) if canonical
                                else index.nearest(v,facts,cfg['k']))
                    if guarded:
                        candidates=protect_identity_candidates(e['attributes'],facts,candidates)
                    e['candidates']=[{k:f.get(k) for k in ('id','name','definition','values','similarity','retrieval_reason')} for f in candidates]
                    matches=exact_matches(e['attributes'],facts) if canonical or guarded else []
                    if guarded and len(matches)>1:
                        e.update(route='ambiguous',reason='multiple_exact_identities_require_consolidation',collision_ids=[f['id'] for f in matches])
                        continue
                    if matches:
                        e['answers']={'routing':{'choice':matches[0]['id'],'type':'exact_name_and_definition','confidence':None}}
                        e['enrichment_mode']='canonical_exact_identity'
                    elif not facts:
                        e['answers']={'routing':{'choice':'new_candidate','type':'deterministic_bootstrap','confidence':None}}
                        e['enrichment_mode']='bootstrap_first'
                    else:
                        e['answers']=(provider.enrich(row,e,candidates,identity_only=True) if guarded
                                      else provider.enrich(row,e,candidates))
                        e['enrichment_mode']='jev_incremental'
                    choice=e['answers']['routing']['choice']
                    if choice=='ambiguous':
                        e['route']='ambiguous'
                        continue
                    if choice=='new_candidate':
                        a=e['attributes']
                        if (canonical or guarded) and (collisions(a,facts) or any(normalized(f['definition'])==normalized(a['definition']) for f in facts)):
                            e['route']='ambiguous';e['reason']='canonical_identity_collision_requires_review'
                            e['collision_ids']=[f['id'] for f in facts if f in collisions(a,facts) or normalized(f['definition'])==normalized(a['definition'])]
                            continue
                        f={'id':'fact_'+digest([run['id'],e['id']])[:12],
                           'name':re.sub(r'[^a-z0-9]+','.',a['concept'].lower()).strip('.') or 'concept',
                           'definition':a['definition'],'family':a['family'],'values':[],
                           'status':'experimental_concept_not_validated','evidence_ids':[],
                           'snapshot':run['id'],'created_from':e['id'],'definition_origin':'langextract_v2',
                           'created_by':e['enrichment_mode']}
                        if canonical:
                            answer=provider.classify_families([{'name':f['name'],'definition':f['definition'],
                                'examples':[{'quote':e['quote'],'value':a['value']}]}],FAMILIES)[0]
                            family=next((fam for fam in FAMILIES if fam['id']==answer['choice']),None)
                            confidence=answer.get('confidence',0)
                            accepted=family and isinstance(confidence,(int,float)) and confidence>=.65
                            f.update(raw_family=f['family'],family=family['name'] if accepted else 'À classer',
                                     family_id=family['id'] if accepted else None,family_decision=answer,
                                     family_registry_version=FAMILY_VERSION,
                                     family_status='assigned_existing_candidate' if accepted else 'proposal_or_ambiguity_pending')
                            fact_vectors[f['id']]=v
                        facts.append(f)
                        e['route']='new_candidate'
                    else:
                        f=next(f for f in facts if f['id']==choice)
                        e['route']='known'
                    value=e['attributes']['value']
                    if value not in f['values']:
                        f['values'].append(value)
                    f['evidence_ids'].append(e['id'])
                    e['fact_id']=f['id']
                    index.add(f['id'],v)
                    added.append(e)
                run['facts']=facts
                run['processed']=i+1
                run['last_checkpoint']=time.time()
                store.save_review(run['id'],i,'completed',prepared,run=run)
        finally:
            for future in pending.values():
                future.cancel()
    run.update(status='completed',phase='completed',finished=time.time())
    store.save(run)
