"""Dedicated read-only Extract / Induct workspaces over existing loop reports.

Pure HTML rendering: no I/O, extraction, projection, publication or input mutation.
Missing checkpoints stay unavailable. Diffs compare full snapshots, preserving
value types and evidence changes. All supplied data is escaped HTML text; only
encoded local job links become URLs. The inline script only searches and pages
already-rendered content, which is also fully accessible without JavaScript.
"""

from collections.abc import Mapping
from html import escape
import json
from urllib.parse import quote


_LABELS = {
    "needs_extraction": "Awaiting extraction", "needs_review": "Needs review",
    "needs_definition": "Definition needed", "search_integration_needed": "Search integration needed",
    "unresolved_intent": "Intent needs clarification", "schema_gap": "Missing facet",
    "coverage_gap": "Incomplete coverage", "retrieval_gap": "Retrieval gap",
    "completed": "Completed", "running": "Running", "queued": "Queued",
    "failed": "Failed", "cancelled": "Cancelled", "partial": "Partial results",
    "proposed": "Proposed", "backlog": "Awaiting evidence", "blocked": "Blocked",
    "not_published": "Not published", "unpublished": "Not published",
    "published": "Published", "superseded": "Superseded", "rolled_back": "Rolled back",
    "unavailable": "Unavailable", "not_performed": "Not performed",
    "exact_source_verified": "Exact source verified (reported)",
    "lexical": "Lexical routing", "cosine": "Cosine similarity",
    "cosine_then_lexical": "Cosine similarity, then lexical routing",
    "exhaustive": "All supported assets", "lexical_match": "Lexical match",
    "no_lexical_match": "No lexical match", "cosine_rank": "Cosine ranking",
    "budget_limit": "Selection budget reached", "not_catalog": "Outside catalog",
    "outside_category": "Outside category", "analysed": "Analyzed",
    "analyzed": "Analyzed", "unanalysed": "Unanalyzed", "unanalyzed": "Unanalyzed",
    "explicit_extractor_required": "Explicit extractor required",
    "document_text_unavailable": "Document text unavailable",
    "extractor_callback": "Extractor callback", "supplied_annotation": "Supplied annotation",
    "labeled_specs": "Labeled specifications", "no_evidence": "No supporting evidence",
    "unknown_product": "Product value unknown", "conflict": "Conflicting values",
    "unknown_candidate": "Candidate not found", "invalid_evidence": "Evidence validation failed",
    "invalid_assignment": "Invalid assignment", "missing_value": "Value missing",
    "conflicting_candidates": "Conflicting candidate definitions",
    "conflicting_extractions": "Conflicting extraction results",
    "existing_assignment_conflict": "Conflicts with an existing assignment",
    "existing_schema_conflict": "Conflicts with the existing schema",
    "sqlite_fts5_bm25": "Full-text search (FTS5 / BM25)", "not_measured": "Not measured",
}


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _items(value):
    return list(value) if isinstance(value, (list, tuple)) else []


def _entries(value, key="key"):
    if isinstance(value, Mapping):
        if key in value:
            return [dict(value)]
        return [dict(item, **{key: item.get(key, name)}) if isinstance(item, Mapping)
                else {key: name, "value": item} for name, item in value.items()]
    return [dict(item) if isinstance(item, Mapping) else {key: item} for item in _items(value)]


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _text(value):
    if value is None:
        return "Not reported"
    if isinstance(value, (bool, Mapping, list, tuple)):
        return _json(value)
    return str(value)


def _e(value):
    return escape(_text(value), quote=True)


def _label(value):
    return _LABELS.get(str(value), _text(value))


def _badge(value, tone="neutral"):
    return f'<span class="badge {tone}">{_e(_label(value))}</span>'


def _empty(message):
    return f'<p class="empty">{_e(message)}</p>'


def _raw(title, value):
    text = _json(value)
    if len(text) > 24000:
        text = text[:24000] + '\n… Preview truncated. The complete snapshot is available through the JSON link below.'
    return f'<details class="raw"><summary>{_e(title)}</summary><pre>{_e(text)}</pre></details>'


def _fields(pairs):
    return '<dl class="facts">' + ''.join(
        f'<div><dt>{_e(name)}</dt><dd>{_e(value)}</dd></div>' for name, value in pairs) + '</dl>'


def _value(value):
    # An explicit false, zero or null must never turn into an empty-state label.
    return _e("null" if value is None else value)


def _route(snapshot, product):
    identifier = snapshot.get("id")
    if product == 'benchmark':
        identifier = _mapping(snapshot.get('benchmark')).get('parent_job') or identifier
    if not isinstance(identifier, str) or not identifier.strip() or identifier in {".", ".."}:
        return None
    prefix = "jobs" if product == "benchmark" else product
    return f'/{prefix}/{quote(identifier, safe="")}'


def _link(snapshot, product, label):
    target = _route(snapshot, product)
    return (f'<a href="{_e(target)}">{_e(label)} <span aria-hidden="true">↗</span></a>'
            if target else f'<span class="muted">{_e(label)} · job unavailable</span>')


def _collection(identifier, content, noun, *, table_head=None, page_size=8):
    """All rows render server-side; progressive paging never discards source data."""
    controls = (f'<div class="collection-tools" data-tools hidden><label for="search-{identifier}">'
                f'Search {noun}<input id="search-{identifier}" type="search" '
                'placeholder="Search this list" autocomplete="off"></label>'
                '<div class="pager"><button type="button" data-prev>Previous</button>'
                '<output aria-live="polite"></output><button type="button" data-next>Next</button></div></div>')
    if table_head:
        caption, headings = table_head
        body = ('<div class="table-scroll" role="region" tabindex="0" '
                f'aria-label="{_e(caption)}"><table><caption>{_e(caption)}</caption><thead><tr>'
                + ''.join(f'<th scope="col">{_e(h)}</th>' for h in headings)
                + '</tr></thead><tbody data-items>' + ''.join(content) + '</tbody></table></div>')
    else:
        body = '<div class="item-list" data-items>' + ''.join(content) + '</div>'
    return (f'<div class="collection" id="{identifier}" data-collection data-page-size="{page_size}">'
            + controls + body + '<p data-no-match class="empty" hidden>No matching items in this list.</p></div>')


def _sources(extractions):
    result = {}
    for extraction in extractions:
        for record in _entries(extraction.get("source_records"), "id"):
            group = result.setdefault(_text(record.get("id")), [])
            if record not in group:
                group.append(record)
    return result


