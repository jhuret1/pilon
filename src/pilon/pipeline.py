import math
import threading
import time
import re
import numpy as np
from .providers import OpenRouter, MODELS, PROMPT
from .store import Paused, digest

ALLOWED = {
    'presence': {'present', 'absent', 'unknown', 'not_applicable'},
    'condition': {'working', 'broken', 'resolved', 'unknown', 'not_applicable'},
    'subject': {'reviewed_item', 'other_item', 'advertisement', 'unknown'},
    'temporality': {'during_use', 'past', 'resolved', 'unknown'},
}


def ground(text, extraction):
    out = dict(extraction)
    a, b = out.get('start'), out.get('end')
    exact = type(a) is int and type(b) is int and 0 <= a < b <= len(text) and text[a:b] == out.get('quote')
    attrs = out.get('attributes', {})
    valid = isinstance(attrs, dict) and all(isinstance(attrs.get(k), str) and attrs[k] in values for k, values in ALLOWED.items())
    valid = valid and all(isinstance(attrs.get(k), str) and bool(attrs[k].strip()) for k in ('concept', 'definition', 'family', 'value'))
    if valid and attrs['presence'] == 'absent' and attrs['condition'] in ('broken', 'working', 'resolved'):
        valid = False
    out['proof_status'] = 'exact_span' if exact else 'invalid_span'
    out['contract_valid'] = valid
    context = attrs.get('context', '') if isinstance(attrs, dict) else ''
    if context and (not isinstance(context, str) or context not in text):
        out['proof_status'] = 'invalid_context'
    out['usable'] = exact and valid and out['proof_status'] == 'exact_span'
    return out


def signature(ext, mode):
    a = ext['attributes']
    if mode == 'identity':
        return a['concept'] + ' | ' + a['definition']
    return 'Équipement: ' + a['concept'] + ' | Statut: ' + a['value'] + ' ; ' + a['presence'] + ' ; ' + a['condition']


def nearest(vector, facts, k):
    if not facts:
        return []
    query = np.asarray(vector, dtype=np.float32)
    scores = np.asarray([float(np.max(np.asarray(f.get('anchor_vectors') or [f['vector']], dtype=np.float32) @ query)) for f in facts])
    ids = np.argsort(-scores, kind='stable')[:k]
    return [{**facts[int(i)], 'similarity': float(scores[i])} for i in ids]


def route(answers, ext, candidates, threshold):
    r, s = answers['routing'], answers['support']
    if ext['attributes']['subject'] != 'reviewed_item':
        return 'not_applicable'
    for answer in (r, s):
        confidence = answer.get('confidence')
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not threshold <= confidence <= 1:
            return 'ambiguous'
    if s['choice'] != 'supported':
        return 'invalid_evidence' if s['choice'] == 'unsupported' else 'ambiguous'
    if r['choice'] in {c['id'] for c in candidates}:
        return 'known'
    return r['choice']


class Engine:
    def __init__(self, store, key, provider_factory=OpenRouter):
        self.store, self.key, self.provider_factory = store, key, provider_factory
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        self.store.recover()
        self.thread = threading.Thread(target=self.loop, daemon=True, name='pilon-worker')
        self.thread.start()

    def loop(self):
        while not self.stop.is_set():
            run = next((r for r in reversed(self.store.runs()) if r['status'] in ('queued', 'running')), None)
            if run:
                try:
                    if run['status'] == 'queued':
                        run['status'] = 'running'
                        self.store.save(run)
                    self.process(run)
                except Paused as exc:
                    run['status'] = 'paused'
                    run['error'] = str(exc)
                    self.store.save(run)
                except Exception:
                    import logging
                    logging.exception('PILON worker failed for run %s',run['id'])
                    run['status'] = 'failed'
                    run['error'] = 'Étape invalide ou indisponible. Résultats et réponses conservés ; consulter le journal.'
                    self.store.save(run)
            else:
                self.stop.wait(.5)

    def checkpoint(self, run):
        if self.store.run(run['id'])['status'] != 'running' or self.stop.is_set():
            raise Paused('Pause demandée ; étapes terminées conservées.')
        self.store.save(run)

    def process(self, run):
        if run['config'].get('purpose') != 'canonical_corpus':
            raise ValueError('Only canonical corpus induction is supported in this release.')
        from .streaming import process_corpus
        return process_corpus(self, run)

def metrics(run, calls):
    ext = run['extractions']
    counts = {k: sum(e['route'] == k for e in ext) for k in ('known', 'new_candidate', 'ambiguous', 'not_applicable', 'invalid_evidence')}
    stages = {}
    for stage in ('extraction', 'embedding', 'decision', 'definition'):
        subset = [c for c in calls if c['stage'] == stage]
        times = [c['elapsed_ms'] for c in subset if c['elapsed_ms'] is not None]
        stages[stage] = {'calls': len(subset), 'cost': sum(c['cost'] or 0 for c in subset),
                         'unknown_cost': sum(c['cost'] is None for c in subset),
                         'tokens': sum(token_count((c['response'] or {}).get('usage', {})) for c in subset),
                         'p50_ms': float(np.percentile(times, 50)) if times else None,
                         'p95_ms': float(np.percentile(times, 95)) if times else None}
    return {'routes': counts, 'extractions': len(ext), 'linked':sum(bool(e.get('fact_id')) for e in ext), 'arbitrated': sum(e.get('enrichment_mode') == 'jev_incremental' for e in ext),
            'bootstrap_count': sum(e.get('enrichment_mode') == 'bootstrap_first' for e in ext),
            'exact_spans': sum(e['proof_status'] == 'exact_span' for e in ext), 'processed': run['processed'],
            'total_reviews': len(run['rows']), 'cost': sum(c['cost'] or 0 for c in calls),
            'reserved': sum(c['reserved'] for c in calls if c['cost'] is None),
            'unknown_cost': sum(c['cost'] is None for c in calls), 'calls': len(calls), 'stages': stages,
            'precision': None, 'recall': None, 'quality_status': 'not_measured'}


def token_count(usage):
    # Decisions uses input_tokens/output_tokens; Chat uses prompt/completion_tokens.
    return (usage.get('total_tokens') or
            (usage.get('input_tokens', usage.get('prompt_tokens', 0)) or 0) +
            (usage.get('output_tokens', usage.get('completion_tokens', 0)) or 0))
