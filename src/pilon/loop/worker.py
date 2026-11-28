"""Checkpointed background enrichment; publication is a separate operation."""
from copy import deepcopy
import threading
import time

from .benchmark import benchmark
from .enrichment import _selected_catalog
from .store import fingerprint, LeaseLost
from .. import __version__

ENGINE_VERSION = "background-loop-v1"


def _inference_metrics(options):
    """Separate recorded model work from the local replay of its decisions."""
    supplied = options.get('inference')
    if not isinstance(supplied, dict):
        return {}
    allowed = ('provider', 'model', 'calls', 'failed_calls', 'input_tokens', 'output_tokens',
               'provider_cost_usd', 'estimated_cost_usd', 'elapsed_seconds',
               'cached_records', 'new_records', 'cost_basis', 'usage_reported_calls',
               'provider_cost_reported_calls', 'known_provider_cost_usd')
    usage = {key: deepcopy(supplied[key]) for key in allowed if key in supplied}
    return dict(inference=usage, llm_calls=usage.get('calls'),
                api_cost_usd=usage.get('provider_cost_usd'),
                estimated_cost_usd=usage.get('estimated_cost_usd'),
                provider=usage.get('provider', 'model_connector'),
                inference_accounting='Recorded connector usage; estimates are not provider billing. Local replay time is separate.')


def report(queue, job_id):
    job = queue.get(job_id)
    if job['result']:
        out = deepcopy(job['result'])
    else:
        payload = job['payload']
        bp = queue.checkpoint(job_id, 'benchmark')
        candidates = bp['data']['candidates'] if bp else []
        extractions = []
        geometries = []
        for c in candidates:
            stage = queue.checkpoint(job_id, 'extract:'+c['key'])
            if stage:
                extractions.append(stage['data'])
            diagnostic = queue.checkpoint(job_id,'geometry:'+c['key'])
            if diagnostic:
                geometries.append(diagnostic['data'])
        pp = queue.checkpoint(job_id, 'projection')
        out = dict(schema_version=1,id=job_id,model=payload['model'],candidates=candidates,
                   extractions=extractions,geometry=geometries,projection=pp['data'] if pp else None,metrics={},synthetic=payload['synthetic'])
    out.update(status=job['status'],stage=job['stage'],events=job['events'],error=job['error'])
    receipts=[e['detail'] for e in job['events'] if e['kind']=='publication_receipt']
    out['publication']=dict(status='not_published',receipts=receipts)
    if receipts:
        from .projection import read_published
        latest=receipts[-1]
        try:
            current=read_published(latest['store'])
            out['publication'].update(status='published' if current['snapshot_hash']==latest['snapshot_hash'] else 'superseded',
                                      current_revision=current['revision'],current_hash=current['snapshot_hash'])
        except (OSError,ValueError):
            out['publication']['status']='unavailable'
    return out