def _source(record, proof=None):
    text = record.get("text")
    rendered = _e(text) if isinstance(text, str) else "Source text unavailable."
    if isinstance(text, str) and proof:
        start, end = proof.get("start"), proof.get("end")
        if (type(start) is int and type(end) is int and 0 <= start < end <= len(text)
                and text[start:end] == proof.get("quote")):
            rendered = _e(text[:start]) + '<mark>' + _e(text[start:end]) + '</mark>' + _e(text[end:])
    return ('<details class="source"><summary>Full source · ' + _e(record.get("id")) + '</summary>'
            + _fields((('Source', record.get('source')), ('Product', record.get('product_id')),
                       ('Asset type', record.get('asset_type', 'text')), ('Role', record.get('role'))))
            + f'<pre class="source-text">{rendered}</pre>' + _raw('Original source record', record) + '</details>')


def _proofs(value, sources):
    proofs = _entries(value, "record_id")
    if not proofs:
        return _empty("No quotation reported.")
    parts = ['<div class="proofs">']
    for proof in proofs:
        parts.append('<figure class="proof"><blockquote>' + _e(proof.get('quote')) + '</blockquote>'
                     '<figcaption>' + _e(proof.get('source')) + ' · ' + _e(proof.get('record_id'))
                     + '</figcaption></figure>')
        parts.append('<details class="provenance"><summary>Evidence details &amp; full source</summary>'
                     + _fields((('Grounding', _label(proof.get('grounding_status'))),
                                ('Extraction method', _label(proof.get('extraction_method'))),
                                ('Start offset', proof.get('start')), ('End offset (exclusive)', proof.get('end')))))
        records = sources.get(_text(proof.get('record_id')), [])
        parts.append(''.join(_source(record, proof) for record in records)
                     if records else _empty('Full source record unavailable in this snapshot.'))
        parts.append(_raw('Original evidence', proof) + '</details>')
    return ''.join(parts) + '</div>'


def _number(value):
    return value if type(value) is int and value >= 0 else None


def _asset_counts(result):
    metrics = _mapping(result.get("metrics"))
    retrieval = _mapping(metrics.get("retrieval"))
    extraction = _mapping(metrics.get("extraction"))
    routing = _mapping(result.get("routing"))
    selected = _number(retrieval.get("selected_assets"))
    if selected is None and isinstance(routing.get("selected"), list):
        selected = len(routing["selected"])
    analyzed = _number(extraction.get("analyzed_assets"))
    selected_rows = routing.get("selected")
    if analyzed is None and isinstance(selected_rows, list) and all(
            _mapping(row).get("analysis_status") in {"analysed", "analyzed", "unanalysed", "unanalyzed"}
            for row in selected_rows):
        analyzed = sum(row["analysis_status"] in {"analysed", "analyzed"} for row in selected_rows)
    total = _number(retrieval.get("catalog_assets"))
    unanalyzed = None
    if total is not None and analyzed is not None and total >= analyzed:
        unanalyzed = total - analyzed
    elif selected is not None and analyzed is not None and selected >= analyzed:
        others = []
        for name in ("unselected", "unsupported"):
            count = _number(retrieval.get(name + "_assets"))
            if count is None and isinstance(routing.get(name), list):
                count = len(routing[name])
            others.append(count)
        if all(count is not None for count in others):
            unanalyzed = sum(others) + selected - analyzed
    return selected, analyzed, unanalyzed


def _stats(pairs):
    return '<dl class="stats">' + ''.join(
        f'<div><dt>{_e(label)}</dt><dd>{_e(count) if count is not None else "Unavailable"}</dd></div>'
        for label, count in pairs) + '</dl>'


def _evidence(result):
    proofs = [proof for row in _entries(result.get('assignments'), 'product_id')
              for proof in _entries(row.get('evidence'), 'record_id')]
    for conflict in _entries(result.get('conflicts'), 'product_id'):
        for evidence in _mapping(conflict.get('competing_values')).values():
            proofs.extend(_entries(evidence, 'record_id'))
    return proofs


def _quote_checked(proof, sources):
    quote, start, end = proof.get('quote'), proof.get('start'), proof.get('end')
    if not isinstance(quote, str) or not quote.strip() or type(start) is not int or type(end) is not int:
        return False
    if not 0 <= start < end or end - start != len(quote):
        return False
    records = sources.get(_text(proof.get('record_id')), [])
    if records:
        return any(isinstance(row.get('text'), str) and row['text'][start:end] == quote
                   and (proof.get('product_id') is None or row.get('product_id') == proof['product_id'])
                   for row in records)
    return proof.get('grounding_status') == 'exact_source_verified'


def _semantic_status(results):
    proofs = [proof for result in results for proof in _evidence(result)]
    methods = {proof.get('extraction_method') for proof in proofs}
    if 'supplied_annotation' in methods:
        kind = ('Supplied annotations' if methods == {'supplied_annotation'} else
                'Supplied annotations and other extraction methods')
        checked = all(_quote_checked(proof, _sources([result]))
                      for result in results for proof in _evidence(result))
        return (kind + (' · exact quotes checked' if checked else ' · quote checks incomplete')
                + '; not independently audited')
    states = list(dict.fromkeys(_label(result.get('semantic_validation')) for result in results))
    return 'Semantic validation: ' + (', '.join(states) if states else 'Unavailable')


def _extract_overview(snapshot, candidates, extractions):
    """Count only reported rows; never turn a missing checkpoint into zero."""
    grouped = {}
    for result in extractions:
        grouped.setdefault(_text(result.get('candidate_key')), []).append(result)
    keys = {_text(candidate.get('key')) for candidate in candidates}
    complete = bool(candidates) and keys == set(grouped) and all(len(rows) == 1 for rows in grouped.values())
    complete = complete and snapshot.get('status') == 'completed'
    assignment_rows = [row for result in extractions for row in _entries(result.get('assignments'), 'product_id')]
    assignments_known = bool(extractions) and all(isinstance(result.get('assignments'), (list, tuple, Mapping))
                                                for result in extractions)
    supported = set()
    product_ids_known = True
    for result in extractions:
        sources = _sources([result])
        for row in _entries(result.get('assignments'), 'product_id'):
            proof = any(_quote_checked(p, sources) and
                        (p.get('product_id') is None or p['product_id'] == row.get('product_id'))
                        for p in _entries(row.get('evidence'), 'record_id'))
            if proof:
                if row.get('product_id') is None:
                    product_ids_known = False
                else:
                    supported.add(_json(row['product_id']))
    without_proof = 0
    proof_known = bool(candidates)
    for key in keys:
        rows = grouped.get(key, [])
        if not rows or any(not isinstance(row.get(field), (list, tuple, Mapping))
                           for row in rows for field in ('assignments', 'conflicts')):
            proof_known = False
            continue
        if not any(_quote_checked(p, _sources([row])) for row in rows for p in _evidence(row)):
            without_proof += 1
    complete = complete and assignments_known and proof_known and all(
        result.get('status') not in {'failed', 'partial', 'running', 'queued', 'cancelled'} for result in extractions)

    def reported(value):
        return value if complete else f'{value} reported'

    stats = [('Candidates', len(candidates) if 'candidates' in snapshot or
              'candidates' in _mapping(snapshot.get('benchmark')) else None),
             ('Proposed assignments', reported(len(assignment_rows)) if assignments_known else None),
             ('Distinct supported products', reported(len(supported)) if assignments_known and product_ids_known else None),
             ('Proposals without proof', reported(without_proof) if proof_known else None)]
    selected = [_mapping(result.get('routing')).get('selected') for result in extractions]
    distinct_assets = distinct_products = None
    if selected and all(isinstance(rows, list) and all(isinstance(row, Mapping) for row in rows) for rows in selected):
        rows = [row for group in selected for row in group]
        if all(row.get('record_id') is not None for row in rows):
            distinct_assets = len({_json(row['record_id']) for row in rows})
        if all(row.get('product_id') is not None for row in rows):
            distinct_products = len({_json(row['product_id']) for row in rows})
    counts = [_asset_counts(result) for result in extractions]
    totals = [sum(row[i] for row in counts) if counts and all(row[i] is not None for row in counts)
              else None for i in range(2)]
    upstream = _mapping(_mapping(snapshot.get('benchmark')).get('source_routing'))
    selections = [_mapping(upstream.get(key)) for key in keys]
    inventory = None
    if selections and all(isinstance(row.get('source_sha256'), str) and row['source_sha256']
                          and _number(row.get('indexed_assets')) is not None for row in selections):
        identities = {(row['source_sha256'], row['indexed_assets']) for row in selections}
        if len(identities) == 1 and all(_number(row.get('selected_assets')) is not None and
                                      row['selected_assets'] <= row['indexed_assets'] for row in selections):
            inventory = selections[0]['indexed_assets']
    return stats, complete, distinct_assets, distinct_products, totals, inventory


