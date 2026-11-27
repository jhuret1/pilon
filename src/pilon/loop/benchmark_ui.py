"""Read-only Benchmark workspace. Product extraction is deliberately not exposed here."""
from collections import Counter
from copy import deepcopy
from importlib.resources import files
import json

from .benchmark import _identifier
from .report import _entries, _mapping


def build_view(report, *, records=None, benchmark=None):
    """Build a demand-only view; never substitute projected/product evidence for demand."""
    report = _mapping(report)
    model = deepcopy(_mapping(report.get('model')))
    bp = _mapping(benchmark or report.get('benchmark'))
    candidates = deepcopy(_entries(bp.get('candidates', report.get('candidates', []))))
    candidates.sort(key=lambda c: (-c.get('demand_events', 0), str(c.get('key', ''))))
    by_record = {}
    for c in candidates:
        for p in c.get('demand_records', []):
            by_record.setdefault(p.get('record_id'), []).append(dict(candidate_key=c['key'], **p))
    complete_inputs = records is not None
    if complete_inputs:
        demands = [deepcopy(r) for r in records if r.get('role') == 'demand'
                   and r.get('category') == model.get('category')
                   and str(model.get('window_start', '')) <= str(r.get('date', '')) <= str(model.get('window_end', '9999'))]
    else:
        demands = [dict(id=rid, text=proofs[0].get('quote', ''), source=proofs[0].get('source', ''),
                        count=proofs[0].get('count', 1), excerpt_only=True) for rid, proofs in by_record.items()]
    for r in demands:
        r['matches'] = by_record.get(r['id'], [])
    facets = deepcopy(_entries(model.get('facets', [])))
    keys = {str(f.get('key')) for f in facets}
    for name in model.get('existing_facets', []):
        key = _identifier(name)
        if key not in keys:
            facets.append(dict(key=key, label=name, values=[]))
            keys.add(key)
    metrics = _mapping(bp.get('metrics') or _mapping(report.get('metrics')).get('benchmark'))
    inventory = metrics.get('inventory_products')
    if inventory is None and complete_inputs:
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
    return dict(id=report.get('id'), status=report.get('status', 'empty'), ready=ready,
                synthetic=bool(report.get('synthetic')), model=model, attributes=facets, candidates=candidates,
                demands=demands, channels=channels, jobs=deepcopy(report.get('jobs', [])),
                error=report.get('error'), complete_inputs=complete_inputs,
                metrics=deepcopy(metrics),
                summary=dict(demand_events=sum(r.get('count', 1) for r in demands),
                             demand_records=len(demands), opportunity_count=len(candidates),
                             schema_gaps=gaps['schema_gap'], inventory_products=inventory,
                             gaps=dict(gaps), attributes=len(facets)))


def render_benchmark(report, *, records=None, benchmark=None):
    data = build_view(report, records=records, benchmark=benchmark)
    # Script data must not terminate its element, even when a source contains HTML.
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    assets = files('pilon').joinpath('loop', 'ui')
    html = assets.joinpath('benchmark.html').read_text(encoding='utf-8')
    return html.replace('/* STYLES */', assets.joinpath('benchmark.css').read_text(encoding='utf-8')).replace(
        '/* APPLICATION */', assets.joinpath('benchmark.js').read_text(encoding='utf-8')).replace('/* DATA */', payload)
