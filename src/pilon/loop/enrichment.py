"""Explicit handoff from reviewed Benchmark proposals to product evidence jobs."""
from copy import deepcopy

from .store import fingerprint


def _selected_catalog(catalog, manifest):
    """Validate explicit asset routing; absent IDs retain the legacy full catalog."""
    if not isinstance(manifest, dict):
        raise ValueError('Source routing manifests must be objects')
    if 'selected_record_ids' not in manifest:
        return catalog
    ids = manifest['selected_record_ids']
    if (not isinstance(ids, list)
            or any(not isinstance(rid, str) or not rid.strip() for rid in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('selected_record_ids must contain distinct nonempty catalog IDs')
    by_id = {}
    for row in catalog:
        rid = row.get('id')
        if not isinstance(rid, str) or not rid.strip() or rid in by_id:
            raise ValueError('Explicit routing requires distinct nonempty catalog record IDs')
        by_id[rid] = row
    if any(rid not in by_id for rid in ids):
        raise ValueError('selected_record_ids must refer to known catalog records')
    count = len(ids)
    for field in ('selected_assets', 'matching_assets', 'indexed_assets',
                  'unassessed_outside_shortlist', 'limit'):
        if field in manifest and (type(manifest[field]) is not int or manifest[field] < 0):
            raise ValueError('Source routing '+field+' must be a nonnegative integer')
    if 'selected_assets' in manifest and manifest['selected_assets'] != count:
        raise ValueError('selected_assets must match selected_record_ids')
    for field in ('matching_assets', 'indexed_assets', 'limit'):
        if field in manifest and manifest[field] < count:
            raise ValueError('Source routing '+field+' cannot be smaller than selected_assets')
    if ('matching_assets' in manifest and 'indexed_assets' in manifest
            and manifest['matching_assets'] > manifest['indexed_assets']):
        raise ValueError('matching_assets cannot exceed indexed_assets')
    if ('unassessed_outside_shortlist' in manifest and 'indexed_assets' in manifest
            and manifest['unassessed_outside_shortlist'] != manifest['indexed_assets'] - count):
        raise ValueError('unassessed_outside_shortlist must match indexed_assets minus selected_assets')
    selected = set(ids)
    # Preserve source order, including for geometry, independent of manifest ID order.
    return [row for row in catalog if row['id'] in selected]


def prepare_enrichment(queue, benchmark_job, candidate_keys, catalog_records, *, routing=None):
    source = queue.get(benchmark_job)
    if source['status'] != 'completed':
        raise ValueError('Select proposals from a completed Benchmark')
    payload = source['payload']
    bp = (source.get('result') or {}).get('benchmark')
    if not bp:
        raise ValueError('Source job has no completed Benchmark snapshot')
    available = {c['key']: c for c in bp['candidates']}
    if not candidate_keys or len(set(candidate_keys)) != len(candidate_keys) or any(key not in available for key in candidate_keys):
        raise ValueError('Select distinct existing Benchmark candidate keys')
    model = payload['model']
    facets = {f['key']:f for f in model.get('facets', [])}
    grouped = {}
    for source_key in candidate_keys:
        candidate = available[source_key]
        if candidate['gap_type'] not in {'schema_gap', 'value_gap', 'filter_proposal', 'coverage_gap'}:
            raise ValueError('Resolve intent before extracting product facts')
        # Review occurrence IDs must never become duplicate catalog attribute IDs.
        target = candidate.get('fact_key') if candidate['gap_type'] != 'filter_proposal' else None
        target = target or candidate.get('proposed_key')
        if not target and candidate.get('detection') != 'agent_semantic_review' and not source_key.startswith('review_'):
            from .benchmark import _identifier
            known_targets = [key for key in facets if _identifier(key) == source_key]
            if len(known_targets) > 1:
                raise ValueError('Ambiguous canonical attribute target')
            target = known_targets[0] if known_targets else source_key
        if not target:
            raise ValueError('Define a stable proposed_key before enrichment')
        if candidate['gap_type'] == 'schema_gap' and target in facets:
            raise ValueError('New attribute already exists in the model')
        if candidate['gap_type'] == 'value_gap' and target not in facets:
            raise ValueError('Value extension must refer to an existing attribute')
        item = grouped.setdefault(target, dict(key=target, label=facets.get(target,{}).get('label') or candidate['label'],
            definition=candidate.get('definition',''), aliases=[], gap_type=candidate['gap_type'],
            status='needs_extraction', source_candidate_keys=[], demand_records=[], demand_events=0))
        if item['gap_type'] != candidate['gap_type']:
            raise ValueError('Conflicting proposal kinds for one target')
        item['aliases'] = sorted(set(item['aliases']) | set(candidate.get('aliases',[])) | {candidate['label']})
        item['source_candidate_keys'].append(source_key)
        item['demand_records'].extend(deepcopy(candidate.get('demand_records',[])))
    demand_counts = {r['id']:r.get('count',1) for r in payload['records'] if r.get('role')=='demand'}
    for item in grouped.values():
        item['demand_events'] = sum(demand_counts[rid] for rid in {p['record_id'] for p in item['demand_records']})
    source_routing = deepcopy(routing) if routing is not None else {}
    if not isinstance(source_routing, dict):
        raise ValueError('Source routing must refer to selected target keys')
    if source_routing and 'method' in source_routing:
        if len(grouped) != 1:
            raise ValueError('Provide a routing manifest per target when enriching multiple facts')
        source_routing = {next(iter(grouped)):source_routing}
    if not isinstance(source_routing,dict) or any(key not in grouped for key in source_routing):
        raise ValueError('Source routing must refer to selected target keys')
    catalog = list(catalog_records)
    if not catalog or any(r.get('role') != 'catalog' or r.get('category') != model['category'] for r in catalog):
        raise ValueError('Enrichment needs product sources from the same declared dataset')
    for manifest in source_routing.values():
        _selected_catalog(catalog, manifest)
    demands = [deepcopy(r) for r in payload['records'] if r.get('role') == 'demand']
    records = demands + deepcopy(catalog)
    selection = dict(schema_version=1, stage='benchmark', category=model['category'], candidates=list(grouped.values()),
        metrics=dict(candidate_count=len(grouped), source_records=len(records),
                     inventory_products=len({r['product_id'] for r in catalog})),
        parent_job=benchmark_job, parent_benchmark_hash=fingerprint(bp),
        selection_status='explicit_reviewed_proposals', source_routing=source_routing)
    options = dict(prepared_benchmark=selection, exhaustive=True, through='projection')
    return queue.enqueue(model, records, options=options, synthetic=payload.get('synthetic',False))