def _routing(result, identifier, sources):
    routing = _mapping(result.get("routing"))
    parts = ['<details class="routing"><summary>Asset selection &amp; source records</summary>',
             _fields((('Routing', _label(routing.get('method'))), ('Asset budget', routing.get('top_k')),
                      ('Exhaustive', routing.get('exhaustive')), ('Budget truncated', routing.get('truncated')))),
             '<p class="muted">Excluded assets are outside the candidate scope. Unselected and unsupported '
             'assets remain unanalyzed.</p>']
    for name, title in (("selected", "Selected assets"), ("unselected", "Unselected assets"),
                        ("unsupported", "Unsupported assets"), ("excluded", "Excluded assets")):
        entries = _entries(routing.get(name), "record_id")
        parts.append(f'<h4>{title}</h4>')
        rows = []
        for row in entries:
            source = ''.join(_source(record) for record in sources.get(_text(row.get('record_id')), []))
            rows.append('<article class="asset" data-item><h5>' + _e(row.get('record_id')) + '</h5>'
                        + _fields((('Product', row.get('product_id')), ('Source', row.get('source')),
                                   ('Asset type', row.get('asset_type')), ('Reason', _label(row.get('reason'))),
                                   ('Analysis', _label(row.get('analysis_status')))))
                        + source + _raw('Routing record', row) + '</article>')
        parts.append(_collection(f'{identifier}-{name}', rows, 'assets') if rows else
                     _empty('None reported.' if name in routing else 'Routing data unavailable.'))
    parts.append(_raw('Measured metrics', result.get('metrics')))
    # Also retain selected sources when a partial report has no routing entries.
    records = _entries(result.get('source_records'), 'id')
    parts.append('<details><summary>All supplied source records · ' + str(len(records)) + '</summary>'
                 + ''.join(_source(record) for record in records) + '</details></details>')
    return ''.join(parts)


def _product_list(title, values, identifier, explanation):
    if not isinstance(values, (list, tuple, Mapping)):
        return f'<details class="review"><summary>{title} · unavailable</summary>{_empty(explanation)}</details>'
    entries = _entries(values, 'product_id')
    rows = [f'<div class="product-unknown" data-item><strong>{_e(row.get("product_id"))}</strong></div>'
            for row in entries]
    return (f'<details class="review"><summary>{title} · {len(rows)}</summary><p>{_e(explanation)}</p>'
            + (_collection(identifier, rows, 'products', page_size=12) if rows else _empty('None reported.'))
            + '</details>')


def _upstream_selection(selection):
    if not isinstance(selection, Mapping):
        return _empty('Upstream source selection unavailable. Full-catalog coverage is unknown.')
    return ('<div class="upstream"><h3>Upstream source selection</h3>'
            '<p class="muted">The extractor receives a shortlist from this larger asset inventory. '
            'Search matches are retrieval results, not verified product values.</p>'
            + _stats((('Indexed assets · upstream', _number(selection.get('indexed_assets'))),
                      ('Matching assets · upstream', _number(selection.get('matching_assets'))),
                      ('Shortlisted assets · upstream', _number(selection.get('selected_assets'))),
                      ('Unassessed outside shortlist', _number(selection.get('unassessed_outside_shortlist')))))
            + _fields((('Selection method', _label(selection.get('method'))),
                       ('Selection recall', _label(selection.get('selection_recall')))))
            + '<p class="muted">Assets outside the shortlist are unassessed, never evidence of absence.</p>'
            + _raw('Upstream selection details · phrases and source fingerprint', selection) + '</div>')


def _extraction(result, identifier):
    sources = _sources([result])
    counts = _asset_counts(result)
    parts = []
    if result.get('error'):
        parts.append('<p class="notice warning">' + _e(result['error']) + '</p>')
    rows = []
    for assignment in _entries(result.get('assignments'), 'product_id'):
        rows.append('<article class="assignment" data-item><div class="value-heading"><h4>'
                    + _e(assignment.get('product_id')) + '</h4><strong class="value">'
                    + (_value(assignment['value']) if 'value' in assignment else 'Value unavailable')
                    + '</strong></div>' + _proofs(assignment.get('evidence'), sources) + '</article>')
    parts.append('<h3>Product values</h3>')
    parts.append(_collection(identifier + '-values', rows, 'product values') if rows else
                 _empty('No product values reported. The candidate remains open.'))
    conflicts = []
    for conflict in _entries(result.get('conflicts'), 'product_id'):
        body = '<h4>' + _e(conflict.get('product_id')) + '</h4>'
        competing = conflict.get('competing_values')
        if isinstance(competing, Mapping):
            for value, evidence in competing.items():
                body += '<strong class="value">' + _value(value) + '</strong>' + _proofs(evidence, sources)
        else:
            body += _raw('Competing values', competing)
        conflicts.append('<article class="conflict" data-item>' + body + '</article>')
    parts.append('<details class="review"' + (' open' if conflicts else '') + '><summary>Conflicts · '
                 + (str(len(conflicts)) if 'conflicts' in result else 'unavailable') + '</summary>'
                 + (_collection(identifier + '-conflicts', conflicts, 'conflicts') if conflicts
                    else _empty('No conflicts reported.')) + '</details>')
    parts.append(_product_list('Unknown product values', result.get('unknown_products'), identifier + '-unknown',
                               'No value established. Unknown does not mean the property is absent.'))
    parts.append(_product_list('Unanalyzed or partially analyzed products', result.get('unanalysed_products'),
                               identifier + '-unanalyzed', 'Some assets have not been analyzed. '
                               'These products may also have a reported value or conflict.'))
    parts.append('<details class="scope"><summary>Scope &amp; method · this extraction</summary>'
                 + _stats(zip(('Selected assets', 'Analyzed assets', 'Unanalyzed assets'), counts))
                 + '<p class="muted">' + _e(_semantic_status([result]))
                 + '. Exact quotations establish provenance; they do not establish semantic correctness.</p>'
                 + _routing(result, identifier, sources) + _raw('Original extraction', result) + '</details>')
    return ''.join(parts)