def run_once(queue, *, job_id=None, lease_seconds=60, hooks=None):
    """Claim one job; hooks allow injected stage implementations for integration tests."""
    from .extraction import extract
    from .projection import build_projection
    hooks = hooks or {}
    job = queue.claim(job_id=job_id,lease_seconds=lease_seconds)
    if job is None:
        return None
    jid, owner, payload = job['id'], job['owner'], job['payload']
    stop, lease_errors = threading.Event(), []
    def keep_alive():
        while not stop.wait(max(.05,lease_seconds/3)):
            try:
                queue.heartbeat(jid,owner,lease_seconds)
            except Exception as exc:
                lease_errors.append(exc); return
    heartbeat = threading.Thread(target=keep_alive,name='pilon-lease',daemon=True)
    heartbeat.start()
    started = time.perf_counter()
    reused = []
    def stage(name, inputs, fn):
        if lease_errors:
            raise lease_errors[0]
        key = fingerprint([ENGINE_VERSION,name,inputs])
        old = queue.checkpoint(jid,name)
        if old:
            if old['input_hash']!=key:
                raise ValueError("Frozen stage input changed; cannot resume")
            reused.append(name)
            return old['data']
        cached = queue.cached(key)
        result = cached if cached is not None else fn()
        queue.save_stage(jid,owner,name,key,result,cache_hit=cached is not None)
        if cached is not None:
            reused.append(name)
        return result
    try:
        model, records = payload['model'], payload['records']
        options = payload['options']
        prepared = options.get('prepared_benchmark')
        if prepared is not None:
            bp = stage('benchmark',dict(model=model,records=records,prepared=prepared), lambda: deepcopy(prepared))
        else:
            bp = stage('benchmark',dict(model=model,records=records),
                       lambda: hooks.get('benchmark',benchmark)(model,records))
        inference_metrics = _inference_metrics(options)
        if inference_metrics:
            bp = deepcopy(bp)
            bp['analysis'] = dict(bp.get('analysis', {}), execution='model_connector',
                                  inference=inference_metrics['inference'],
                                  api_cost_usd=inference_metrics['api_cost_usd'],
                                  inference_accounting=inference_metrics['inference_accounting'])
            bp['metrics'] = dict(bp.get('metrics', {}), llm_calls=inference_metrics['llm_calls'],
                                 detector='model connector decisions')
            for entry in bp.get('candidates', []) + bp.get('already_represented', []):
                entry['validation_status'] = 'model_reviewed_not_independently_audited'
        if options.get('audit') is not None:
            from .audit import validate_audit
            bp = dict(bp, audit=validate_audit(options['audit'], model, records))
        candidates, extractions, geometries = bp['candidates'], [], []
        if options.get('through') == 'benchmark' or (model.get('assessment_scope') == 'schema_only' and prepared is None):
            result = dict(schema_version=1,id=jid,model=model,candidates=candidates,benchmark=bp,
                          extractions=[],geometry=[],projection=None,synthetic=payload['synthetic'],
                          producer=dict(version=__version__,engine=ENGINE_VERSION),
                          metrics=dict(benchmark=bp['metrics'],elapsed_seconds=time.perf_counter()-started,
                                       reused_stages=reused,llm_calls=0,api_cost_usd=0,
                                       provider='imported_agent_decisions' if bp.get('analysis') else 'local_baseline'))
            result['metrics'].update(inference_metrics)
            queue.finish(jid,owner,result,stage='benchmark')
            return report(queue,jid)
        catalog = [r for r in records if r.get('role')=='catalog' and r.get('category')==model['category']]
        source_routing = bp.get('source_routing', {}) if prepared is not None else {}
        if 'method' in source_routing:
            if len(candidates) != 1:
                raise ValueError('Provide a routing manifest per target when enriching multiple facts')
            source_routing = {candidates[0]['key']: source_routing}
        extraction_options = {k:v for k,v in options.items() if k != 'prepared_benchmark'}
        for c in candidates:
            if c['gap_type'] in ('unresolved_intent','retrieval_gap'):
                extractions.append(dict(candidate_key=c['key'],status='needs_definition' if c['gap_type']=='unresolved_intent' else 'search_integration_needed',
                                        assignments=[],conflicts=[],unknown_products=[],routing=[],metrics={}))
                continue
            target = {k:deepcopy(c[k]) for k in ('key','label','definition','aliases') if k in c}
            target.update({k:c[k] for k in ('embedding','embedding_contract') if k in c})
            selected_catalog = _selected_catalog(catalog, source_routing.get(c['key'], {}))
            inputs = dict(candidate=target,records=selected_catalog,model=model,options=extraction_options)
            extraction = stage('extract:'+c['key'],inputs,
                lambda c=c, selected_catalog=selected_catalog: hooks.get('extract',extract)(c,selected_catalog,model,
                    top_k=options.get('top_k',50),exhaustive=options.get('exhaustive',False)))
            extractions.append(extraction)
            if options.get('geometry',False):
                from .geometry import analyze_geometry
                diagnostic=stage('geometry:'+c['key'],dict(candidate=target,records=selected_catalog),
                                 lambda target=target, selected_catalog=selected_catalog: analyze_geometry(target,selected_catalog))
                geometries.append(diagnostic)
        projection = stage('projection',dict(model=model,candidates=candidates,extractions=extractions),
                           lambda: hooks.get('projection',build_projection)(model,candidates,extractions))
        result = dict(schema_version=1,id=jid,model=model,candidates=candidates,benchmark=bp,extractions=extractions,geometry=geometries,
                      projection=projection,synthetic=payload['synthetic'],producer=dict(version=__version__,engine=ENGINE_VERSION),
                      metrics=dict(benchmark=bp['metrics'],elapsed_seconds=time.perf_counter()-started,
                                   reused_stages=reused,llm_calls=0,api_cost_usd=0,
                                   provider='local_baseline',geometry='inspection_only' if geometries else 'not_requested',
                                   inference_accounting='Local replay only; supplied annotation generation is not metered.'))
        result['metrics'].update(inference_metrics)
        queue.finish(jid,owner,result)
    except KeyboardInterrupt as exc:
        queue.fail(jid,owner,exc,retryable=True)
        raise
    except LeaseLost:
        raise
    except Exception as exc:
        queue.fail(jid,owner,exc)
        raise
    finally:
        stop.set(); heartbeat.join(timeout=2)
    return report(queue,jid)
