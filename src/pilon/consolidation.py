"""Immutable ontology comparison snapshots, with conservative complete-link merging."""
import collections
import copy
import json
import math
import os
import time
import uuid
from pathlib import Path
import numpy as np
from .identity import identity_key,card,value_preview,FAMILIES,FAMILY_VERSION
from .store import digest,Paused

def analysis_budget(source,calls,combined_cap=2.,analysis_cap=.15):
    """Admit analysis only after an immutable, fully billed source has finished."""
    if source['status']!='completed':
        raise Paused('Le test source doit être terminé avant toute analyse payante.')
    if any(c['cost'] is None or not isinstance(c['cost'],(int,float)) or
           not math.isfinite(c['cost']) or c['cost']<0 for c in calls):
        raise Paused('Un coût source reste non confirmé ; budget complémentaire non engagé.')
    source_cost=sum(c['cost'] for c in calls)
    budget=min(analysis_cap,max(0.,combined_cap-source_cost))
    if budget<.005:
        raise Paused('Le plafond de 2 USD ne laisse pas assez de réserve pour cette analyse.')
    return source_cost,budget

def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
        # Windows can briefly keep a served snapshot open. Keep the previous
        # complete version available and retry only the atomic replacement.
        for attempt in range(12):
            try:
                os.replace(tmp,path)
                break
            except PermissionError:
                if attempt==11:raise
                time.sleep(min(.05*(2**attempt),.5))
    finally:
        if tmp.exists():tmp.unlink()

def materialize(source,extractions):
    by_fact=collections.defaultdict(list)
    for e in extractions:
        if e.get('fact_id'):by_fact[e['fact_id']].append(e)
    facts=[]
    for f in source['facts']:
        es=by_fact[f['id']];examples=[];seen=set()
        for e in es:
            if e['quote'] in seen:continue
            seen.add(e['quote']);row=source['rows'][e['review_index']]
            examples.append({'quote':e['quote'],'value':e['attributes']['value'],'presence':e['attributes'].get('presence'),
                             'condition':e['attributes'].get('condition'),'review_id':row['review_id'],
                             'item_id':row['item_id'],'language':row.get('language'),'review_index':e['review_index'],
                             'extraction_id':e['id'],'review_text':row['text'],'start':e.get('start'),'end':e.get('end'),
                             'proof_status':e.get('proof_status')})
            if len(examples)>=4:break
        facts.append({**{k:f.get(k) for k in ('id','name','definition','family','values')},
                      'evidence_count':len(es),'item_count':len({source['rows'][e['review_index']]['item_id'] for e in es}),
                      'examples':examples,'value_proposals':[value_preview(v) for v in f['values']]})
    initial_pairs=[]
    for i,f in enumerate(facts):
        for other in facts[:i]:
            a,b=identity_key(other),identity_key(f)
            if a[0]==b[0] or a[1]==b[1]:
                initial_pairs.append({'id':digest([other['id'],f['id']])[:16],'left':other['id'],'right':f['id'],
                    'similarity':None,'same_name':a[0]==b[0],'same_definition':a[1]==b[1],
                    'decision':{'choice':'equivalent','confidence':1.,'method':'exact_name_and_definition'} if a==b else None})
    return {'version':'identity-consolidation-v1','source_run':source['id'],'source_processed':source['processed'],
            'source_total':len(source['rows']),'source_status':source['status'],'source_input_hash':source['input_hash'],
            'source_fingerprint':digest({'facts':source['facts'],'extractions':extractions}),
            'family_registry_version':FAMILY_VERSION,'families':FAMILIES,'facts':facts,'pairs':initial_pairs,
            'status':'preparing','source_unchanged':True,'quality_status':'candidate_not_independent_validation',
            'raw_family_count':len({f['family'] for f in facts})}

def build_pairs(facts,vectors):
    n=len(facts);matrix=np.asarray(vectors,dtype=np.float32)
    similarities=np.clip(matrix@matrix.T,-1,1)
    selected=set()
    for i in range(n):
        for j in np.argsort(-similarities[i],kind='stable')[:13]:
            if i!=j:selected.add(tuple(sorted((i,int(j)))))
        for j in range(i):
            a,b=identity_key(facts[i]),identity_key(facts[j])
            if a[0]==b[0] or a[1]==b[1]:selected.add((j,i))
    pairs=[]
    for i,j in sorted(selected):
        a,b=identity_key(facts[i]),identity_key(facts[j])
        exact=a==b
        pairs.append({'id':digest([facts[i]['id'],facts[j]['id']])[:16],'left':facts[i]['id'],'right':facts[j]['id'],
                      'similarity':float(similarities[i,j]),'same_name':a[0]==b[0],'same_definition':a[1]==b[1],
                      'decision':{'choice':'equivalent','confidence':1.,'method':'exact_name_and_definition'} if exact else None})
    return pairs