def _extract(snapshot, candidates, extractions):
    upstream = _mapping(_mapping(snapshot.get('benchmark')).get('source_routing'))
    stats, complete, assets, products, totals, inventory = _extract_overview(snapshot, candidates, extractions)
    selection_note = []
    if products is not None:
        selection_note.append(f'{products} distinct selected products')
    if totals[0] is not None:
        selection_note.append(f'{totals[0]} candidate–asset checks')
    if totals[1] is not None:
        selection_note.append(f'{totals[1]} analyzed')
    parts = [_stats(stats), '<p class="count-note">'
        + ('Partial results · ' if not complete else '')
        + _e(' · '.join(selection_note) or 'Selection counts unavailable') + '</p>',
        '<p class="method-note">' + _e(_semantic_status(extractions)) + '</p>',
        '<details class="scope overview-scope"><summary>Scope &amp; method</summary>'
        '<p><strong>Extraction scope: supplied subcorpus.</strong> '
        'These asset counts are not a full-catalog product count.</p>'
        '<p class="muted">Asset counts cover reported extractions, per candidate; the same asset can '
        'appear more than once. Missing extraction results are not counted as zero. '
        'Headline counts cover reported assignments, products with checked quotations, and candidates '
        'with no checked proof in their reported results; conflicts are not proposed assignments.</p>'
        + _fields((('Distinct selected assets', assets), ('Distinct selected products', products),
                   ('Candidate–asset checks', totals[0]), ('Analyzed candidate–asset checks', totals[1]),
                   ('Indexed assets · shared upstream inventory', inventory if inventory is not None else 'Unavailable · inventory not established as shared')))
        + '<p class="muted">Skipped or unsupported assets are unanalyzed, never evidence of absence.</p></details>',
        '<section id="candidates"><div class="section-heading"><div><h2>Candidates &amp; evidence</h2>'
        '<p>Inspect product values, their exact quotations, and what is still unknown.</p></div>'
        + _link(snapshot, 'induct', 'Review in Induct') + '</div>']
    grouped = {}
    for result in extractions:
        grouped.setdefault(_text(result.get('candidate_key')), []).append(result)
    cards = []
    known = {_text(candidate.get('key')) for candidate in candidates}
    # Orphan extraction checkpoints remain visible; no fabricated candidate data.
    entries = [(candidate, grouped.get(_text(candidate.get('key')), [])) for candidate in candidates]
    entries += [(dict(key=key), results) for key, results in grouped.items() if key not in known]
    for index, (candidate, results) in enumerate(entries):
        identifier = f'candidate-{index}'
        label = candidate.get('label') or 'Candidate without a label'
        preview = []
        for result in results:
            for row in _entries(result.get('assignments'), 'product_id'):
                if 'value' in row and _value(row['value']) not in preview:
                    preview.append(_value(row['value']))
        cards.append(f'<details class="candidate" data-item id="{identifier}"' + (' open' if index == 0 else '')
                     + '><summary><span><strong>' + _e(label) + '</strong><small>'
                     + (' · '.join(preview[:3]) if preview else 'No proposed values reported') + '</small></span>'
                     + _badge(results[0].get('status') if len(results) == 1 else
                              ('Multiple extraction results' if results else 'needs_extraction')) + '</summary>'
                     '<div class="candidate-body">')
        if not results:
            cards.append(_empty('Extraction unavailable. This candidate is retained; product values are unknown.'))
        for result_index, result in enumerate(results):
            if len(results) > 1:
                cards.append(f'<h3>Reported extraction {result_index + 1}</h3>')
            cards.append(_extraction(result, f'{identifier}-result-{result_index}'))
        cards.append('<details><summary>Candidate context &amp; demand</summary>'
                     '<p class="muted">Demand explains the candidate; it is not product evidence.</p>'
                     + _fields((('Candidate key', candidate.get('key')), ('Definition', candidate.get('definition')),
                                ('Gap', _label(candidate.get('gap_type'))), ('Demand events', candidate.get('demand_events'))))
                     + _proofs(candidate.get('demand_records'), {}) + _raw('Original candidate', candidate)
                     + '</details><details class="scope"><summary>Scope &amp; method · source selection</summary>'
                     + _upstream_selection(upstream.get(_text(candidate.get('key')))) + '</details></div></details>')
    parts.append(_collection('candidate-list', cards, 'candidates') if entries else
                 _empty('No candidates or extraction results available in this snapshot.'))
    return ''.join(parts) + '</section>'


def _facets(model):
    result = {}
    for entry in _entries(model.get('existing_facets')):
        result.setdefault(_text(entry.get('key')), [])
    for entry in _entries(model.get('facets')):
        result.setdefault(_text(entry.get('key')), []).append(entry)
    return result


def _assignments(model):
    result = {}
    for assignment in _entries(model.get('assignments'), 'product_id'):
        key = (_text(assignment.get('fact_key')), _text(assignment.get('product_id')))
        result.setdefault(key, []).append(assignment)
    return result


def _change(before, after, comparable):
    if not comparable:
        return 'Comparison unavailable'
    if before is None:
        return 'Added'
    if after is None:
        return 'Removed'
    return 'Unchanged' if _json(before) == _json(after) else 'Changed'


def _facet_values(facets):
    if facets is None:
        return {}
    if not facets or any(not isinstance(facet.get('values'), list) for facet in facets):
        return None
    return {_json(value): value for facet in facets for value in facet['values']}


def _value_chips(values):
    chips = [f'<span class="value-chip">{_value(value)}</span>' for value in values]
    body = '<div class="values">' + ''.join(chips[:8]) + '</div>'
    if len(chips) > 8:
        body += (f'<details><summary>{len(chips) - 8} more values</summary><div class="values">'
                 + ''.join(chips[8:]) + '</div></details>')
    return body


