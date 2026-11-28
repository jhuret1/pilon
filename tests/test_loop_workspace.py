"""Read-only product workspaces, including the actual extraction/projection contract."""

from copy import deepcopy
from html import escape
from html.parser import HTMLParser
import json
import re

import pytest

from pilon.loop.extraction import extract
from pilon.loop.projection import build_projection
from pilon.loop.workspace import render_workspace


class Page(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.tags, self.tables, self.scripts, self.pre = [], [], [], []
        self.table = self.row = self.cell = self.script = self.pre_text = None
        self.in_caption = False
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == 'table':
            self.table = dict(caption='', rows=[])
        elif tag == 'caption':
            self.in_caption = True
        elif tag == 'tr':
            self.row = []
        elif tag in ('td', 'th'):
            self.cell = ''
        elif tag == 'script':
            self.script = ''
        elif tag == 'pre':
            self.pre_text = ''

    def handle_data(self, data):
        if self.in_caption:
            self.table['caption'] += data
        if self.cell is not None:
            self.cell += data
        if self.script is not None:
            self.script += data
        if self.pre_text is not None:
            self.pre_text += data

    def handle_endtag(self, tag):
        if tag == 'table':
            self.tables.append(self.table)
            self.table = None
        elif tag == 'caption':
            self.in_caption = False
        elif tag in ('td', 'th') and self.row is not None:
            self.row.append(self.cell)
            self.cell = None
        elif tag == 'tr' and self.table is not None:
            self.table['rows'].append(self.row)
            self.row = None
        elif tag == 'script':
            self.scripts.append(self.script)
            self.script = None
        elif tag == 'pre':
            self.pre.append(self.pre_text)
            self.pre_text = None

    def rows(self, prefix):
        return [row for table in self.tables if table['caption'].startswith(prefix)
                for row in table['rows'][1:]]


@pytest.fixture
def snapshot():
    model = dict(category='Hardware', version='catalog-1', existing_facets=['material'],
                 facets=[dict(key='material', label='Material', definition='Primary material', values=['Aluminium'])],
                 assignments=[dict(fact_key='material', product_id='Legacy', value='Aluminium', evidence=[])])
    candidates = [dict(key='material', label='Material', definition='The supplied material',
                       gap_type='coverage_gap', status='needs_extraction', demand_events=5,
                       demand_records=[dict(record_id='query-1', source='Search', quote='brass door hardware')]),
                  dict(key='waterproof', label='Waterproof', gap_type='schema_gap', demand_events=2)]

    def source(identifier, product, text, **extra):
        return dict(id=identifier, product_id=product, text=text, role='catalog',
                    category='Hardware', source='Supplier sheet', **extra)

    records = [source('r1', 'Handle 01', 'Édition été.\nMaterial: Brass\nFull supplier notes: keep the protective film.'),
               source('r2', 'Handle 02', 'Material: Steel'),
               source('r3', 'Handle 02', 'Material: Plastic'),
               source('r4', 'Handle 03', 'Material information unavailable'),
               source('r5', 'Handle 04', 'Material: Copper'),
               source('r6', 'Handle 01', 'Material: Brass', asset_type='image'),
               source('r7', 'Handle 05', 'Installation instructions only')]
    extraction = extract(candidates[0], records, model, top_k=4)
    return dict(schema_version=1, id='job-hardware', status='completed', model=model,
                candidates=candidates, extractions=[extraction],
                projection=build_projection(model, candidates, [extraction]),
                publication=dict(status='not_published'), synthetic=False, metrics={}, events=[])


def main_content(markup):
    return markup.split('<main ', 1)[1].split('<section id="snapshot">', 1)[0]


def test_extract_uses_engine_values_proofs_counts_and_full_source(snapshot):
    result = snapshot['extractions'][0]
    assert result['metrics']['retrieval']['selected_assets'] == 4
    assert result['metrics']['extraction']['analyzed_assets'] == 4
    markup = render_workspace(snapshot)
    main = main_content(markup)
    assert '<title>PILON Extract</title>' in markup
    assert '<dt>Candidates</dt><dd>2</dd>' in main
    assert '<dt>Selected assets</dt><dd>4</dd>' in main
    assert '<dt>Analyzed assets</dt><dd>4</dd>' in main
    assert '<dt>Unanalyzed assets</dt><dd>3</dd>' in main
    assert 'Handle 01' in main and '<strong class="value">Brass</strong>' in main
    assert '<blockquote>Material: Brass</blockquote>' in main
    assert 'Édition été.\n<mark>Material: Brass</mark>\nFull supplier notes:' in main
    assert 'keep the protective film.' in main and 'Full source · r1' in main
    assert 'Exact source verified (reported)' in main and 'Labeled specifications' in main
    assert 'Semantic validation: Not performed' in main
    assert 'Semantic correctness verified' not in main
    assert 'Waterproof' in main and 'Extraction unavailable. This candidate is retained' in main
    assert 'the same asset can appear more than once' in main


def test_unknown_conflict_and_partial_analysis_are_distinct(snapshot):
    main = main_content(render_workspace(snapshot))
    assert 'Skipped or unsupported assets are unanalyzed, never evidence of absence.' in main
    assert 'Unknown does not mean the property is absent.' in main
    assert 'Unknown product values · 4' in main  # Includes the inventory-only Legacy product.
    assert 'Unanalyzed or partially analyzed products · 4' in main
    assert 'Conflicts · 1' in main
    for value in ('Handle 02', 'Material: Steel', 'Material: Plastic', 'Handle 03', 'Handle 04', 'Handle 05'):
        assert value in main
    assert 'Selection budget reached' in main and 'Explicit extractor required' in main
    assert 'No lexical match' in main and 'Unanalyzed' in main
    assert '<strong class="value">Copper</strong>' not in main
    assert 'These products may also have a reported value or conflict.' in main


def test_actual_model_snapshots_override_change_summaries(snapshot):
    snapshot['projection']['schema_changes'] = []
    snapshot['projection']['assignment_changes'] = []
    markup = render_workspace(snapshot, 'induct')
    main = main_content(markup)
    page = Page(markup)
    facet, = page.rows('Facets ·')
    assert facet[0].startswith('MaterialFacet key') and facet[0].endswith('material')
    assert 'Aluminium' in facet[1] and 'Brass' not in facet[1]
    assert 'Aluminium' in facet[2] and 'Brass' in facet[2]
    assert facet[3] == 'Changed'
    assignment, = page.rows('Product assignments ·')
    assert 'Handle 01' in assignment[0] and 'Material' in assignment[0]
    assert 'No assignment in snapshot.' in assignment[1]
    assert 'Brass' in assignment[2] and 'Material: Brass' in assignment[2]
    assert assignment[3] == 'Added'
    assert 'Unchanged product assignments · 1' in main
    assert 'Not published' in main and 'Blocked entries' in main
    assert 'Conflicting values' in main and 'Product value unknown' in main
    assert 'Awaiting extraction' in main
    assert 'Handle 02' in main and 'Handle 03' in main and 'Handle 04' in main
    links = {attrs.get('href') for tag, attrs in page.tags if tag == 'a'}
    assert {'/jobs/job-hardware', '/extract/job-hardware'} <= links


@pytest.mark.parametrize('missing', ['before', 'after'])
def test_missing_snapshot_is_not_an_empty_model(snapshot, missing):
    if missing == 'before':
        snapshot.pop('model')
        snapshot['projection'].pop('base_model')
    else:
        snapshot['projection'].pop('projected_model')
    markup = render_workspace(snapshot, 'induct')
    assert 'Comparison incomplete' in markup
    rows = Page(markup).rows('Facets ·') + Page(markup).rows('Product assignments ·')
    assert rows and all(row[3] == 'Comparison unavailable' for row in rows)
    assert all('Snapshot unavailable.' in row[1 if missing == 'before' else 2] for row in rows)
    assert '<dt>Facet changes</dt><dd>Unavailable</dd>' in markup


def test_explicit_empty_model_is_a_real_removal_and_projection_base_wins(snapshot):
    snapshot['model'] = dict(existing_facets=['wrong-base'])
    snapshot['projection']['projected_model'] = {}
    markup = render_workspace(snapshot, 'induct')
    rows = Page(markup).rows('Facets ·')
    assert rows[0][0].startswith('MaterialFacet key') and rows[0][3] == 'Removed'
    assert all('wrong-base' not in cell for row in rows for cell in row)
    assignments = Page(markup).rows('Product assignments ·')
    assert assignments[0][3] == 'Removed'


def test_values_preserve_types_negation_and_all_evidence(snapshot):
    before = dict(facets=[dict(key='flag', values=[False])],
                  assignments=[dict(fact_key='flag', product_id='A', value=False,
                                    evidence=[dict(quote='original proof')])])
    after = dict(facets=[dict(key='flag', values=[0, 'not supported', None])],
                 assignments=[dict(fact_key='flag', product_id='A', value=0,
                                   evidence=[dict(quote='changed proof')]),
                              dict(fact_key='flag', product_id='A', value='not supported',
                                   evidence=[dict(quote='second exact proof')])])
    snapshot['projection'].update(base_model=before, projected_model=after)
    markup = render_workspace(snapshot, 'induct')
    facet, = Page(markup).rows('Facets ·')
    assert 'false' in facet[1] and '0' in facet[2] and 'null' in facet[2]
    assert facet[3] == 'Changed'  # Python's False == 0 must not hide a real change.
    assignment, = Page(markup).rows('Product assignments ·')
    assert 'original proof' in assignment[1]
    assert 'changed proof' in assignment[2] and 'second exact proof' in assignment[2]
    assert 'not supported' in assignment[2] and assignment[3] == 'Changed'
    # A pure evidence change is also material.
    snapshot['projection']['projected_model'] = deepcopy(before)
    snapshot['projection']['projected_model']['assignments'][0]['evidence'] = [dict(quote='new provenance')]
    row, = Page(render_workspace(snapshot, 'induct')).rows('Product assignments ·')
    assert row[3] == 'Changed' and 'new provenance' in row[2]


@pytest.mark.parametrize('value,expected', [(False, 'false'), (0, '0'), ('not supported', 'not supported')])
def test_extract_preserves_explicit_negative_and_zero_values(snapshot, value, expected):
    snapshot['extractions'][0]['assignments'][0]['value'] = value
    main = main_content(render_workspace(snapshot))
    assert f'<strong class="value">{expected}</strong>' in main


def test_source_highlight_requires_the_actual_quoted_span(snapshot):
    snapshot['extractions'][0]['assignments'][0]['evidence'][0]['start'] = 0
    main = main_content(render_workspace(snapshot))
    assert '<blockquote>Material: Brass</blockquote>' in main
    assert 'Full supplier notes:' in main
    assert '<mark>' not in main.split('Product values', 1)[1].split('Conflicts ·', 1)[0]


@pytest.mark.parametrize('product', ['extract', 'induct'])
@pytest.mark.parametrize('snapshot', [None, {}, [], dict(model=None, candidates=None, extractions=None,
                                                       projection=None, metrics=None, events=None)])
def test_empty_reports_have_honest_accessible_states(snapshot, product):
    markup = render_workspace(snapshot, product)
    page = Page(markup)
    assert markup.startswith('<!doctype html><html lang="en">')
    ids = [attrs['id'] for _, attrs in page.tags if 'id' in attrs]
    assert len(ids) == len(set(ids))
    assert {'main', 'snapshot'} <= set(ids)
    assert ':focus-visible' in markup and '@media(max-width:740px)' in markup
    assert 'Synthetic data' not in main_content(markup)
    if product == 'extract':
        assert 'No candidates or extraction results available' in markup
        assert '<dt>Proposed assignments</dt><dd>Unavailable</dd>' in markup
    else:
        assert 'Publication status unavailable' in markup
        assert 'Comparison incomplete' in markup


def test_partial_and_keyed_checkpoints_never_invent_zero_or_discard_results(snapshot):
    candidate = snapshot['candidates'][0]
    extraction = snapshot['extractions'][0]
    snapshot['benchmark'] = dict(candidates={candidate['key']: {k: v for k, v in candidate.items() if k != 'key'}})
    snapshot.pop('candidates')
    extraction.pop('candidate_key')
    extraction.pop('metrics')
    extraction.pop('routing')
    snapshot['extractions'] = dict(material=extraction)
    snapshot.update(status='failed', error='Adapter interrupted')
    main = main_content(render_workspace(snapshot))
    assert 'Material' in main and 'Material: Brass' in main
    assert 'Full supplier notes:' in main  # Source survives even without routing.
    assert 'Adapter interrupted' in main and 'Available results remain visible.' in main
    for label in ('Selected assets', 'Analyzed assets', 'Unanalyzed assets'):
        assert f'<dt>{label}</dt><dd>Unavailable</dd>' in main


def test_metrics_fall_back_to_reported_routing_without_treating_selected_as_analyzed(snapshot):
    result = snapshot['extractions'][0]
    result.pop('metrics')
    main = main_content(render_workspace(snapshot))
    assert '<dt>Selected assets</dt><dd>4</dd>' in main
    assert '<dt>Analyzed assets</dt><dd>4</dd>' in main
    assert '<dt>Unanalyzed assets</dt><dd>3</dd>' in main
    result['routing']['selected'][0].pop('analysis_status')
    main = main_content(render_workspace(snapshot))
    assert '<dt>Selected assets</dt><dd>4</dd>' in main
    assert '<dt>Analyzed assets</dt><dd>Unavailable</dd>' in main
    assert '<dt>Unanalyzed assets</dt><dd>Unavailable</dd>' in main


def test_multiple_and_orphan_extractions_are_not_silently_overwritten(snapshot):
    second = deepcopy(snapshot['extractions'][0])
    second['assignments'][0]['value'] = 'Distinct second value'
    snapshot['extractions'].append(second)
    snapshot['extractions'].append(dict(candidate_key='orphan', assignments=[dict(product_id='Other', value='actual orphan')]))
    markup = render_workspace(snapshot)
    main = main_content(markup)
    assert 'Multiple extraction results' in main
    assert 'Distinct second value' in main and 'actual orphan' in main and 'orphan' in main
    ids = [attrs['id'] for _, attrs in Page(markup).tags if 'id' in attrs]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize('publication,expected', [
    (None, 'Publication status unavailable'),
    (dict(status='not_published'), 'Not published'),
    (dict(status='published'), 'Published'),
    ('rolled_back', 'Rolled back'),
])
def test_publication_requires_explicit_state(publication, expected):
    markup = render_workspace(dict(status='completed', publication=publication), 'induct')
    panel = markup.split('<section id="publication"', 1)[1].split('</section>', 1)[0]
    assert expected in panel
    assert 'Completed' not in panel
    assert 'This workspace cannot publish or change the model.' in panel


@pytest.mark.parametrize('product', ['extract', 'induct'])
def test_every_snapshot_field_is_escaped_and_renderer_has_no_write_actions(snapshot, product):
    attack = '\"><script>alert(1)</script><img src=x onerror=alert(2)><svg onload=alert(3)>&\'\u2028'

    def poison(value):
        if isinstance(value, dict):
            return {key: poison(item) for key, item in value.items()}
        if isinstance(value, list):
            return [poison(item) for item in value]
        return attack if isinstance(value, str) else value

    snapshot = poison(snapshot)
    snapshot.update(error=attack, future_field={attack: attack})
    original = deepcopy(snapshot)
    markup = render_workspace(snapshot, product)
    page = Page(markup)
    assert snapshot == original
    assert render_workspace(snapshot, product) == markup
    assert escape(attack, quote=True) in markup and attack not in markup
    assert len(page.scripts) == 1 and attack not in page.scripts[0]
    assert page.scripts == Page(render_workspace({}, product)).scripts
    assert not any(tag in {'img', 'svg', 'iframe', 'object', 'embed', 'link', 'form'} for tag, _ in page.tags)
    for tag, attrs in page.tags:
        assert not any(name.startswith('on') for name in attrs)
        assert 'src' not in attrs and 'action' not in attrs and 'formaction' not in attrs
        if tag == 'button':
            assert attrs['type'] == 'button'
            assert 'data-prev' in attrs or 'data-next' in attrs
        if 'href' in attrs:
            assert attrs['href'] in {'/start', '/connectors'} or attrs['href'].startswith(('#', '/jobs/', '/extract/', '/induct/', '/api/jobs/'))
            assert '<' not in attrs['href'] and '"' not in attrs['href']
    for forbidden in ('fetch(', 'XMLHttpRequest', 'sendBeacon', 'WebSocket', 'localStorage', 'innerHTML'):
        assert forbidden not in page.scripts[0]
    original_json=json.dumps(original,ensure_ascii=False,indent=2,sort_keys=True,default=str)
    if len(original_json)>24000:
        assert page.pre[-1].startswith(original_json[:24000])
        assert 'Preview truncated' in page.pre[-1]
    else:
        assert json.loads(page.pre[-1]) == original


@pytest.mark.parametrize('identifier', ['.', '..', '', None])
def test_missing_or_dot_job_ids_never_become_navigation_paths(identifier):
    page = Page(render_workspace(dict(id=identifier)))
    assert all(attrs['href'] in {'/start', '/connectors'} or attrs['href'].startswith('#')
               for tag, attrs in page.tags if tag == 'a')


def test_job_paths_are_encoded_and_values_are_never_remote_resources(snapshot):
    snapshot['id'] = 'job/2?x#y'
    markup = render_workspace(snapshot)
    assert 'href="/induct/job%2F2%3Fx%23y"' in markup
    assert 'href="/jobs/job%2F2%3Fx%23y"' in markup


@pytest.mark.parametrize('product', ['extract', 'induct'])
def test_enrichment_links_back_to_the_parent_benchmark(snapshot, product):
    snapshot['benchmark'] = dict(parent_job='benchmark/parent?source=1')
    page = Page(render_workspace(snapshot, product))
    links = {attrs['href'] for tag, attrs in page.tags if tag == 'a'}
    assert '/jobs/benchmark%2Fparent%3Fsource%3D1' in links
    assert '/jobs/job-hardware' not in links
    assert ('/induct/job-hardware' if product == 'extract' else '/extract/job-hardware') in links


def test_upstream_inventory_is_distinct_from_extraction_subcorpus(snapshot):
    snapshot['benchmark'] = dict(parent_job='original-benchmark', source_routing=dict(material=dict(
        method='sqlite_fts5_bm25', indexed_assets=124428, matching_assets=137, selected_assets=20,
        unassessed_outside_shortlist=124408, selection_recall='not_measured',
        phrases=['material', '<untrusted phrase>'], source_sha256='source-fingerprint')))
    main = main_content(render_workspace(snapshot))
    assert 'Extraction scope: supplied subcorpus.' in main
    assert 'These asset counts are not a full-catalog product count.' in main
    assert '<dt>Indexed assets · upstream</dt><dd>124428</dd>' in main
    assert '<dt>Matching assets · upstream</dt><dd>137</dd>' in main
    assert '<dt>Shortlisted assets · upstream</dt><dd>20</dd>' in main
    assert '<dt>Unassessed outside shortlist</dt><dd>124408</dd>' in main
    assert '<dt>Selected assets</dt><dd>4</dd>' in main
    assert '<dt>Selection recall</dt><dd>Not measured</dd>' in main
    assert 'Assets outside the shortlist are unassessed, never evidence of absence.' in main
    assert 'Full-text search (FTS5 / BM25)' in main and 'source-fingerprint' in main
    assert '&lt;untrusted phrase&gt;' in main and '<untrusted phrase>' not in main
    # Another candidate has no upstream record; it must not inherit this inventory.
    assert 'Upstream source selection unavailable. Full-catalog coverage is unknown.' in main


def test_large_snapshots_keep_all_values_in_progressive_detail(snapshot):
    snapshot['projection']['projected_model']['facets'][0]['values'] = [f'exact value {i}' for i in range(1000)]
    markup = render_workspace(snapshot, 'induct')
    main = main_content(markup)
    assert '992 more values' in main and 'exact value 999' in main
    assert 'data-page-size="8"' in main and 'type="search"' in main
    ids = [attrs['id'] for _, attrs in Page(markup).tags if 'id' in attrs]
    assert len(ids) == len(set(ids))


def test_worker_report_renders_without_changing_queue_or_publication(tmp_path):
    from pilon.loop.store import Queue
    from pilon.loop.worker import report, run_once

    queue = Queue(tmp_path / 'jobs.sqlite')
    model = dict(category='Hardware', existing_facets=[], window_start='2026-11-01', window_end='2026-11-30')
    records = [dict(id='catalog-1', role='catalog', category='Hardware', product_id='Door 1',
                    source='Supplier', text='Material: Brass'),
               dict(id='demand-1', role='demand', category='Hardware', date='2026-11-01',
                    source='Search', text='Material: Brass')]
    job_id = queue.enqueue(model, records)
    run_once(queue, job_id=job_id)
    snapshot = report(queue, job_id)
    assert snapshot['status'] == 'completed'
    assert snapshot['extractions'][0]['assignments'][0]['value'] == 'Brass'
    original = deepcopy(snapshot)
    saved = queue.get(job_id)
    for product in ('extract', 'induct'):
        markup = render_workspace(snapshot, product)
        assert f'<title>PILON {product.capitalize()}</title>' in markup
        assert json.loads(Page(markup).pre[-1]) == original
    assert queue.get(job_id) == saved and snapshot == original
    assert snapshot['publication']['status'] == 'not_published'


def test_invalid_product_fails_explicitly():
    with pytest.raises(ValueError, match="product must be"):
        render_workspace({}, 'benchmark')
def test_large_unchanged_catalog_is_not_duplicated_into_the_dom():
    from pilon.loop.workspace import render_workspace
    facets=[dict(key=f'field_{i}',label=f'Field {i}',values=['value '*40]*10) for i in range(1000)]
    model=dict(category='Large catalog',facets=facets,assignments=[])
    html=render_workspace(dict(id='large',model=model,projection=dict(base_model=model,projected_model=model,
        schema_changes=[],assignment_changes=[],blocked=[])),product='induct')
    assert 'Unchanged facets · 1000' in html
    assert 'Open complete JSON snapshot' in html
    assert len(html)<100000


def test_extract_overview_distinguishes_proposals_products_and_repeated_checks(snapshot):
    first = snapshot['extractions'][0]
    first['routing']['selected'] = [dict(record_id='r1', product_id='Handle 01', analysis_status='analyzed')]
    first['metrics']['retrieval']['selected_assets'] = 1
    first['metrics']['extraction']['analyzed_assets'] = 1
    second = deepcopy(first)
    second['candidate_key'] = 'waterproof'
    second['routing']['selected'].append(dict(record_id='r2', product_id='Handle 02', analysis_status='analyzed'))
    second['metrics']['retrieval']['selected_assets'] = 2
    second['metrics']['extraction']['analyzed_assets'] = 2
    snapshot['extractions'].append(second)
    main = main_content(render_workspace(snapshot))
    assert '<dt>Proposed assignments</dt><dd>2</dd>' in main
    assert '<dt>Distinct supported products</dt><dd>1</dd>' in main
    assert '<dt>Proposals without proof</dt><dd>0</dd>' in main
    assert '2 distinct selected products · 3 candidate–asset checks · 3 analyzed' in main
    assert '<dt>Distinct selected assets</dt><dd>2</dd>' in main
    assert '<details class="scope overview-scope"><summary>Scope &amp; method</summary>' in main


def test_partial_extraction_totals_are_reported_not_complete_and_missing_is_not_zero(snapshot):
    main = main_content(render_workspace(snapshot))
    assert 'Partial results ·' in main
    assert '<dt>Proposed assignments</dt><dd>1 reported</dd>' in main
    assert '<dt>Distinct supported products</dt><dd>1 reported</dd>' in main
    assert '<dt>Proposals without proof</dt><dd>Unavailable</dd>' in main
    snapshot['extractions'][0].pop('assignments')
    main = main_content(render_workspace(snapshot))
    assert '<dt>Proposed assignments</dt><dd>Unavailable</dd>' in main
    assert '<dt>Distinct supported products</dt><dd>Unavailable</dd>' in main
    empty = main_content(render_workspace({}))
    assert '<dt>Candidates</dt><dd>Unavailable</dd>' in empty
    assert '<dt>Proposals without proof</dt><dd>Unavailable</dd>' in empty


def test_no_proof_is_counted_only_from_reported_candidate_results(snapshot):
    second = deepcopy(snapshot['extractions'][0])
    second.update(candidate_key='waterproof', assignments=[], conflicts=[], status='needs_extraction')
    snapshot['extractions'].append(second)
    main = main_content(render_workspace(snapshot))
    assert '<dt>Proposals without proof</dt><dd>1</dd>' in main
    snapshot['status'] = 'running'
    assert '<dt>Proposals without proof</dt><dd>1 reported</dd>' in render_workspace(snapshot)


@pytest.mark.parametrize('mismatch', ['count', 'fingerprint', 'missing', None])
def test_shared_inventory_requires_consistent_counts_and_source_identity(snapshot, mismatch):
    selection = dict(indexed_assets=124428, selected_assets=20, source_sha256='same-source')
    other = deepcopy(selection)
    if mismatch == 'count':
        other['indexed_assets'] = 100000
    elif mismatch == 'fingerprint':
        other['source_sha256'] = 'different-source'
    elif mismatch == 'missing':
        other = {}
    snapshot['benchmark'] = dict(source_routing=dict(material=selection, waterproof=other))
    scope = render_workspace(snapshot).split('<details class="scope overview-scope">', 1)[1].split('</details>', 1)[0]
    assert ('<dt>Indexed assets · shared upstream inventory</dt><dd>124428</dd>' in scope) == (mismatch is None)
    if mismatch:
        assert 'Unavailable · inventory not established as shared' in scope


def test_supplied_annotations_are_named_without_claiming_semantic_validation(snapshot):
    result = snapshot['extractions'][0]
    result['conflicts'] = []
    proof = result['assignments'][0]['evidence'][0]
    proof['extraction_method'] = 'supplied_annotation'
    main = main_content(render_workspace(snapshot))
    assert 'Supplied annotations · exact quotes checked; not independently audited' in main
    assert 'Semantic validation: Not performed' not in main
    proof['quote'] = 'a quotation absent from the source'
    main = main_content(render_workspace(snapshot))
    assert 'Supplied annotations · quote checks incomplete; not independently audited' in main
    assert '<dt>Distinct supported products</dt><dd>0 reported</dd>' in main
    assert 'Supplied annotations · exact quotes checked' not in main


def test_candidate_values_precede_scope_and_hashes_stay_in_disclosures(snapshot):
    key = 'candidate_' + 'a' * 64
    snapshot['candidates'][0]['key'] = key
    snapshot['extractions'][0]['candidate_key'] = key
    markup = render_workspace(snapshot)
    hero = markup.split('<main ', 1)[1].split('<dl class="stats">', 1)[0]
    assert 'job-hardware' not in hero
    card = markup.split('id="candidate-0"', 1)[1]
    summary = card.split('</summary>', 1)[0]
    assert 'Material' in summary and 'Brass' in summary and key not in summary
    assert card.index('<strong class="value">Brass</strong>') < card.index('Scope &amp; method · this extraction')
    assert card.index('<strong class="value">Brass</strong>') < card.index('Upstream source selection')
    assert '<dt>Candidate key</dt><dd>' + key + '</dd>' in card
    assert 'Original extraction' in card


def test_incomplete_routing_never_invents_distinct_product_counts(snapshot):
    snapshot['extractions'][0]['routing'].pop('selected')
    markup = render_workspace(snapshot)
    scope = markup.split('<details class="scope overview-scope">', 1)[1].split('</details>', 1)[0]
    assert '<dt>Distinct selected products</dt><dd>Not reported</dd>' in scope
    assert '<dt>Distinct selected assets</dt><dd>Not reported</dd>' in scope


def test_induct_compares_large_domains_without_repeating_existing_values(snapshot):
    key = 'attribute_' + 'a' * 64
    values = ['ants,beetles,flies,' * 30 + str(i) for i in range(179)]
    before = dict(facets=[dict(key=key, label='Pest Type', values=values,
                              definition='Long supplier definition')], assignments=[])
    after = deepcopy(before)
    after['facets'][0]['values'].append('Gnats')
    after['facets'].append(dict(key='pest_control_action', label='Pest control action',
                                values=['kill', 'repel', 'trap'], definition='Long action definition'))
    after['assignments'] = [dict(product_id='P1', fact_key=key, value='Gnats')]
    snapshot['projection'].update(base_model=before, projected_model=after,
                                  blocked=[dict(candidate_key=key, product_id='P2')])
    markup = render_workspace(snapshot, 'induct')
    table = markup.split('<tbody data-items>', 1)[1].split('</tbody>', 1)[0]
    visible = re.sub(r'<details\b.*?</details>', '', table, flags=re.S)
    assert 'Pest Type' in visible and key not in visible
    assert '179 values' in visible and '180 values' in visible
    assert 'Added values' in visible and '<span class="value-chip">Gnats</span>' in visible
    assert values[0] not in visible and 'Long supplier definition' not in visible
    assert 'Not in model.' in visible and 'Pest control action' in visible
    assert all(f'<span class="value-chip">{value}</span>' in visible for value in ('kill', 'repel', 'trap'))
    assert 'Long action definition' not in visible
    assert values[-1] in table and 'Long action definition' in table and key in table
    assert '<dt>Facets</dt><dd>1</dd>' in markup and '<dt>Facets</dt><dd>2</dd>' in markup
    assert '<dt>Assignments</dt><dd>0</dd>' in markup and '<dt>Assignments</dt><dd>1</dd>' in markup
    assert '<dt>Blocked entries</dt><dd>1</dd>' in markup


@pytest.mark.parametrize('old,new', [(False, 0), (True, 1), (1, '1'), (1, 1.0),
                                    (None, 'null'), ({'a': 1}, {'a': '1'})])
def test_induct_value_deltas_keep_json_types_distinct(snapshot, old, new):
    snapshot['projection'].update(
        base_model=dict(facets=[dict(key='typed', label='Typed', values=[old])]),
        projected_model=dict(facets=[dict(key='typed', label='Typed', values=[new])]))
    markup = render_workspace(snapshot, 'induct')
    table = markup.split('<tbody data-items>', 1)[1].split('</tbody>', 1)[0]
    visible = re.sub(r'<details\b.*?</details>', '', table, flags=re.S)
    assert 'Added values' in visible and 'Removed values' in visible
    assert 'No value changes.' not in visible


def test_induct_missing_domains_and_inventory_are_not_invented(snapshot):
    snapshot['projection'].update(base_model=dict(facets=[dict(key='pest', label='Pest')]),
        projected_model=dict(facets=[dict(key='pest', label='Pest', values=['Gnats'])]))
    markup = render_workspace(snapshot, 'induct')
    assert 'Value comparison unavailable.' in markup
    assert 'Added values' not in markup
    assert '<dt>Assignments</dt><dd>Not reported</dd>' in markup
