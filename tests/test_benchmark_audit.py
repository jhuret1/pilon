"""Optional audit contracts, using a local JS runtime without browser automation."""

from copy import deepcopy
import csv
from html.parser import HTMLParser
import io
import json
import shutil
import subprocess

import pytest

from pilon.loop.benchmark_ui import build_view, render_benchmark


class Markup(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.tags, self.scripts, self.text = [], [], []
        self.script = None
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == 'script':
            self.script = dict(attrs=dict(attrs), text='')
            self.scripts.append(self.script)

    def handle_endtag(self, tag):
        if tag == 'script':
            self.script = None

    def handle_data(self, data):
        self.text.append(data)
        if self.script is not None:
            self.script['text'] += data


@pytest.fixture
def snapshot():
    model = dict(category='Home Depot', assessment_scope='schema_only',
                 observation_period='unknown', category_status='unavailable_not_supplied', facets=[])
    texts = ['🔧 red & blue drill', 'drill 12 inch', 'garden hose']
    records = [dict(id=f'q{i}', role='demand', category='Home Depot', source='homedepot',
                    text=text, count=42) for i, text in enumerate(texts)]
    quote = 'red & blue'
    start = texts[0].index(quote)
    findings = [
        dict(id='error-1', record_id='q0', kind='missed_constraint', severity='medium',
             status='confirmed_error', summary='Colour was omitted', expected='Colour constraint',
             observed='Product type only', quote=quote, start=start, end=start + len(quote),
             correction=None),
        dict(id='correction-1', record_id='q1', kind='unit_error', severity='high',
             status='corrected', summary='Unit interpretation corrected', expected={'size': '12 in'},
             observed={'size': '12 ft'}, quote=texts[1], start=0, end=len(texts[1]),
             correction='Use inches.\nRetain the original query.'),
        dict(id='review-1', record_id='q0', kind='disagreement', severity='low',
             status='needs_review', summary='Possible colour alternative', expected=['red', 'blue'],
             observed='One combined colour', quote=quote, start=start, end=start + len(quote),
             correction=None),
    ]
    audit = dict(status='reviewed', method='agent_review', sample_size=12,
                 independent=False, findings=findings)
    bp = dict(candidates=[], already_represented=[], metrics={}, audit=audit)
    report = dict(id='audit-test', status='completed', model=model, benchmark=bp)
    return report, records, bp


# Exercise the shipped script and its event handlers with minimal local elements.
# This is not a browser/layout test and cannot launch a browser or make requests.
JS_DRIVER = r"""
const fs=require('node:fs'), vm=require('node:vm'), {Blob}=require('node:buffer');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const elements=new Map(), handlers={}, windowHandlers={};
let exportedBlob, exportedName;
function element(id){
  if(!elements.has(id)) elements.set(id,{
    innerHTML:'',textContent:'',hidden:false,open:false,dataset:{},handlers:{},
    classList:{add(){}},setAttribute(){},removeAttribute(){},
    addEventListener(type,callback){this.handlers[type]=callback;},
    showModal(){this.open=true;},
    close(){if(this.open){this.open=false;this.handlers.close?.();}}
  });
  return elements.get(id);
}
element('#benchmark-data').textContent=JSON.stringify(input.data);
const location={hash:input.hash||'#audit'};
const document={
  body:element('body'),activeElement:null,
  getElementById:id=>element('#'+id),querySelector:element,querySelectorAll:()=>[],
  addEventListener:(type,callback)=>{handlers[type]=callback;},
  createElement:()=>({click(){exportedName=this.download;}})
};
const context={document,location,Intl,URLSearchParams,Blob,
  URL:{createObjectURL:blob=>{exportedBlob=blob;return 'blob:local';},revokeObjectURL(){}},
  history:{replaceState:(a,b,hash)=>{location.hash=hash;}},setTimeout:callback=>callback(),
  window:{addEventListener:(type,callback)=>{windowHandlers[type]=callback;},scrollTo(){}}
};
vm.runInNewContext(input.script,context,{timeout:5000});
function snapshot(){return {
  title:element('#page-title').textContent,nav:element('#navigation').innerHTML,
  description:element('#page-description').textContent,scope:element('#scope-notice').textContent,
  content:element('#content').innerHTML,table:element('#table-content').innerHTML,
  inspector:element('#inspector-content').innerHTML,hash:location.hash,
  announcement:element('#announcement').textContent
};}
(async()=>{
  const snapshots=[snapshot()];
  for(const action of input.actions||[]){
    if(action.type==='navigate'){
      location.hash=action.hash;element('#table-content').innerHTML='';windowHandlers.hashchange();
    }else if(action.type==='input'||action.type==='change'){
      handlers[action.type]({target:{id:action.id,value:action.value}});
    }else if(action.type==='click'){
      handlers.click({target:{closest:()=>({dataset:action.dataset})}});
    }else if(action.type==='export'){
      element('#export').handlers.click();
    }else if(action.type==='methodology'){
      element('#methodology').handlers.click();
    }
    snapshots.push(snapshot());
  }
  process.stdout.write(JSON.stringify({snapshots,exportedName,csv:exportedBlob?await exportedBlob.text():null}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


def run_ui(snapshot, *, actions=(), hash='#audit', records=True):
    node = shutil.which('node')
    if not node:
        pytest.skip('A local Node runtime is required for non-browser UI contract checks')
    report, sources, bp = snapshot
    page = Markup(render_benchmark(report, records=sources if records else None, benchmark=bp))
    data, script = page.scripts
    result = subprocess.run([node, '-e', JS_DRIVER], input=json.dumps(dict(
        data=json.loads(data['text']), script=script['text'], actions=actions, hash=hash)),
        text=True, encoding='utf-8', capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def text(markup):
    return ' '.join(Markup(markup).text)


def csv_rows(result):
    return list(csv.DictReader(io.StringIO(result['csv'].lstrip('\ufeff')), delimiter=';'))


@pytest.mark.parametrize('embedded', [False, True])
def test_audit_is_a_deepcopy_without_reclassifying_or_translating(snapshot, embedded):
    report, records, bp = snapshot
    original = deepcopy(snapshot)
    view = build_view(report, records=records, benchmark=None if embedded else bp,
                      display_translations={'red': 'translated', 'Colour constraint': 'translated'})
    assert view['audit'] == bp['audit']
    assert [f['status'] for f in view['audit']['findings']] == [
        'confirmed_error', 'corrected', 'needs_review']
    view['audit']['findings'][1]['expected']['size'] = 'modified'
    view['audit']['findings'][2]['expected'].append('modified')
    view['audit']['findings'][0]['status'] = 'modified'
    view['audit']['sample_size'] = 999
    assert snapshot == original
    fresh = build_view(report, records=records, benchmark=bp)
    bp['audit']['findings'][1]['expected']['size'] = 'changed input'
    assert fresh['audit'] == original[2]['audit']


@pytest.mark.parametrize('audit_value', ['absent', None, {}])
def test_no_audit_keeps_existing_navigation_and_never_invents_results(snapshot, audit_value):
    report, records, bp = snapshot
    if audit_value == 'absent':
        del bp['audit']
    else:
        bp['audit'] = audit_value
    view = build_view(report, records=records, benchmark=bp)
    assert view.get('audit') == (None if audit_value == 'absent' else audit_value)
    result = run_ui(snapshot)['snapshots'][0]
    assert '#audit' not in result['nav']
    assert result['hash'] == '#overview'
    assert result['title'] == 'Overview'
    assert 'Confirmed errors:' not in result['content']


def test_review_counts_use_supplied_denominator_and_explicit_statuses(snapshot):
    result = run_ui(snapshot)['snapshots'][0]
    content = text(result['content'])
    assert result['title'] == 'Errors & review'
    assert '#audit' in result['nav']
    assert 'Reviewed denominator:  12 queries' in content
    assert 'Not independent' in content
    assert 'Confirmed errors: 1' in content
    assert 'Corrected: 1' in content
    assert 'Needs review: 1' in content
    assert 'Disagreements are not automatically errors' in content
    assert 'not an error rate' in content
    assert '126' not in content  # Demand weights are not the reviewed denominator.


@pytest.mark.parametrize('sample_size', [None, 0, 12])
def test_empty_review_does_not_claim_error_free_or_invent_reviewed_count(snapshot, sample_size):
    audit = snapshot[2]['audit']
    audit['findings'] = []
    audit['sample_size'] = sample_size
    audit.pop('independent')
    result = run_ui(snapshot, actions=[dict(type='export')])
    content = text(result['snapshots'][0]['content'])
    assert 'No findings supplied' in content
    assert 'Independence not provided' in content
    assert 'Confirmed errors:' not in content
    assert f"Reviewed denominator:  {str(sample_size) + ' queries' if sample_size is not None else 'Not provided'}" in content
    assert csv_rows(result) == []


def test_search_status_filter_and_csv_share_the_same_findings(snapshot):
    actions = [dict(type='input', id='search', value='🔧'),
               dict(type='change', id='audit-status-filter', value='needs_review'),
               dict(type='export')]
    result = run_ui(snapshot, actions=actions)
    assert '2 matching findings' in text(result['snapshots'][1]['table'])
    assert '1 matching findings' in text(result['snapshots'][2]['table'])
    rows = csv_rows(result)
    assert [r['id'] for r in rows] == ['review-1']
    assert rows[0]['status'] == 'needs_review'
    assert rows[0]['kind'] == 'disagreement'
    assert rows[0]['reviewed_sample_size'] == '12'
    assert rows[0]['independent'] == 'false'
    assert rows[0]['source_query'] == snapshot[1][0]['text']
    assert json.loads(rows[0]['expected']) == ['red', 'blue']
    assert result['exportedName'] == 'pilon-benchmark-audit.csv'


def test_pagination_searches_all_findings_and_export_is_not_page_limited(snapshot):
    base = snapshot[2]['audit']['findings'][0]
    snapshot[2]['audit']['findings'] = [dict(base, id=f'finding-{i}', summary=f'Finding {i:02}')
                                         for i in range(27)]
    result = run_ui(snapshot, actions=[dict(type='click', dataset={'pageStep': '1'}),
                                      dict(type='export'),
                                      dict(type='input', id='search', value='finding 00')])
    assert sum(tag == 'tr' for tag, _ in Markup(result['snapshots'][0]['content']).tags) == 26
    assert sum(tag == 'tr' for tag, _ in Markup(result['snapshots'][1]['content']).tags) == 3
    assert len(csv_rows(result)) == 27
    assert '1 matching findings' in text(result['snapshots'][-1]['table'])
    assert 'Finding 00' in text(result['snapshots'][-1]['table'])


def test_inspection_preserves_unicode_query_and_readable_correction(snapshot):
    result = run_ui(snapshot, actions=[dict(type='click', dataset={'audit': 'error-1'}),
                                      dict(type='click', dataset={'audit': 'correction-1'})])
    detail = result['snapshots'][1]['inspector']
    assert '🔧 <mark>red &amp; blue</mark> drill' in detail
    assert 'Verified span · [2, 12)' in text(detail)
    assert 'data-demand="q0"' in detail
    correction = text(result['snapshots'][2]['inspector'])
    assert 'Expected' in correction and 'Observed' in correction and 'Correction' in correction
    assert '"size": "12 in"' in correction and '"size": "12 ft"' in correction
    assert 'Use inches.\nRetain the original query.' in correction


@pytest.mark.parametrize('bounds', [(0, 1), (-15, 12), (2, 999), (12, 2)])
def test_mismatched_span_never_highlights_or_replaces_full_query(snapshot, bounds):
    finding = snapshot[2]['audit']['findings'][0]
    finding['start'], finding['end'] = bounds
    detail = run_ui(snapshot, actions=[dict(type='click', dataset={'audit': 'error-1'})])['snapshots'][-1]['inspector']
    assert '<mark>' not in detail
    assert '🔧 red &amp; blue drill' in detail
    assert 'Span not verified' in text(detail)


def test_missing_source_is_an_excerpt_not_an_invented_query(snapshot):
    result = run_ui(snapshot, records=False, actions=[dict(type='click', dataset={'audit': 'error-1'})])
    detail = result['snapshots'][-1]['inspector']
    assert 'Full source query unavailable' in text(detail)
    assert 'red &amp; blue' in detail
    assert '<mark>' not in detail
    assert 'data-demand=' not in detail


def assert_inert(markup):
    parsed = Markup(markup)
    assert not any(tag in {'img', 'iframe', 'object', 'embed'} for tag, _ in parsed.tags)
    assert not any(key.lower().startswith('on') for _, attrs in parsed.tags for key in attrs)


def test_untrusted_audit_round_trips_and_is_escaped_in_all_ui_surfaces(snapshot):
    report, records, bp = snapshot
    attack = '</script><img src=x onerror="alert(1)"><script>alert(2)</script>&\"\' café\u2028\u2029'
    audit = bp['audit']
    audit['status'] = audit['method'] = attack
    finding = audit['findings'][0]
    for key in ('id', 'record_id', 'kind', 'severity', 'status', 'summary', 'expected',
                'observed', 'quote', 'correction'):
        finding[key] = attack
    records[0]['id'] = attack
    records[0]['text'] = attack
    finding.update(start=0, end=len(attack))
    markup = render_benchmark(report, records=records, benchmark=bp)
    page = Markup(markup)
    assert len(page.scripts) == 2
    assert json.loads(page.scripts[0]['text'])['audit'] == audit
    assert attack not in markup
    assert_inert(markup)
    result = run_ui(snapshot, actions=[dict(type='click', dataset={'audit': attack})])
    for fragment in (result['snapshots'][0]['content'], result['snapshots'][-1]['inspector']):
        assert_inert(fragment)
        assert not Markup(fragment).scripts
        assert '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;' in fragment


def test_csv_preserves_multiline_corrections_and_blocks_formulas(snapshot):
    finding = snapshot[2]['audit']['findings'][1]
    finding['summary'] = '=HYPERLINK("bad")'
    result = run_ui(snapshot, actions=[dict(type='input', id='search', value='inches'),
                                      dict(type='export')])
    row, = csv_rows(result)
    assert row['id'] == 'correction-1'
    assert row['summary'] == "'" + finding['summary']
    assert row['correction'] == finding['correction']
    assert json.loads(row['expected']) == finding['expected']


@pytest.mark.parametrize('corpus', ['Home Depot', 'WANDS'])
def test_corpus_labels_preserve_wands_and_do_not_mislabel_home_depot(snapshot, corpus):
    report, records, bp = snapshot
    report['model']['category'] = corpus
    if corpus == 'WANDS':
        report['model'].pop('category_status')
    for record in records:
        record['category'] = corpus
    bp.pop('audit')
    result = run_ui(snapshot, hash='#overview', actions=[dict(type='methodology'),
                                                        dict(type='navigate', hash='#demands')])
    first, method, demands = result['snapshots']
    assert first['description'] == f'Customer queries from {corpus} compared with the reconstructed schema.'
    assert f'unofficial reconstructed {corpus} model' in first['scope']
    if corpus == 'WANDS':
        assert 'official Wayfair production ontology' in text(method['inspector'])
        assert 'distinct taxonomies' in text(demands['content'])
    else:
        assert 'No query or product category taxonomy was supplied' in text(demands['content'])
        assert 'Categories not supplied' in text(method['inspector'])
        assert 'WANDS' not in method['inspector'] + first['scope']
        assert 'Wayfair' not in method['inspector']