def _facet_cell(facets, available, *, other=None, after=False, comparable=True):
    if not available:
        return _empty('Snapshot unavailable.')
    if facets is None:
        return _empty('Not in model.')
    if not facets:
        return _empty('Facet exists; definition and values not supplied.')
    parts = []
    for facet in facets:
        parts.append('<strong>' + _e(facet.get('label', facet.get('key'))) + '</strong>')
        values = facet.get('values')
        if not isinstance(values, list):
            parts.append(_empty('Values not supplied.'))
        else:
            parts.append(f'<p class="muted">{len(values)} values</p>')
    if after:
        old_values, new_values = _facet_values(other), _facet_values(facets)
        if not comparable or old_values is None or new_values is None:
            parts.append(_empty('Value comparison unavailable.'))
        elif other is None:
            parts.append(_value_chips(new_values.values()))
        else:
            added = [value for key, value in new_values.items() if key not in old_values]
            removed = [value for key, value in old_values.items() if key not in new_values]
            for title, values in (('Added values', added), ('Removed values', removed)):
                if values:
                    parts.append('<strong>' + title + '</strong>' + _value_chips(values))
            if not added and not removed:
                parts.append(_empty('No value changes.'))
    for facet in facets:
        parts.append('<details class="raw"><summary>Full facet record</summary><pre>'
                     + _e(_json(facet)) + '</pre></details>')
    return ''.join(parts)


def _assignment_cell(assignments, available, sources):
    if not available:
        return _empty('Snapshot unavailable.')
    if assignments is None:
        return _empty('No assignment in snapshot.')
    return ''.join('<div class="assignment-cell"><strong class="value">'
                   + (_value(item['value']) if 'value' in item else 'Value unavailable') + '</strong>'
                   + _proofs(item.get('evidence'), sources) + _raw('Assignment record', item) + '</div>'
                   for item in assignments)


def _comparison(before, after, available, kind, sources, labels=None):
    comparable = all(available)
    changed, unchanged = [], []
    keys = sorted(before.keys() | after.keys())
    unchanged_count = 0
    for key in keys:
        old, new = before.get(key), after.get(key)
        change = _change(old, new, comparable)
        if change == 'Unchanged':
            unchanged_count += 1
            if len(keys) > 200:
                continue
        if kind == 'facets':
            label = next((facet.get('label') for facet in (new or []) + (old or [])
                          if facet.get('label')), 'Unnamed facet')
            label = ('<strong>' + _e(label) + '</strong><details class="raw"><summary>Facet key</summary>'
                     '<small>' + _e(key) + '</small></details>')
            cells = (_facet_cell(old, available[0]),
                     _facet_cell(new, available[1], other=old, after=True, comparable=comparable))
        else:
            label = ('<strong>Product ' + _e(key[1]) + '</strong><small>'
                     + _e((labels or {}).get(key[0], key[0])) + '</small>')
            cells = (_assignment_cell(old, available[0], sources), _assignment_cell(new, available[1], sources))
        row = '<tr data-item><th scope="row">' + label + '</th><td>' + cells[0] + '</td><td>' + cells[1]
        row += '</td><td>' + _badge(change, 'accent' if change in {'Added', 'Changed'} else 'neutral') + '</td></tr>'
        (unchanged if change == 'Unchanged' else changed).append(row)
    noun = 'facets' if kind == 'facets' else 'product assignments'
    headers = ('Facet' if kind == 'facets' else 'Product / facet', 'Before', 'Proposed after', 'Change')
    body = (_collection(kind + '-changes', changed, noun,
                        table_head=(noun.capitalize() + ' · before and proposed after', headers)) if changed
            else _empty('No changes between the supplied snapshots.' if comparable else 'Comparison unavailable.'))
    if unchanged_count:
        body += f'<details class="unchanged"><summary>Unchanged {noun} · {unchanged_count}</summary>'
        body += (_collection(kind + '-unchanged', unchanged, noun,
                            table_head=('Unchanged ' + noun, headers)) if unchanged else
                 '<p>Unchanged records are kept in the full snapshot. This view focuses on the proposed changes.</p>') + '</details>'
    return body, len(changed) if comparable else None


def _publication(snapshot, projection):
    publication = snapshot.get('publication', projection.get('publication'))
    if isinstance(publication, Mapping):
        status = publication.get('status')
    elif isinstance(publication, str):
        status = publication
    else:
        status = snapshot.get('publication_status', projection.get('publication_status'))
    return ('<section id="publication" class="notice publication"><div><h2>Publication</h2>'
            + _badge(status if status is not None else 'Publication status unavailable', 'warning') + '</div>'
            '<p>This is a proposed model snapshot. This workspace cannot publish or change the model.</p>'
            + ('<p>Completion of a job does not establish publication.</p>' if status is None else '')
            + (_raw('Publication record', publication) if publication is not None else '') + '</section>')