def accepted(pair,similarity=.88,confidence=.75,*,semantic_only=False):
    d=pair.get('decision') or {}
    if d.get('method')=='exact_name_and_definition':return True
    score=d.get('confidence')
    return (d.get('choice')=='equivalent' and isinstance(score,(int,float)) and math.isfinite(score)
            and score>=confidence and (semantic_only or (pair['similarity'] is not None and pair['similarity']>=similarity)))

def canonical_groups(facts,pairs,similarity=.88,confidence=.75,*,semantic_only=False):
    """No A~B~C transitive merge unless every cross-pair is approved."""
    groups={f['id']:[f['id']] for f in facts};owner={k:k for k in groups}
    allowed={frozenset((p['left'],p['right'])) for p in pairs if accepted(p,similarity,confidence,semantic_only=semantic_only)}
    for p in sorted(pairs,key=lambda p:(-(p.get('decision') or {}).get('confidence',-1),-(p['similarity'] or 0),p['id'])):
        a,b=owner[p['left']],owner[p['right']]
        if a==b or not accepted(p,similarity,confidence,semantic_only=semantic_only):continue
        if not all(frozenset((x,y)) in allowed for x in groups[a] for y in groups[b]):continue
        members=groups.pop(b);groups[a].extend(members)
        for x in members:owner[x]=a
    order={f['id']:i for i,f in enumerate(facts)}
    return [sorted(g,key=order.get) for g in groups.values()]

def canonical_snapshot(data,extractions):
    facts={f['id']:f for f in data['facts']};groups=canonical_groups(data['facts'],data['pairs'])
    families={f['id']:f for f in data.get('families',FAMILIES)}
    aliases={i:g[0] for g in groups for i in g};out=[]
    for g in groups:
        f=copy.deepcopy(facts[g[0]])
        f['aliases']=[{'id':i,'name':facts[i]['name']} for i in g[1:]]
        f['values']=list(dict.fromkeys(v for i in g for v in facts[i]['values']))
        f['evidence_count']=sum(facts[i]['evidence_count'] for i in g)
        f['status']='consolidation_candidate_not_published'
        f['family_candidates']={i:facts[i].get('family_decision') for i in g}
        f['family_adjudications']={i:facts[i]['family_review'] for i in g if facts[i].get('family_review')}
        reviewed={r['family_id'] for r in f['family_adjudications'].values() if r['status']=='assigned'}
        unresolved=any(r['status']!='assigned' for r in f['family_adjudications'].values())
        automatic={a['choice'] for a in f['family_candidates'].values() if a and a['choice'] in families}
        if len(reviewed)==1 and not unresolved:
            family_id=next(iter(reviewed));assignment='assistant_adjudicated'
        elif reviewed or unresolved:
            family_id=None;assignment='requires_definition_or_reconciliation'
        elif len(automatic)==1:
            family_id=next(iter(automatic));assignment='automatic_proposal'
        else:
            family_id=None;assignment='requires_reconciliation'
        f['raw_family']=f.get('family')
        f['family_id']=family_id
        f['family']=families[family_id]['name'] if family_id in families else 'Rattachement à préciser'
        f['family_assignment_status']=assignment
        f['family_review_is_not_fact_validation']=True
        out.append(f)
    occurrences=[{'extraction_id':e['id'],'source_fact_id':e.get('fact_id'),
                  'canonical_fact_id':aliases.get(e.get('fact_id')),'review_index':e['review_index'],
                  'quote':e['quote'],'value':e['attributes'].get('value'),'presence':e['attributes'].get('presence'),
                  'condition':e['attributes'].get('condition'),'start':e.get('start'),'end':e.get('end')} for e in extractions]
    return {'source_run':data['source_run'],'source_fingerprint':data['source_fingerprint'],
            'published':False,'settings':{'similarity':.88,'decision_confidence':.75},
            'facts':out,'aliases':aliases,'occurrences':occurrences}
