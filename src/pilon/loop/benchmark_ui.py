"""Read-only Benchmark workspace. Product extraction is deliberately not exposed here."""
from collections import Counter
from copy import deepcopy
from importlib.resources import files
import json

from .benchmark import _identifier
from .recommendations import build_recommendations
from .presentation import apply_display_translations
from .report import _entries, _mapping


def build_view(report, *, records=None, benchmark=None, display_translations=None):
    """Build a demand-only view; never substitute projected/product evidence for demand."""
    report = _mapping(report)
    model = deepcopy(_mapping(report.get('model')))
    schema_only = model.get('assessment_scope') == 'schema_only'
    unknown_period = model.get('observation_period') == 'unknown'
    bp = _mapping(benchmark or report.get('benchmark'))
    candidates = deepcopy(_entries(bp.get('candidates', report.get('candidates', []))))
    candidates.sort(key=lambda c: (-c.get('demand_events', 0), str(c.get('key', ''))))
    by_record = {}
    for c in candidates:
        for p in c.get('demand_records', []):
            by_record.setdefault(p.get('record_id'), []).append(dict(candidate_key=c['key'], **p))
    represented = deepcopy(_entries(bp.get('already_represented', report.get('already_represented', []))))
    represented_by_record = {}
    for entry in represented:
        represented_by_record.setdefault(entry.get('record_id'), []).append(entry)
    complete_inputs = records is not None
    if complete_inputs:
        demands = [deepcopy(r) for r in records if r.get('role') == 'demand'
                   and (r.get('category') == model.get('category') or (schema_only and not model.get('category')))
                   and (unknown_period or str(model.get('window_start', '')) <= str(r.get('date', ''))
                        <= str(model.get('window_end', '9999')))]
    else:
        demands = [dict(id=rid, text=proofs[0].get('quote', ''), source=proofs[0].get('source', ''),
                        count=proofs[0].get('count', 1), excerpt_only=True) for rid, proofs in by_record.items()]
        # A lexical schema match may have no candidate proof or full query text.
        # Keep its identity without inventing the query from an attribute label.
        for rid, entries in represented_by_record.items():
            if rid not in by_record:
                proof = _mapping(entries[0].get('evidence')) or entries[0]
                demands.append(dict(id=rid, text=proof.get('quote', ''), source=proof.get('source', ''),
                                    count=proof.get('count', 1), excerpt_only=True))
    for r in demands:
        r['matches'] = by_record.get(r['id'], [])
        r['represented'] = represented_by_record.get(r['id'], [])
    # The model is already a private snapshot; keep its large value sets shared
    # with the attribute view instead of copying them a second time.
    facets = _entries(model.get('facets', []))
    keys = {str(f.get('key')) for f in facets}
    for name in model.get('existing_facets', []):
        key = _identifier(name)
        if key not in keys:
            facets.append(dict(key=key, label=name, values=[]))
            keys.add(key)
    metrics = deepcopy(_mapping(bp.get('metrics') or _mapping(report.get('metrics')).get('benchmark')))
    inventory = metrics.get('inventory_products')
    if schema_only:
        inventory = None
        metrics['inventory_products'] = None
    elif inventory is None and complete_inputs:
        inventory = len({r['product_id'] for r in records if r.get('role') == 'catalog'
                         and r.get('category') == model.get('category') and r.get('product_id')}
                        | {a['product_id'] for a in model.get('assignments', []) if a.get('product_id')})
    gaps = Counter(c.get('gap_type', 'unknown') for c in candidates)
    channels = {}
    for r in demands:
        s = channels.setdefault(r.get('source', 'unknown'), dict(records=0, events=0))
        s['records'] += 1
        s['events'] += r.get('count', 1)
    ready = bool(bp) or bool(candidates) or report.get('status') == 'completed'
    product_view = (build_recommendations(model, demands, candidates, represented)
                    if _mapping(bp.get('analysis')).get('method') == 'agent_semantic_review'
                    and _mapping(bp.get('analysis')).get('status') == 'reviewed' else None)
    view = dict(id=report.get('id'), status=report.get('status', 'empty'), ready=ready,
                product_view=product_view,
                synthetic=bool(report.get('synthetic')), model=model, attributes=facets, candidates=candidates,
                demands=demands, already_represented=represented, channels=channels, jobs=deepcopy(report.get('jobs', [])),
                error=report.get('error'), complete_inputs=complete_inputs,
                metrics=metrics, analysis=deepcopy(_mapping(bp.get('analysis', report.get('analysis')))),
                summary=dict(demand_events=sum(r.get('count', 1) for r in demands),
                             demand_records=len(demands), opportunity_count=len(candidates),
                             schema_gaps=gaps['schema_gap'], inventory_products=inventory,
                             gaps=dict(gaps), attributes=len(facets)))
    return apply_display_translations(view, display_translations)


def render_benchmark(report, *, records=None, benchmark=None, display_translations=None):
    data = build_view(report, records=records, benchmark=benchmark, display_translations=display_translations)
    if data['model'].get('assessment_scope') == 'schema_only' and data['attributes'] == data['model'].get('facets'):
        # Thousands of observed value sets belong to the frozen model. Serialize
        # them once; the local UI uses that same snapshot for browsing and export.
        data.pop('attributes')
    # Script data must not terminate its element, even when a source contains HTML.
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    assets = files('pilon').joinpath('loop', 'ui')
    html = assets.joinpath('benchmark.html').read_text(encoding='utf-8')
    return html.replace('/* STYLES */', assets.joinpath('benchmark.css').read_text(encoding='utf-8')).replace(
        '/* APPLICATION */', assets.joinpath('benchmark.js').read_text(encoding='utf-8')).replace('/* DATA */', payload)