def _induct(snapshot, extractions):
    projection = _mapping(snapshot.get('projection'))
    before = projection.get('base_model', snapshot.get('model'))
    after = projection.get('projected_model')
    available = (isinstance(before, Mapping), isinstance(after, Mapping))
    base, proposed = _mapping(before), _mapping(after)
    labels = {key: next((row.get('label') for row in rows if row.get('label')), key)
              for model in (base, proposed) for key, rows in _facets(model).items()}
    labels.update({row['key']: row.get('label') or row['key']
                   for row in _entries(snapshot.get('candidates'), 'key') if row.get('key')})
    sources = _sources(extractions + _entries(_mapping(projection.get('validation_inputs')).get('extractions'),
                                             'candidate_key'))
    facets, facet_count = _comparison(_facets(base), _facets(proposed), available, 'facets', sources)
    assignments, assignment_count = _comparison(_assignments(base), _assignments(proposed),
                                               available, 'assignments', sources, labels)
    blocked = _entries(projection.get('blocked'), 'candidate_key')
    parts = [_publication(snapshot, projection),
             _stats((('Facet changes', facet_count), ('Assignment changes', assignment_count),
                     ('Blocked entries', len(blocked) if 'blocked' in projection else None)))]
    if not all(available):
        parts.append('<p class="notice warning">Comparison incomplete: a model snapshot is unavailable. '
                     'No additions or removals can be inferred.</p>')
    parts.append('<div class="snapshot-heads">')
    for title, model, exists in (('Before · base model', base, available[0]),
                                 ('After · proposed model', proposed, available[1])):
        parts.append('<div><h3>' + title + '</h3>' + (_fields((('Category', model.get('category')),
                     ('Version', model.get('version')),
                     ('Facets', len(_facets(model)) if any(isinstance(model.get(field), (list, tuple, Mapping))
                                                         for field in ('facets', 'existing_facets')) else None),
                     ('Assignments', len(_entries(model.get('assignments'), 'product_id'))
                      if isinstance(model.get('assignments'), (list, tuple, Mapping)) else None)))
                     if exists else _empty('Snapshot unavailable.')) + '</div>')
    parts.append('</div><section id="facets"><h2>Facets &amp; values</h2>'
                 '<p>Added and removed values; full definitions and records are available in each row.</p>' + facets + '</section>')
    parts.append('<section id="assignments"><h2>Product assignments</h2>'
                 '<p>Product values and evidence before and after the proposal.</p>' + assignments + '</section>')
    rows = []
    for row in blocked:
        rows.append('<article class="blocked" data-item><div class="value-heading"><h3>'
                    + _e(labels.get(row.get('candidate_key'), row.get('candidate_key'))) + '</h3>' + _badge('blocked', 'warning') + '</div>'
                    + ('<p class="value">' + _e(row['product_id']) + '</p>' if 'product_id' in row else '')
                    + '<p>' + _e(_label(row.get('reason'))) + '</p>'
                    + _raw('Blocked proposal details', row) + '</article>')
    parts.append('<section id="blocked"><div class="section-heading"><div><h2>Blocked entries</h2>'
                 '<p>Includes blocked product assignments and fully blocked proposals.</p></div>'
                 + _link(snapshot, 'extract', 'Inspect extraction evidence') + '</div>'
                 + (_collection('blocked-list', rows, 'blocked entries') if rows else
                    _empty('No blocked entries reported.' if 'blocked' in projection else 'Blocked entries unavailable.'))
                 + '</section>')
    # Keep extraction uncertainty available even when a projection has no blocked rows.
    if extractions:
        parts.append('<details class="review"><summary>Extraction unknowns &amp; incomplete analysis</summary>')
        for index, result in enumerate(extractions):
            parts.append('<h3>' + _e(labels.get(result.get('candidate_key'), result.get('candidate_key'))) + '</h3>'
                         + _product_list('Unknown product values', result.get('unknown_products'),
                                         f'induct-unknown-{index}', 'No product value established.')
                         + _product_list('Unanalyzed or partially analyzed products', result.get('unanalysed_products'),
                                         f'induct-unanalyzed-{index}', 'Skipped assets are not evidence of absence.'))
        parts.append('</details>')
    return ''.join(parts)


_CSS = """
:root{color-scheme:light;--ink:#252839;--muted:#626779;--line:#e2e4ec;--accent:#5c49cb;--soft:#f0edff;--canvas:#f7f8fb}
*{box-sizing:border-box}body{margin:0;background:var(--canvas);color:var(--ink);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}button,input{font:inherit}button,summary{cursor:pointer}button:disabled{opacity:.45;cursor:default}
:focus-visible{outline:3px solid #8172de;outline-offset:4px}[hidden]{display:none!important}.skip{position:fixed;top:-80px;left:20px;padding:12px;background:white;z-index:20}.skip:focus{top:12px}
.sidebar{position:fixed;inset:0 auto 0 0;width:236px;background:white;border-right:1px solid var(--line);display:flex;flex-direction:column;padding:30px 22px;gap:30px}
.brand{font-size:25px;letter-spacing:.06em;font-weight:750;display:flex;align-items:center;gap:12px;color:var(--ink)}.brand-mark{border-radius:11px;background:var(--accent);color:white;width:38px;height:38px;text-align:center;line-height:38px;letter-spacing:0}
.product-name{display:block;color:var(--muted);font-size:14px;letter-spacing:0;font-weight:500}.nav-label,.eyebrow{color:var(--muted);font-size:12px;letter-spacing:.12em;font-weight:700}.sidebar nav{display:grid;gap:7px}.sidebar nav a{padding:11px 13px;color:var(--muted);border-radius:8px;font-size:15px}.sidebar nav a:first-child{background:var(--soft);color:var(--accent)}
.related{margin-top:auto;display:grid;gap:16px;border-top:1px solid var(--line);padding-top:24px;font-size:14px}.sidebar-foot{font-size:13px;color:var(--muted)}.app{margin-left:236px}.topbar{padding:18px 40px;background:white;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:16px;font-size:14px}.topbar span{color:var(--muted)}
main{max-width:1540px;margin:auto;padding:42px 44px 60px}h1,h2,h3,h4,h5,p{margin:0 0 12px}h1{font-size:42px;line-height:1.15;font-weight:650;letter-spacing:-.035em;margin-top:10px}h2{font-size:26px;font-weight:630;letter-spacing:-.025em}h3{font-size:21px;font-weight:620}h4,h5{font-size:18px;font-weight:620}p{overflow-wrap:anywhere}.lead{font-size:19px;color:var(--muted);max-width:820px;margin:14px 0 20px}.context{display:flex;flex-wrap:wrap;align-items:center;gap:10px 24px;color:var(--muted);font-size:14px;margin-bottom:30px}.context code{font-size:13px;overflow-wrap:anywhere}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));background:white;border:1px solid var(--line);border-radius:13px;margin:24px 0 12px;overflow:hidden}.stats>div{padding:22px 24px;border-right:1px solid var(--line)}.stats dt{color:var(--muted);font-size:14px}.stats dd{font-size:30px;font-weight:620;margin:4px 0 0;line-height:1.25;overflow-wrap:anywhere}.count-note{font-size:13px;color:var(--muted);margin:14px 0 24px}.notice{padding:18px 22px;border:1px solid #dcd6f5;border-radius:10px;background:#f2effc;margin:22px 0;color:#4d407f}.warning{background:#fff7e9;border-color:#e7d4ac;color:#79551c}.publication>div{display:flex;align-items:center;gap:18px;justify-content:space-between}.publication h2{font-size:20px;margin:0}.publication p{margin:10px 0 0}.publication{background:white}.badge{display:inline-block;font-size:12px;font-weight:600;border-radius:6px;padding:5px 9px;line-height:1.5;background:#eef0f5;color:#555b6e;overflow-wrap:anywhere}.badge.accent{background:var(--soft);color:var(--accent)}.badge.warning{background:#fff2d9;color:#79551c}
section{margin:34px 0}.section-heading{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:20px}.section-heading p,section>p{color:var(--muted)}.section-heading a{font-size:14px;white-space:nowrap}.muted{color:var(--muted);font-size:14px}.empty{color:var(--muted);font-size:15px;padding:12px 0;margin:0}.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px 24px;margin:18px 0}.facts dt{font-size:12px;color:var(--muted)}.facts dd{font-size:15px;margin:3px 0 0;overflow-wrap:anywhere}
.candidate{border:1px solid var(--line);border-radius:12px;background:white;margin-bottom:16px;overflow:hidden}.candidate>summary{padding:24px;display:flex;align-items:center;justify-content:space-between;gap:18px;list-style:none}.candidate>summary::-webkit-details-marker{display:none}.candidate>summary:after{content:'+';color:var(--accent);font-size:24px}.candidate[open]>summary:after{content:'−'}.candidate>summary>span:first-child{flex:1}.candidate>summary strong{font-size:22px;font-weight:620;overflow-wrap:anywhere}.candidate small,th small{display:block;color:var(--muted);font-size:13px;font-weight:400;overflow-wrap:anywhere}.candidate[open]>summary{border-bottom:1px solid var(--line)}.candidate-body{padding:26px}.definition{font-size:18px}.candidate-body .stats{background:var(--canvas)}.candidate-body .stats dd{font-size:26px}
details>summary{padding:13px 0;font-size:14px;font-weight:600;color:#51478a;overflow-wrap:anywhere}details>summary:hover{color:var(--accent)}.review,.routing,.unchanged{border-top:1px solid var(--line);margin-top:20px}.review>summary,.routing>summary,.unchanged>summary{font-size:16px;padding:18px 0}.assignment,.asset,.conflict,.blocked{padding:22px;border:1px solid var(--line);border-radius:10px;margin:12px 0;background:white}.conflict{border-left:3px solid #c19a49}.value-heading{display:flex;justify-content:space-between;gap:24px;align-items:baseline}.value-heading h3,.value-heading h4{margin:0;overflow-wrap:anywhere}.value{font-size:21px;font-weight:600;white-space:pre-wrap;overflow-wrap:anywhere}.value-heading .value{color:var(--accent)}.proof{margin:18px 0 6px;border-left:3px solid #d5cef4;padding-left:18px}.proof blockquote{font-size:18px;line-height:1.6;white-space:pre-wrap;margin:0;overflow-wrap:anywhere}.proof figcaption{font-size:12px;color:var(--muted);margin-top:8px;overflow-wrap:anywhere}.provenance{margin-left:20px}.provenance>summary{font-size:13px}.source{padding:0 18px;background:var(--canvas);border:1px solid var(--line);border-radius:8px;margin:12px 0}.source-text{font:16px/1.7 inherit}pre{font:13px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;max-height:480px;overflow:auto;padding:18px;background:var(--canvas);border:1px solid var(--line);border-radius:8px}pre.source-text{font-family:inherit;font-size:16px}mark{background:#eee59b;color:#26261b}.raw>summary{color:var(--muted);font-size:12px}.product-unknown{padding:10px 16px;border-bottom:1px solid var(--line);font-size:16px;overflow-wrap:anywhere}
.collection-tools{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:14px;padding:16px 0}.collection-tools label{font-size:12px;color:var(--muted);display:grid;gap:6px;max-width:100%}input[type=search]{border:1px solid #cfd2df;border-radius:7px;padding:10px 12px;width:280px;max-width:100%;background:white;color:var(--ink);font-size:15px}.pager{display:flex;align-items:center;gap:12px}.pager button{border:1px solid var(--line);border-radius:7px;background:white;padding:9px 12px;color:var(--ink);font-size:13px}.pager output{font-size:12px;color:var(--muted)}.snapshot-heads{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:28px 0}.snapshot-heads>div{background:white;border:1px solid var(--line);border-radius:10px;padding:22px}.snapshot-heads h3{font-size:18px}.table-scroll{overflow:auto;border:1px solid var(--line);border-radius:10px;background:white}table{border-collapse:collapse;width:100%;table-layout:fixed;min-width:760px}caption{text-align:left;padding:18px 20px;font-size:14px;color:var(--muted);border-bottom:1px solid var(--line)}th,td{text-align:left;padding:20px;vertical-align:top;border-bottom:1px solid var(--line);font-size:16px;overflow-wrap:anywhere}thead th{background:#f6f7fb;font-size:13px;font-weight:600}thead th:first-child{width:19%}thead th:last-child{width:15%}tbody th{font-weight:550}tr:last-child>td,tr:last-child>th{border-bottom:0}td .value{font-size:19px}td .proof blockquote{font-size:16px}td .facts{grid-template-columns:1fr}.assignment-cell+.assignment-cell{border-top:1px solid var(--line);margin-top:16px;padding-top:16px}.values{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}.value-chip{background:var(--soft);color:#4c4086;border-radius:5px;padding:5px 9px;font-size:16px;white-space:pre-wrap;overflow-wrap:anywhere}.footer{margin-top:40px;border-top:1px solid var(--line);padding-top:24px;font-size:13px;color:var(--muted)}
@media(max-width:1050px){.sidebar{width:200px;padding:25px 15px}.app{margin-left:200px}main{padding:30px 24px}.topbar{padding:16px 24px}.section-heading{align-items:flex-start;flex-direction:column}.candidate-body{padding:20px}.stats>div{padding:18px}}
@media(max-width:740px){.sidebar{position:static;width:auto;padding:18px;gap:18px}.sidebar nav{display:flex;flex-wrap:wrap}.sidebar .nav-label,.sidebar-foot{display:none}.related{margin:0;padding:12px 0 0;display:flex;flex-wrap:wrap}.brand{font-size:22px}.app{margin:0}.topbar{padding:12px 18px}main{padding:26px 16px}h1{font-size:34px}.lead{font-size:17px}.stats{grid-template-columns:1fr 1fr}.stats dd{font-size:25px}.candidate>summary{padding:18px;flex-wrap:wrap}.candidate>summary strong{font-size:20px}.candidate-body{padding:16px}.value-heading{display:block}.value-heading .value{display:block;margin-top:8px}.snapshot-heads{grid-template-columns:1fr}.collection-tools,.pager{gap:8px}.assignment,.asset,.blocked,.conflict{padding:16px}.publication>div{align-items:flex-start;flex-direction:column}.provenance{margin-left:0}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}@media print{.sidebar,.topbar,.collection-tools{display:none!important}.app{margin:0}main{padding:0}.table-scroll{overflow:visible}pre{max-height:none}}
.extract main{padding-top:22px}.extract .topbar{padding-top:12px;padding-bottom:12px}.extract h1{font-size:28px;margin:0 0 6px}.extract .eyebrow{display:none}.extract .lead{font-size:16px;margin:0 0 8px}.extract .context{margin-bottom:14px;gap:12px}.extract .stats{margin:12px 0 8px;border-radius:9px}.extract .stats>div{padding:12px 16px}.extract .stats dd{font-size:26px}.extract .stats dt{font-size:12px}.extract .count-note{margin:6px 0;font-size:12px}.method-note{color:var(--muted);font-size:13px;margin:4px 0}.scope{border-top:1px solid var(--line);margin-top:10px}.scope>summary{padding:9px 0;font-size:13px}.extract section{margin:18px 0}.extract .section-heading{margin-bottom:4px}.extract .section-heading h2{font-size:21px;margin-bottom:2px}.extract .section-heading p{font-size:14px;margin-bottom:0}.extract .collection-tools{padding:8px 0;gap:8px}.extract input[type=search]{padding:6px 10px}.extract .pager button{padding:6px 10px}.extract .candidate>summary{padding:13px 18px;gap:12px}.extract .candidate>summary strong{font-size:19px}.extract .candidate small{color:var(--accent);font-size:14px}.extract .candidate-body{padding:14px 18px}.extract .candidate-body h3{font-size:17px;margin:0}.extract .assignment{padding:14px 16px;margin:8px 0}.extract .proof{margin-top:10px}.extract .proof blockquote{font-size:16px}.extract .value-heading h4{font-size:15px}.extract .notice{margin:12px 0;padding:12px 16px}
@media(max-width:740px){.extract .stats{grid-template-columns:1fr 1fr}.extract .stats>div{padding:10px}.extract .stats dd{font-size:22px}.extract main{padding-top:18px}.extract .candidate>summary{padding:12px}.extract .candidate-body{padding:12px}}
"""

_JS = """
(() => {
  'use strict';
  document.querySelectorAll('[data-collection]').forEach(collection => {
    const tools = collection.querySelector(':scope > [data-tools]');
    const container = collection.querySelector(':scope > [data-items], :scope > .table-scroll > table > [data-items]');
    if (!tools || !container) return;
    const rows = Array.from(container.children).filter(row => row.hasAttribute('data-item'));
    const search = tools.querySelector('input');
    const previous = tools.querySelector('[data-prev]');
    const next = tools.querySelector('[data-next]');
    const status = tools.querySelector('output');
    const noMatch = collection.querySelector(':scope > [data-no-match]');
    const size = Number(collection.dataset.pageSize) || 8;
    const text = rows.map(row => row.textContent.toLocaleLowerCase());
    let page = 0;
    function render() {
      const term = search.value.trim().toLocaleLowerCase();
      const matches = rows.filter((row, index) => text[index].includes(term));
      const pages = Math.max(1, Math.ceil(matches.length / size));
      page = Math.min(page, pages - 1);
      rows.forEach(row => { row.hidden = true; });
      matches.slice(page * size, (page + 1) * size).forEach(row => { row.hidden = false; });
      const start = matches.length ? page * size + 1 : 0;
      status.textContent = `${start}–${Math.min((page + 1) * size, matches.length)} of ${matches.length}`;
      previous.disabled = page === 0;
      next.disabled = page >= pages - 1;
      noMatch.hidden = matches.length !== 0;
    }
    search.addEventListener('input', () => { page = 0; render(); });
    previous.addEventListener('click', () => { page = Math.max(0, page - 1); render(); });
    next.addEventListener('click', () => { page += 1; render(); });
    tools.hidden = false;
    render();
  });
})();
"""


def render_workspace(snapshot, product='extract') -> str:
    """Render an English Extract or Induct workspace using only supplied data.

    Accepts the same report/checkpoint shapes as ``render_loop``. Corresponding
    Benchmark, Extract and Induct links use ``snapshot.id``. The caller owns
    routing; this function neither processes a job nor exposes a write action.
    """
    if product not in ('extract', 'induct'):
        raise ValueError("product must be 'extract' or 'induct'")
    snapshot = _mapping(snapshot)
    projection = _mapping(snapshot.get('projection'))
    model = _mapping(snapshot.get('model', projection.get('base_model')))
    candidates = _entries(snapshot.get('candidates', _mapping(snapshot.get('benchmark')).get('candidates')))
    extractions = _entries(snapshot.get('extractions'), 'candidate_key')
    title = 'Extract' if product == 'extract' else 'Induct'
    description = ('Product values, with the evidence behind each one.' if product == 'extract' else
                   'Review proposed facets, values, and product assignments before publication.')
    navigation = [('candidates', 'Candidates & evidence')] if product == 'extract' else [
        ('publication', 'Publication'), ('facets', 'Facets & values'),
        ('assignments', 'Product assignments'), ('blocked', 'Blocked entries')]
    navigation.append(('snapshot', 'Snapshot details'))
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width, initial-scale=1">'
             '<meta name="color-scheme" content="light"><title>PILON ' + title + '</title><style>'
             + _CSS + '</style></head><body class="' + product + '"><a class="skip" href="#main">Skip to content</a>'
             '<aside class="sidebar" aria-label="Workspace navigation"><a class="brand" href="#main">'
             '<span class="brand-mark" aria-hidden="true">p</span><span>PILON<span class="product-name">'
             + title + '</span></span></a><span class="nav-label">WORKSPACE</span><nav>']
    parts.extend(f'<a href="#{identifier}">{_e(label)}</a>' for identifier, label in navigation)
    parts.append('</nav><div class="related"><a href="/start">Get started</a><a href="/connectors">Models &amp; connectors</a><span class="nav-label">RELATED WORKSPACES</span>'
                 + _link(snapshot, 'benchmark', 'Benchmark')
                 + _link(snapshot, 'induct' if product == 'extract' else 'extract',
                         'Induct' if product == 'extract' else 'Extract')
                 + '</div><div class="sidebar-foot">Local snapshot · read only</div></aside>'
                 '<div class="app"><header class="topbar"><span>' + title + ' / Workspace</span>'
                 '<span>Read only</span></header><main id="main" tabindex="-1">'
                 '<div class="eyebrow">PRODUCT KNOWLEDGE</div><h1>' + title + '</h1>'
                 '<p class="lead">' + description + '</p><div class="context"><span>'
                 + _e(model.get('category', 'Category not reported')) + '</span>'
                 + ('<span>Job: <code>' + _e(snapshot.get('id')) + '</code></span>' if product == 'induct' else '')
                 + '<span>Run: '
                 + _badge(snapshot.get('status')) + '</span>'
                 + (_badge('Synthetic data', 'warning') if snapshot.get('synthetic') is True else '') + '</div>')
    if snapshot.get('error') or snapshot.get('status') in ('failed', 'partial', 'cancelled'):
        parts.append('<div class="notice warning"><strong>Results may be incomplete.</strong> '
                     'Available results remain visible.'
                     + ('<p>' + _e(snapshot['error']) + '</p>' if snapshot.get('error') else '') + '</div>')
    parts.append(_extract(snapshot, candidates, extractions) if product == 'extract' else _induct(snapshot, extractions))
    parts.append('<section id="snapshot"><h2>Snapshot details</h2><p class="muted">'
                 'Frozen report; reload the page to see a newer snapshot.</p>'
                 + '<p>' + _link(snapshot, 'api/jobs', 'Open complete JSON snapshot') + '</p>'
                 + _raw('Original snapshot · all reported fields', snapshot) + '</section>'
                 '<footer class="footer">Read-only review. No extraction, inference, or publication is triggered here.'
                 '</footer></main></div><script>' + _JS + '</script></body></html>')
    return ''.join(parts)
