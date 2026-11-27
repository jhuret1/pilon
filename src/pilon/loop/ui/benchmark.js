/* Local, dependency-free Benchmark interactions. No inference or remote request. */
(() => {
  'use strict';
  const D = JSON.parse(document.getElementById('benchmark-data').textContent);
  D.attributes ||= D.model.facets || [];
  const $ = s => document.querySelector(s);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const n = v => v == null ? '—' : new Intl.NumberFormat('en-GB').format(v);
  const schemaOnly = D.model.assessment_scope === 'schema_only';
  const semanticReview = schemaOnly && D.analysis?.method === 'agent_semantic_review' && D.analysis?.status === 'reviewed';
  const P = D.product_view;
  if(P) P.covered ||= [];
  const productMode = semanticReview && !!P;
  const analysisLabel = semanticReview ? 'Supplied semantic review' : 'Local lexical detector';
  const matchLabel = semanticReview ? 'review-proposed match' : 'candidate lexical match';
  const unknownPeriod = D.model.observation_period === 'unknown';
  const modelVersion = D.model.version || D.model.provenance?.version || 'Version not provided';
  const schemaDescription = 'Model reconstructed from attribute names and observed values published in WANDS; this is not the official Wayfair production ontology.';
  const lexicalDescription = semanticReview
    ? 'Supplied semantic review: matches and proposals need confirmation. An uninterpreted query does not prove an attribute is missing; the model does not establish filter availability.'
    : 'Local lexical detector: matches are candidates, without validation of the full query. An unclassified query does not prove an attribute is missing.';
  const paths = {
    overview:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
    opportunities:'M4 18V9m5 9V4m5 14v-6m5 6V7M3 21h18',
    demands:'M21 11a8 8 0 0 1-8 8H6l-4 3V11a9 9 0 0 1 19 0ZM7 9h9M7 13h6',
    model:'M9 3h6v5H9zM2 16h6v5H2zM16 16h6v5h-6zM12 8v4M5 16v-4h14v4',
    sources:'M4 4h6l2 3h8v13H4zM8 11h8M8 15h5',
    history:'M3 10a9 9 0 1 1 2 8M3 4v6h6M12 7v5l3 2',
    search:'M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm6-2 6 6',
    close:'m6 6 12 12M6 18 18 6',
    chevron:'m9 5 7 7-7 7',
    back:'m15 5-7 7 7 7',
    download:'M12 3v12m-5-5 5 5 5-5M4 15v6h16v-6',
    calendar:'M4 5h16v16H4zM4 10h16M8 3v4M16 3v4',
    box:'m12 2 10 5v10l-10 5L2 17V7Zm0 10v10M2 7l10 5 10-5M7 4.5l10 5',
    star:'m12 3 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1Z',
    check:'m5 12 4 4L19 6',
    info:'M12 8v.1M12 11v6M22 12A10 10 0 1 1 2 12a10 10 0 0 1 20 0',
    fingerprint:'M5 16v-4a7 7 0 0 1 14 0v5M8 19v-7a4 4 0 0 1 8 0v7M12 12v9'
  };
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.sources}"/></svg>`;
  const gaps = {
    schema_gap:{label:'Missing attribute', plural:'Missing attributes',color:'#8c73db', diagnosis:'This need has no attribute in the model.',next:'Define the attribute and its expected values. Its availability in product sources still needs assessment.'},
    coverage_gap:{label:'Incomplete coverage',plural:'Incomplete coverage',color:'#d6a251',diagnosis:'The attribute exists, but product coverage is incomplete.',next:'Identify products with no value in the model. A source mention is not yet an integrated value.'},
    retrieval_gap:{label:'Search needs improvement',plural:'Search needs improvement',color:'#6a9dbf',diagnosis:'The model covers the need, but the request is still poorly served.',next:'Review the filters, ranking and search results for this request.'},
    unresolved_intent:{label:'Needs clarification',plural:'Needs to clarify',color:'#abb2c2',diagnosis:'The request is retained, but its intent needs clarification.',next:'Clarify the need before proposing an attribute. This ambiguity alone does not create a fact.'}
  };
  if(schemaOnly){
    delete gaps.coverage_gap;
    delete gaps.retrieval_gap;
    gaps.unresolved_intent = {...gaps.unresolved_intent,label:'Uninterpreted',plural:'Uninterpreted queries',diagnosis:'The lexical detector did not interpret this query.',next:'It remains in the review queue; no missing attribute or value has been established.'};
    gaps.schema_gap = {...gaps.schema_gap, label:'Attribute to review', plural:'Attributes to review', diagnosis:'A candidate attribute is flagged outside the reconstructed schema.', next:'Review the query and published attribute names before concluding the model has a gap.'};
    gaps.value_gap = {label:'Unobserved value · needs confirmation', plural:'Values to confirm',color:'#c49057',diagnosis:'The requested value has no exact match among observed values.',next:'Published values are not exhaustive. Check variants and request meaning before concluding a value is missing.'};
    gaps.filter_proposal = {label:'Filter to propose',plural:'Filters to propose',color:'#599b90',diagnosis:'The data is represented; a filtering capability is proposed.',next:'Filter availability in the live service is unknown. This proposal does not establish that a filter is missing.'};
    if(semanticReview) gaps.unresolved_intent.diagnosis = 'This query remains uninterpreted in the supplied review.';
  }
  const channels = {site_search:['Site search','search'],support_chat:['Support conversations','demands'],store_review:['Customer reviews','star'],feedback_form:['Customer forms','sources']};
  const channel = name => channels[name]?.[0] || name || 'Source not provided';
  const channelIcon = name => channels[name]?.[1] || 'sources';
  const badge = gap => `<span class="badge ${gaps[gap] ? gap : ''}">${esc(gaps[gap]?.label || gap || 'Needs checking')}</span>`;
  const pages = {
    overview:['Overview','Gaps between demand and your business model.','overview'],
    opportunities:['Opportunities','Needs to address, ranked by observed demand.','opportunities'],
    demands:['Customer requests','Original wording and related needs.','demands'],
    model:['Business model','The reference model used for this Benchmark.','model'],
    sources:['Sources','Demand channels present in this sample.','sources'],
    runs:['History','Browse the results of each run.','history']
  };
  if(schemaOnly){
    pages.overview[1] = 'Customer queries from WANDS compared with the reconstructed schema.';
    pages.opportunities = ['To review',semanticReview?'Proposals from the semantic review and queries awaiting clarification.':'Review queue: uninterpreted queries and lexical candidates to confirm.','opportunities'];
    pages.demands[1] = 'Full queries and corpus categories; actual frequency unknown.';
    pages.model = ['Data model','Attributes, observed values and product categories in the reconstructed model.','model'];
    pages.sources[1] = 'Provenance of the sampled query corpus.';
    pages.runs = ['Runs','Saved results for this read-only preview.','history'];
  }
  if(productMode){
    pages.overview = ['Summary','Next improvements to your catalogue.','overview'];
    pages.opportunities = ['Recommendations','Filters to propose and needs to explore.','opportunities'];
    pages.demands = ['Customer requests','Searches behind the recommendations.','demands'];
    pages.model = ['Catalogue model','Available attributes and values.','model'];
  }
  let page = 'overview', query = '', gapFilter = 'all', sourceFilter = 'all', categoryFilter = 'all', sort = 'volume', pageIndex = 0;
  let recommendationMode = 'filters';
  let activeCandidate = null, detailTab = 'diagnostic', lastFocus = null;
  let activeFacet = null, valueQuery = '', valueCategory = 'all', valuePageIndex = 0;
  const PAGE_SIZE = 25;
  const ready = D.ready;
  const productItemById = new Map(productMode?[...P.filters,...P.explore,...P.covered,...P.uncertain].map(item=>[item.id,item]):[]);
  const candidates = D.candidates.filter(c => !schemaOnly || !['coverage_gap','retrieval_gap'].includes(c.gap_type));
  const candidateByKey = new Map(candidates.map(c => [c.key,c]));
  const demandById = new Map(D.demands.map(r => [r.id,r]));
  const uniqueSources = c => [...new Set((c.demand_records || []).map(p => p.source))];
  const countRecords = c => new Set((c.demand_records || []).map(p => p.record_id)).size;
  const volume = c => schemaOnly ? countRecords(c) : c.demand_events || 0;
  const maxVolume = Math.max(1,...candidates.map(volume));
  const candidateTitle = c => c.gap_type === 'unresolved_intent'
    ? (c.demand_records || []).map(p => demandById.get(p.record_id)?.text || p.quote).find(Boolean) || c.label || c.key
    : c.gap_type === 'value_gap' || (semanticReview && c.requested_value!=null) ? `${c.label||c.fact_key}: ${c.requested_value??'value to clarify'}` : c.label || c.key;
  const demandCategory = r => r.query_class || (schemaOnly ? 'Not provided' : r.category || D.model.category || 'Not provided');
  const scopes = f => Array.isArray(f.scopes) ? f.scopes : [];
  const facetByKey = new Map(D.attributes.map(f => [f.key,f]));
  const modelValueCount = D.attributes.reduce((total,f) => total+(f.values || []).length,0);
  const valueText = value => typeof value === 'object' ? JSON.stringify(value) : String(value);
  const valueScopes = (f,value) => Object.hasOwn(f.value_scopes || {},valueText(value)) ? f.value_scopes[valueText(value)] : [];
  const gapCount = key => candidates.filter(c => c.gap_type === key).length;
  const representedMatches = r => (r.represented || []).filter(p => !schemaOnly || p.status === 'schema_represented');
  const representedCount = D.demands.filter(r => representedMatches(r).length).length;
  const uninterpretedCount = D.demands.filter(r => r.matches.some(p=>candidateByKey.get(p.candidate_key)?.gap_type==='unresolved_intent') || (!r.matches.length&&!representedMatches(r).length)).length;
  const reviewLabel = schemaOnly ? 'items to review' : 'opportunities';
  const stateLabel = D.status === 'failed' ? 'Failed' : productMode ? `${n(D.analysis.reviewed_records)} requests analysed` : ready ? (schemaOnly?(semanticReview?`Supplied semantic review · ${n(D.analysis.reviewed_records)} queries reviewed`:'Data imported · semantic analysis not performed'):'Benchmark available') : D.status === 'empty' ? 'No runs' : 'Awaiting results';
  const statusClass = D.status === 'failed' ? 'failed' : ready && !schemaOnly ? 'complete' : '';
  $('#navigation').innerHTML = Object.entries(pages).filter(([k]) => k !== 'runs').map(([key,[label,,ico]],i) => `${i===3?'<div class="nav-separator"></div>':''}<a href="#${key}" title="${label}">${icon(ico)}<span class="nav-text">${label}</span>${key==='opportunities'?`<span class="nav-count">${n(productMode?P.filters.length+P.explore.length:candidates.length)}</span>`:''}</a>`).join('');
  document.querySelectorAll('[data-icon]').forEach(el => el.innerHTML = icon(el.dataset.icon));
  $('#workspace-name').textContent = D.model.category || (schemaOnly ? 'WANDS' : 'Local workspace');
  $('#snapshot-state').textContent = stateLabel;
  $('#snapshot-state').className = `badge ${statusClass}`;
  $('#demo-label').textContent = D.synthetic ? 'DEMO' : '';
  $('#demo-banner').hidden = !D.synthetic;
  $('#category').innerHTML = `${icon('box')}${esc(D.model.category || (schemaOnly ? 'WANDS' : 'Category not provided'))}${schemaOnly?' · Schema only':''}`;
  const date = value => value ? new Date(`${value}T12:00:00`).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}) : '—';
  $('#period').innerHTML = unknownPeriod || schemaOnly ? 'Observation period unknown' : `${icon('calendar')}${esc(date(D.model.window_start))} – ${esc(date(D.model.window_end))}`;
  $('#footer-context').textContent = `${modelVersion} · ${D.complete_inputs?'Corpus supplied':'Excerpts available'} · Read-only`;
  $('#scope-notice').hidden = !schemaOnly;
  $('#scope-notice').textContent = semanticReview
    ? 'Read-only preview · unofficial reconstructed WANDS model. Supplied semantic review; proposals need confirmation, filtering capabilities unknown.'
    : 'Local read-only preview · unofficial reconstructed WANDS model. Lexical detection: candidate matches, without full query validation. Unclassified ≠ missing attribute.';
  if(productMode){
    document.body.classList.add('product-workspace');
    $('#scope-notice').hidden=true;
    $('#category').textContent=`${D.model.category} · Catalogue by category`;
    $('#period').hidden=true;
    $('#footer-context').textContent='Suggestions · no changes published';
    $('#methodology').textContent='Sources & method';
  }
  if(schemaOnly) document.querySelectorAll('a[href="#runs"]').forEach(a => {a.setAttribute('aria-label','View runs');a.title='Runs';if(a.classList.contains('history-link'))a.innerHTML=`${icon('history')} Runs`;});
  function empty(title,description='') { return `<div class="empty">${icon('search')}<h2>${esc(title)}</h2><p>${esc(description)}</p></div>`; }
  function announce(text) { $('#announcement').textContent = text; }
  function metric(label,value,caption,ico,accent=false) { return `<div class="metric"><div class="metric-label">${label}${icon(ico)}</div><strong class="num">${n(value)}</strong><small class="${accent?'accent':''}">${caption}</small></div>`; }
  function notice() {
    if(D.status==='failed') return `<div class="state-notice failed">Run interrupted. Available results are partial.${D.error?`<details><summary>View error</summary><pre>${esc(D.error)}</pre></details>`:''}</div>`;
    return ready ? '' : `<div class="state-notice">${D.status==='empty'?'No Benchmark available.':'The Benchmark has not produced results yet.'}</div>`;
  }
  function channelSymbols(c) { return `<span class="channel-list">${uniqueSources(c).map(s=>`<span class="channel-symbol" title="${esc(channel(s))}" aria-label="${esc(channel(s))}">${icon(channelIcon(s))}</span>`).join('')}</span>`; }
  function coverage(c) {
    if(c.gap_type==='schema_gap') return '<span class="muted">Missing attribute</span>';
    if(c.gap_type==='unresolved_intent') return '<span class="muted">Not assessed</span>';
    return `<span class="num">${n(c.known_assignment_count)} <span class="muted">/ ${n(D.summary.inventory_products)} products</span></span>`;
  }
  function opportunityTable(items,compact=false,total=items.length) {
    if(!items.length) return empty(schemaOnly?'No items to review':'No opportunities shown',query||gapFilter!=='all'?'Adjust the search or filters.':ready?(schemaOnly?'No lexical candidates flagged; this does not validate the queries.':'No gaps detected in this result.'):'Results will appear after the Benchmark.');
    return `<div class="table-wrap"><table class="opportunity-table" aria-label="Knowledge opportunities"><thead><tr><th>Customer need</th><th>${schemaOnly?'Assessment':'Diagnosis'}</th><th>${schemaOnly?'Queries':'Requests'}</th><th class="channel-col">${schemaOnly?'Sources':'Channels'}</th>${schemaOnly?'':'<th class="coverage-col">Current model</th>'}<th class="open-col"><span class="sr-only">Details</span></th></tr></thead><tbody>${items.map(c=>`<tr><td><button class="item-title" data-candidate="${esc(c.key)}">${esc(candidateTitle(c))}</button><span class="item-subtitle">${n(countRecords(c))} source text${countRecords(c)!==1?'s':''}</span></td><td>${badge(c.gap_type)}</td><td><span class="cell-metric"><b class="num">${n(volume(c))}</b><span class="mini-track"><i style="width:${Math.min(100,100*volume(c)/maxVolume)}%"></i></span></span></td><td class="channel-col">${channelSymbols(c)}</td>${schemaOnly?'':`<td class="coverage-col">${coverage(c)}</td>`}<td class="open-col"><button class="icon-button" data-candidate="${esc(c.key)}" aria-label="Review ${esc(candidateTitle(c))}">${icon('chevron')}</button></td></tr>`).join('')}</tbody></table></div><div class="table-bottom"><span>${compact?`${n(items.length)} ${reviewLabel} · ${schemaOnly?'corpus queries':'priority by volume'}`:`${n(total)} ${reviewLabel}`}</span>${compact?'<a href="#opportunities" class="text-button">Explore all</a>':pager(total)}</div>`;
  }
  function overview() {
    if(productMode)return productOverview();
    const s=D.summary;
    let start=0; const slices=Object.entries(gaps).map(([key,g])=>{let end=start+(gapCount(key)/Math.max(1,candidates.length))*100;const out=`${g.color} ${start}% ${end}%`;start=end;return out;}).join(',');
    const metrics = schemaOnly
      ? metric('Corpus queries',D.complete_inputs?s.demand_records:null,D.complete_inputs?'Sample · actual frequency unknown':`${n(s.demand_records)} references available · incomplete corpus`,'demands')+metric('Matched queries',ready?representedCount:null,semanticReview?'Review-proposed matches':'Candidate lexical matches','search')+metric('Uninterpreted queries',ready?uninterpretedCount:null,'Review queue · no gap established','opportunities')+metric('Published attributes',s.attributes,`${n(modelValueCount)} observed attribute–value pairs`,'model')
      : metric('Observed requests',D.complete_inputs?s.demand_events:null,`${n(s.demand_records)} source texts`,'demands')+metric('Opportunities',ready?s.opportunity_count:null,'Needs not fully covered','opportunities')+metric('Attributes to consider',ready?s.schema_gaps:null,'Missing from the current model','model',true)+metric('Existing attributes',s.attributes,`${n(s.inventory_products)} products in scope`,'box');
    return `${notice()}<div class="metrics">${metrics}</div>
    <div class="overview-grid"><section class="panel"><div class="panel-heading"><div><h2>What customers ask for</h2><small>${schemaOnly?'Top 5 queries to review':'Top 5 needs · observed events'}</small></div></div><div class="panel-body">${candidates.length?candidates.slice(0,5).map(c=>`<button class="rank-row" data-candidate="${esc(c.key)}" title="Review ${esc(candidateTitle(c))}"><span class="rank-label">${esc(candidateTitle(c))}</span><span class="bar-track"><span class="bar-fill" style="display:block;width:${100*volume(c)/maxVolume}%"></span></span><strong class="num">${n(volume(c))}</strong></button>`).join(''):empty('No needs available')}</div></section>
    <section class="panel"><div class="panel-heading"><div><h2>${schemaOnly?'Candidates to review':'Where are the gaps?'}</h2><small>${schemaOnly?'Review queue':'Opportunity breakdown'}</small></div></div><div class="panel-body"><div class="gap-chart"><div class="donut" style="background:${candidates.length?`conic-gradient(${slices})`:'#f0f1f6'}" role="img" aria-label="${n(candidates.length)} ${reviewLabel}"><div class="donut-center">${ready?n(candidates.length):'—'}<small>${schemaOnly?'to review':'opportunities'}</small></div></div><div class="legend">${Object.entries(gaps).map(([key,g])=>`<button data-gap-link="${key}"><i class="swatch ${key}"></i>${g.plural}<strong>${ready?n(gapCount(key)):'—'}</strong></button>`).join('')}</div></div></div></section></div>
    <section class="panel"><div class="panel-heading"><div><h2>${schemaOnly?'Queries to review':'Opportunities to explore'}</h2><small>${schemaOnly?'Queries to review; gaps still need confirmation.':'From customer demand to identified gaps.'}</small></div><a class="text-button" href="#opportunities">View all</a></div>${opportunityTable(candidates.slice(0,5),true)}</section>`;
  }
  function filteredCandidates() {
    const q=query.toLocaleLowerCase('en-GB');
    return candidates.filter(c=>(gapFilter==='all'||c.gap_type===gapFilter)&&(sourceFilter==='all'||uniqueSources(c).includes(sourceFilter))&&[candidateTitle(c),c.key,c.definition,...(c.demand_records||[]).map(p=>demandById.get(p.record_id)?.text||p.quote)].join(' ').toLocaleLowerCase('en-GB').includes(q)).sort((a,b)=>sort==='name'?String(candidateTitle(a)).localeCompare(String(candidateTitle(b)),'en-GB'):sort==='sources'?uniqueSources(b).length-uniqueSources(a).length:volume(b)-volume(a));
  }
  function sourceOptions() {return `<option value="all">${schemaOnly?'All sources':'All channels'}</option>${Object.keys(D.channels).map(s=>`<option value="${esc(s)}" ${sourceFilter===s?'selected':''}>${esc(channel(s))}</option>`).join('')}`;}
  function categoryOptions(items,selected=categoryFilter,label='All categories') {
    return `<option value="all">${esc(label)}</option>${[...new Set(items)].sort((a,b)=>a.localeCompare(b,'en-GB')).map(value=>`<option value="${esc(value)}" ${selected===value?'selected':''}>${esc(value)}</option>`).join('')}`;
  }
  function searchBox(placeholder) {return `<label class="search-field">${icon('search')}<input id="search" type="search" aria-label="${esc(placeholder)}" placeholder="${esc(placeholder)}" value="${esc(query)}"></label>`;}
  function pager(total) {return total>PAGE_SIZE?`<span class="pagination"><button data-page-step="-1" aria-label="Previous page" ${pageIndex===0?'disabled':''}>${icon('back')}</button>${pageIndex+1} / ${Math.ceil(total/PAGE_SIZE)}<button data-page-step="1" aria-label="Next page" ${(pageIndex+1)*PAGE_SIZE>=total?'disabled':''}>${icon('chevron')}</button></span>`:'';}
  const productLabels = {filters:'Filters to build',explore:'To explore',covered:'Already covered',uncertain:'Needs clarification'};
  const basisLabels = {existing_attribute:'Already covered',derived_filter:'Rule to define',missing_attribute:'Attribute to document',unobserved_value:'Value to check',unresolved:'Meaning to clarify'};
  const actionLabels = {existing_attribute:'No addition',derived_filter:'Define the rule',missing_attribute:'Document',unobserved_value:'Check the value',unresolved:'Clarify the need'};
  const productActions = {
    existing_attribute:'This criterion is already covered by the catalogue. No additional filter is proposed.',
    derived_filter:'Define the rule that turns existing data into a filter.',
    missing_attribute:'Explore product sources to document this criterion.',
    unobserved_value:'Check whether this value exists in product sources.',
    unresolved:'Clarify the request before proposing a filter.'
  };
  function productValues(item,limit=3){
    return item.values?.length?`<div class="tags requested-values">${item.values.slice(0,limit).map(v=>`<span class="tag">${esc(valueText(v))}</span>`).join('')}${item.values.length>limit?`<span class="tag more-values">+${n(item.values.length-limit)}</span>`:''}</div>`:'<span class="muted">To define</span>';
  }
  function filteredProducts(mode=recommendationMode){
    const q=query.toLocaleLowerCase('en-GB');
    return (P[mode]||[]).filter(item=>(categoryFilter==='all'||(categoryFilter==='unassigned'?!item.category_refs.length:item.category_refs.includes(categoryFilter)))&&[item.label,...item.category_refs,...(item.values||[]).map(valueText),...item.record_ids.map(id=>demandById.get(id)?.text||'')].join(' ').toLocaleLowerCase('en-GB').includes(q)).sort((a,b)=>sort==='name'?a.label.localeCompare(b.label,'en-GB'):b.demand_count-a.demand_count||a.label.localeCompare(b.label,'en-GB'));
  }
  function productTable(items,total=items.length,compact=false){
    if(!items.length)return empty(recommendationMode==='covered'?'No covered criteria shown':'No recommendations shown','Try another category or search.');
    return `<div class="table-wrap"><table class="recommendation-table" aria-label="${recommendationMode==='covered'?'Covered catalogue criteria':recommendationMode==='uncertain'?'Requests to clarify':'Catalogue recommendations'}"><thead><tr><th>${recommendationMode==='uncertain'?'Need':'Filter or criterion'}</th><th>${recommendationMode==='covered'?'Catalogue values':'Requested values'}</th><th>Requests</th><th>Next step</th><th class="open-col"><span class="sr-only">Details</span></th></tr></thead><tbody>${items.map(item=>`<tr><td><button class="item-title" data-product="${esc(item.id)}">${esc(item.label)}</button><span class="item-subtitle">${esc(item.category_refs.join(' · ')||'Category to clarify')}</span></td><td>${productValues(item)}</td><td class="num demand-count">${n(item.demand_count)}</td><td><span class="basis-badge ${esc(item.basis)}">${esc(actionLabels[item.basis])}</span></td><td class="open-col"><button class="icon-button" data-product="${esc(item.id)}" aria-label="View ${esc(item.label)}">${icon('chevron')}</button></td></tr>`).join('')}</tbody></table></div>${compact?'':`<div class="table-bottom"><span>${n(total)} ${recommendationMode==='covered'?'already covered criteria':recommendationMode==='uncertain'?'needs':'recommendations'}</span>${pager(total)}</div>`}`;
  }
  function productOverview(){
    const preview=(mode,title,subtitle)=>`<section class="panel"><div class="panel-heading"><div><h2>${title}</h2><small>${subtitle}</small></div><a class="text-button" href="#opportunities?mode=${mode}">View all ${icon('chevron')}</a></div><div class="recommendation-preview">${P[mode].slice(0,5).map(item=>`<button class="preview-row" data-product="${esc(item.id)}"><span><strong>${esc(item.label)}</strong><small>${esc(item.category_refs.join(' · ')||'Category to clarify')}</small>${productValues(item,2)}</span><span class="preview-count"><b>${n(item.demand_count)}</b><small>request${item.demand_count!==1?'s':''}</small></span>${icon('chevron')}</button>`).join('')||empty('No items')}</div></section>`;
    return `${notice()}<div class="metrics">${metric('Filters to build',P.filters.length,'Derived criteria to define','opportunities',true)}${metric('To explore',P.explore.length,'Knowledge to enrich','search')}${metric('Already covered',P.covered.length,'No addition proposed','check')}${metric('Requests analysed',D.analysis.reviewed_records,'In this sample','sources')}</div><div class="product-overview-grid">${preview('filters','Build new filters','Rules to define using existing data.')}${preview('explore','Enrich the catalogue','Criteria and values to document.')}</div>`;
  }
  function productOpportunities(){
    const items=filteredProducts();
    const categories=[...new Set([...P.filters,...P.explore,...P.covered,...P.uncertain].flatMap(item=>item.category_refs))];
    return `${notice()}<div class="filter-tabs product-tabs" aria-label="Catalogue assessment">${Object.entries(productLabels).map(([mode,label])=>`<button data-recommendation-mode="${mode}" class="${recommendationMode===mode?'active':''}" aria-pressed="${recommendationMode===mode}">${label}<span>${n(P[mode].length)}</span></button>`).join('')}</div><section class="panel"><div class="toolbar">${searchBox('Search filters or values…')}<select id="category-filter" aria-label="Catalogue category">${categoryOptions(categories)}<option value="unassigned" ${categoryFilter==='unassigned'?'selected':''}>Category to clarify</option></select><select id="sort" aria-label="Sort recommendations"><option value="volume" ${sort==='volume'?'selected':''}>Most requested</option><option value="name" ${sort==='name'?'selected':''}>Alphabetical order</option></select></div><div id="table-content">${productTable(items.slice(pageIndex*PAGE_SIZE,(pageIndex+1)*PAGE_SIZE),items.length)}</div></section><p class="product-footnote">Already covered criteria are excluded from recommendations · requests from this sample.</p>`;
  }
  function openProductItem(id){
    const item=productItemById.get(id);if(!item)return;
    activeCandidate=null;activeFacet=null;
    const facet=facetByKey.get(item.fact_key);
    const proofs=item.proofs||[];
    const first=proofs.slice(0,1).map(proofCard).join('');
    inspectorOpen(`<div class="drawer-heading product-heading"><span class="basis-badge ${esc(item.basis)}">${esc(basisLabels[item.basis])}</span><h2 id="inspector-title">${esc(item.label)}</h2><p>${esc(item.category_refs.join(' · ')||'Category to clarify')} · ${n(item.demand_count)} request${item.demand_count!==1?'s':''}</p></div><div class="drawer-body product-detail"><section class="recommendation-action ${item.basis==='existing_attribute'?'covered-action':''}"><h3>${esc(productActions[item.basis])}</h3>${productValues(item,50)}</section>${facet?`<section class="available-data"><span>Available data</span><button class="text-button" data-facet="${esc(facet.key)}">${esc(facet.label||facet.key)} ${icon('chevron')}</button>${item.model_values?.length?`<small>${esc(item.model_values.slice(0,8).map(valueText).join(' · '))}${item.model_values.length>8?'…':''}</small>`:''}</section>`:''}<h3>In customers’ words</h3>${first||'<p>No quotation available.</p>'}${proofs.length>1?`<details class="more-proofs"><summary>View other quotations (${n(proofs.length-1)})</summary>${proofs.slice(1).map(proofCard).join('')}</details>`:''}<details class="decision-details"><summary>${item.basis==='existing_attribute'?'Why is this criterion covered?':'Why this recommendation?'}</summary>${[...new Set(item.rationales||[])].map(r=>`<p>${esc(r)}</p>`).join('')||'<p>Criterion identified in the requests above.</p>'}<p>${item.basis==='existing_attribute'?'The model covers this need. This match is not an improvement to add.':item.basis==='derived_filter'?'The proposal adds a grouping rule to existing data; whether it is new to the site still needs checking.':'No match in this sample does not prove absence from the entire catalogue.'}</p></details></div>`,item.basis==='existing_attribute'?'ALREADY COVERED':item.basis==='unresolved'?'REQUEST TO CLARIFY':P.filters.includes(item)?'FILTER TO BUILD':'TO EXPLORE');
  }
  function productDemandTable(items,total){
    if(!items.length)return empty('No requests shown','Adjust the search or category.');
    return `<div class="table-wrap"><table class="demand-table product-demand-table" aria-label="Source requests"><thead><tr><th>Customer request</th><th>Category</th><th>Identified criteria</th></tr></thead><tbody>${items.map(r=>{const labels=[...new Set([...representedMatches(r).map(p=>p.requested_value!=null?`${p.label}: ${p.requested_value}`:p.label),...r.matches.map(m=>candidateByKey.get(m.candidate_key)).filter(c=>c&&c.gap_type!=='unresolved_intent').map(candidateTitle)])];return `<tr><td class="quote-cell"><button data-demand="${esc(r.id)}">${esc(r.text)}</button></td><td>${esc(demandCategory(r))}</td><td><div class="tags">${labels.slice(0,3).map(label=>`<span class="tag">${esc(label)}</span>`).join('')}${labels.length>3?`<span class="muted small">+${n(labels.length-3)}</span>`:''}${!labels.length?'<span class="muted">Needs clarification</span>':''}</div></td></tr>`;}).join('')}</tbody></table></div><div class="table-bottom"><span>${n(total)} requests</span>${pager(total)}</div>`;
  }
  function openProductDemand(r){
    activeCandidate=null;activeFacet=null;
    const related=[...productItemById.values()].filter(i=>i.record_ids.includes(r.id));
    const covered=related.filter(i=>i.basis==='existing_attribute');
    const actions=related.filter(i=>i.basis!=='existing_attribute');
    const section=(title,items)=>items.length?`<h3>${title}</h3><div class="demand-recommendations">${items.map(i=>`<button class="demand-recommendation" data-product="${esc(i.id)}"><span><strong>${esc(i.label)}</strong><small>${esc(basisLabels[i.basis])}</small></span>${icon('chevron')}</button>`).join('')}</div>`:'';
    inspectorOpen(`<div class="drawer-heading"><h2 id="inspector-title">${esc(r.text)}</h2><p>${esc(demandCategory(r))}</p></div><div class="drawer-body product-detail">${section('To build, explore or clarify',actions)}${section('Already covered by the catalogue',covered)}${!related.length?'<p>Product type already represented; no additional filter proposed.</p>':''}<details class="decision-details"><summary>Interpretation and references</summary>${representedMatches(r).map(representedDetail).join('')}<p class="mono">${esc(r.id)} · ${esc(channel(r.source))}</p></details></div>`,'CUSTOMER REQUEST');
  }
  function opportunities() {
    if(productMode)return productOpportunities();
    const items=filteredCandidates();
    return `${notice()}<div class="filter-tabs" aria-label="Diagnoses"><button data-gap="all" class="${gapFilter==='all'?'active':''}" aria-pressed="${gapFilter==='all'}">All<span>${n(candidates.length)}</span></button>${Object.entries(gaps).map(([key,g])=>`<button data-gap="${key}" class="${gapFilter===key?'active':''}" aria-pressed="${gapFilter===key}">${g.plural}<span>${n(gapCount(key))}</span></button>`).join('')}</div><section class="panel"><div class="toolbar">${searchBox('Search needs or quotations')}<select id="source-filter" aria-label="Filter by source">${sourceOptions()}</select><select id="sort" aria-label="Sort opportunities"><option value="volume" ${sort==='volume'?'selected':''}>${schemaOnly?'Corpus query count':'Highest demand first'}</option><option value="name" ${sort==='name'?'selected':''}>Need name</option><option value="sources" ${sort==='sources'?'selected':''}>Source count</option></select></div><div id="table-content">${opportunityTable(items.slice(pageIndex*PAGE_SIZE,(pageIndex+1)*PAGE_SIZE),false,items.length)}</div></section>`;
  }
  function filteredDemands(){const q=query.toLocaleLowerCase('en-GB');return D.demands.filter(r=>(sourceFilter==='all'||r.source===sourceFilter)&&(categoryFilter==='all'||demandCategory(r)===categoryFilter)&&[r.text,r.id,demandCategory(r),...r.matches.map(m=>m.candidate_key),...representedMatches(r).flatMap(m=>[m.fact_key,m.label])].join(' ').toLocaleLowerCase('en-GB').includes(q)).sort((a,b)=>schemaOnly?0:(b.count||1)-(a.count||1));}
  function valueStatus(status){return ({observed_exact:'Observed value · exact match',observed_semantic:'Observed value · proposed semantic match',represented_by_category:'Represented by a model category',attribute_represented:'Attribute represented in the model',not_observed_exact:'Unobserved value · needs confirmation',not_observed_semantic:'Value unobserved in review · needs confirmation',not_assessed:'Value not assessed',unresolved:'Value to clarify'})[status]||'Value not assessed';}
  function demandTags(r){
    const matched = r.matches.map(p=>candidateByKey.get(p.candidate_key)).filter(Boolean);
    const links = matched.map(c=>`<button class="tag tag-button" data-candidate="${esc(c.key)}">${esc(c.gap_type==='unresolved_intent'?(schemaOnly?'Uninterpreted':'Needs clarification'):candidateTitle(c))}</button>`).join('');
    const represented = representedMatches(r).map(p=>`<span class="tag schema-match">${esc(p.label||p.fact_key)} · ${schemaOnly?matchLabel:'already represented'}${schemaOnly?`<span class="item-subtitle">${esc(valueStatus(p.value_status))}${p.requested_value!=null?`: ${esc(p.requested_value)}`:''}</span>`:''}</span>`).join('');
    const qualification = schemaOnly ? (represented?'<p class="match-note">Full query not validated.</p>':!matched.length?'<span class="muted">Needs clarification · no conclusion about a missing attribute</span>':'') : '';
    return `<div class="tags">${links}${represented}${qualification||(!links&&!represented?'<span class="muted">No linked gap</span>':'')}</div>`;
  }
  function demandTable(items,total) {
    if(productMode)return productDemandTable(items,total);
    return items.length?`<div class="table-wrap"><table class="demand-table" aria-label="Source requests"><thead><tr><th>${schemaOnly?'Original query':'Original request'}</th><th>Category</th><th>Source</th>${schemaOnly?'':'<th>Volume</th>'}${schemaOnly||unknownPeriod?'':'<th class="date-col">Date</th>'}<th>${schemaOnly?(semanticReview?'Proposed assessment':'Lexical assessment'):'Related needs'}</th></tr></thead><tbody>${items.map(r=>`<tr><td class="quote-cell"><button data-demand="${esc(r.id)}">${esc(r.text||'Full text unavailable')}</button><span class="item-subtitle">${esc(r.id)}${r.excerpt_only?' · excerpt only':''}</span></td><td>${esc(demandCategory(r))}</td><td>${esc(channel(r.source))}</td>${schemaOnly?'':`<td class="num">${n(r.count||1)}</td>`}${schemaOnly||unknownPeriod?'':`<td class="date-col muted">${esc(r.date||'—')}</td>`}<td>${demandTags(r)}</td></tr>`).join('')}</tbody></table></div><div class="table-bottom"><span>${n(total)} ${schemaOnly?'corpus queries':'texts'} · each row counts once</span>${pager(total)}</div>`:empty('No requests shown','Adjust the search, category or source.');
  }
  function demands(){const items=filteredDemands();return `<section class="panel"><div class="toolbar">${searchBox('Search requests')}<select id="category-filter" aria-label="Filter by query category">${categoryOptions(D.demands.map(demandCategory),categoryFilter,'All query categories')}</select><select id="source-filter" aria-label="Filter by source">${sourceOptions()}</select></div><div id="table-content">${demandTable(items.slice(pageIndex*PAGE_SIZE,(pageIndex+1)*PAGE_SIZE),items.length)}</div>${schemaOnly&&!productMode?'<div class="placeholder-note">Query categories (query_class) and model product categories (product_class) are distinct taxonomies; no equivalence is assumed.</div>':''}</section>`;}
  function values(v){return Array.isArray(v)&&v.length?`<div class="tags">${v.map(x=>`<span class="tag">${esc(typeof x==='object'?JSON.stringify(x):x)}</span>`).join('')}</div>`:'<span class="muted small">Values not provided</span>';}
  function filteredAttributes(){const q=query.toLocaleLowerCase('en-GB');return D.attributes.filter(f=>(categoryFilter==='all'||scopes(f).includes(categoryFilter))&&([f.key,f.label,f.definition,...scopes(f)].join(' ').toLocaleLowerCase('en-GB').includes(q)||(f.values||[]).some(v=>(categoryFilter==='all'||valueScopes(f,v).includes(categoryFilter))&&valueText(v).toLocaleLowerCase('en-GB').includes(q))));}
  function attributeTable(items,total){
    return items.length?`<div class="table-wrap"><table class="attribute-table" aria-label="Model attributes"><thead><tr><th>Attribute</th><th>Product categories</th><th>${schemaOnly?'Observed values':'Values'}</th><th>${schemaOnly?'Model origin':'Definition'}</th></tr></thead><tbody>${items.map(f=>`<tr><td><button class="item-title" data-facet="${esc(f.key)}">${esc(f.label||f.key)}</button><code class="item-subtitle">${esc(f.key)}</code></td><td>${esc(scopes(f).slice(0,3).join(', ')||'Not provided')}${scopes(f).length>3?`<span class="item-subtitle">+ ${n(scopes(f).length-3)} categories · view details</span>`:''}</td><td><button class="text-button" data-facet="${esc(f.key)}">${n((f.values||[]).length)} values</button>${schemaOnly?'<span class="item-subtitle">Observed · not exhaustive</span>':''}</td><td>${schemaOnly?esc(['observed_attribute_names','observed_attribute_names_and_values'].includes(f.schema_source)?'Published attribute · reconstructed model':'Origin not provided'):esc(f.definition||'Definition not provided.')}</td></tr>`).join('')}</tbody></table></div><div class="table-bottom"><span>${n(total)} attributes · ${n(D.attributes.length)} total</span>${pager(total)}</div>`:empty('No attributes shown','Adjust the search or category.');
  }
  function provenance(){
    if(!D.model.provenance)return '';
    // Metadata stays inert text: opening the preview never fetches published URLs.
    return `<details class="provenance"><summary>Published provenance</summary><pre>${esc(JSON.stringify(D.model.provenance,null,2))}</pre></details>`;
  }
  function modelView(){
    const items=filteredAttributes();
    const categories=[...(D.model.categories||[]),...D.attributes.flatMap(scopes)];
    return `<section class="panel"><div class="panel-heading"><div><h2>Model attributes</h2><small>${n(D.attributes.length)} attributes · ${n(modelValueCount)} ${schemaOnly?'observed attribute–value pairs':'attribute–value pairs'} · ${n(new Set(categories).size)} product categories</small><small>${esc(modelVersion)}</small></div>${icon('model')}</div>${schemaOnly?`<div class="placeholder-note">${esc(schemaDescription)} Observed values are not exhaustive; they are not canonical lists of allowed values.</div>`:''}<div class="toolbar">${searchBox('Search attributes, values or categories')}<select id="category-filter" aria-label="Filter by product category">${categoryOptions(categories,categoryFilter,'All product categories')}</select></div><div id="table-content">${attributeTable(items.slice(pageIndex*PAGE_SIZE,(pageIndex+1)*PAGE_SIZE),items.length)}</div><div class="placeholder-note">The displayed model is the one used at the start of the Benchmark. <a class="text-button" href="#opportunities?gap=schema_gap">Review candidate attributes (${n(gapCount('schema_gap'))})</a></div>${provenance()}</section>`;
  }
  function filteredValues(f){const q=valueQuery.toLocaleLowerCase('en-GB');return (f.values||[]).filter(v=>(valueCategory==='all'||valueScopes(f,v).includes(valueCategory))&&valueText(v).toLocaleLowerCase('en-GB').includes(q));}
  function scopeSummary(items){return esc(items.slice(0,3).join(', ')||'Not provided')+(items.length>3?`<details class="scope-details"><summary>+ ${n(items.length-3)} categories</summary><p>${esc(items.slice(3).join(', '))}</p></details>`:'');}
  function facetValuesTable(f){
    const all=filteredValues(f), items=all.slice(valuePageIndex*PAGE_SIZE,(valuePageIndex+1)*PAGE_SIZE);
    return (items.length?`<div class="table-wrap"><table class="value-table" aria-label="Attribute values"><thead><tr><th>${schemaOnly?'Observed value':'Value'}</th><th>Product categories</th></tr></thead><tbody>${items.map(v=>`<tr><td class="value-text">${esc(valueText(v))}</td><td>${scopeSummary(valueScopes(f,v))}</td></tr>`).join('')}</tbody></table></div>`:empty('No values shown','Adjust the search or category; absence from this sample does not prove impossibility.'))+`<div class="table-bottom"><span>${n(all.length)} matching values · ${n((f.values||[]).length)} total</span>${all.length>PAGE_SIZE?`<span class="pagination"><button data-value-step="-1" aria-label="Previous values" ${valuePageIndex===0?'disabled':''}>${icon('back')}</button>${valuePageIndex+1} / ${Math.ceil(all.length/PAGE_SIZE)}<button data-value-step="1" aria-label="Next values" ${(valuePageIndex+1)*PAGE_SIZE>=all.length?'disabled':''}>${icon('chevron')}</button></span>`:''}</div>`;
  }
  function openFacet(key){
    const f=facetByKey.get(key);if(!f)return;
    activeCandidate=null;activeFacet=key;valueQuery='';valuePageIndex=0;valueCategory=categoryFilter;
    inspectorOpen(`<div class="drawer-heading"><h2 id="inspector-title">${esc(f.label||f.key)}</h2><span class="mono muted">${esc(f.key)}</span><p>${schemaOnly?'Observed values · not exhaustive. These are not a canonical list; a missing value still needs confirmation.':esc(f.definition||'Definition not provided.')}</p></div><div class="drawer-body"><details><summary>${n(scopes(f).length)} product categories for this attribute</summary><p>${esc(scopes(f).join(', ')||'Not provided')}</p></details></div><div class="toolbar"><label class="search-field">${icon('search')}<input id="value-search" type="search" aria-label="Search values" placeholder="Search values"></label><select id="value-category-filter" aria-label="Filter values by product category">${categoryOptions(scopes(f),valueCategory,'All product categories')}</select></div><div id="value-content">${facetValuesTable(f)}</div>`,'MODEL ATTRIBUTE');
  }
  function updateValues(){const f=facetByKey.get(activeFacet);if(f){$('#value-content').innerHTML=facetValuesTable(f);announce(`${filteredValues(f).length} values`);}}
  function sources(){return `<section class="panel"><div class="panel-heading"><div><h2>${schemaOnly?'Corpus sources':'Observed channels'}</h2><small>${n(Object.keys(D.channels).length)} sources · ${n(D.summary.demand_records)} texts</small></div><span class="badge">Imported sample</span></div><div class="source-row ${schemaOnly?'schema-source-row':''} muted"><span>Source</span><span class="num">${schemaOnly?'Queries':'Rows'}</span>${schemaOnly?'':'<span class="num">Requests</span>'}</div>${Object.entries(D.channels).sort(([,a],[,b])=>schemaOnly?b.records-a.records:b.events-a.events).map(([s,c])=>`<div class="source-row ${schemaOnly?'schema-source-row':''}"><div class="source-name"><span class="channel-symbol">${icon(channelIcon(s))}</span><div><button class="text-button" data-source-link="${esc(s)}">${esc(channel(s))}</button><small class="item-subtitle">${esc(s)}</small></div></div><span class="num">${n(c.records)}</span>${schemaOnly?'':`<span class="num">${n(c.events)}</span>`}</div>`).join('')||empty('No sources available')}<div class="placeholder-note">${schemaOnly?'Sampled queries; observation period and actual frequency unknown.':unknownPeriod?'Observation period unknown.':'Volumes observed over the selected period. No live connection is assumed.'}</div>${provenance()}</section>`;}
  function runs(){return `<section class="panel"><div class="panel-heading"><div><h2>Saved runs</h2><small>Opening a result does not rerun any computation.</small></div></div>${D.jobs.length?`<div class="table-wrap"><table class="run-table" aria-label="Saved runs"><thead><tr><th>Run</th>${schemaOnly?'':'<th>Created</th>'}<th>Processing status</th><th></th></tr></thead><tbody>${D.jobs.map(j=>`<tr class="run-row ${j.id===D.id?'run-current':''}"><td><a href="/jobs/${encodeURIComponent(j.id)}#overview">${esc(j.id)}</a>${j.id===D.id?'<span class="item-subtitle">Current result</span>':''}</td>${schemaOnly?'':`<td class="muted">${j.created?esc(new Date(j.created*1000).toLocaleString('en-GB')):'—'}</td>`}<td><span class="badge ${j.status==='completed'?'complete':j.status==='failed'?'failed':''}">${esc(({completed:'Completed',failed:'Failed',queued:'Queued',running:'Running'})[j.status]||j.status)}</span></td><td><a class="icon-button" href="/jobs/${encodeURIComponent(j.id)}#overview" aria-label="Open ${esc(j.id)}">${icon('chevron')}</a></td></tr>`).join('')}</tbody></table></div>`:empty('No saved runs')}</section>`;}
  function render(){
    const [title,description]=pages[page];
    $('#page-title').textContent=title;$('#breadcrumb').textContent=title;$('#page-description').textContent=description;
    $('#eyebrow').textContent=schemaOnly?'QUERIES & DATA MODEL':page==='model'?'KNOWLEDGE REFERENCE':page==='runs'?'TRACEABILITY':'DEMAND & PRODUCT KNOWLEDGE';
    document.querySelectorAll('#navigation a').forEach(a=>{if(a.hash===`#${page}`)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
    $('#content').innerHTML=({overview,opportunities,demands,model:modelView,sources,runs})[page]();
    $('#export').hidden=page==='runs';
  }
  function updateTable(){
    pageIndex=0;
    if(page==='opportunities'&&productMode){const items=filteredProducts();$('#table-content').innerHTML=productTable(items.slice(0,PAGE_SIZE),items.length);announce(`${items.length} ${recommendationMode==='covered'?'already covered criteria':recommendationMode==='uncertain'?'requests to clarify':'recommendations'}`);return;}
    if(page==='opportunities'){const items=filteredCandidates();$('#table-content').innerHTML=opportunityTable(items.slice(0,PAGE_SIZE),false,items.length);announce(`${items.length} opportunities`);}
    if(page==='demands'){const items=filteredDemands();$('#table-content').innerHTML=demandTable(items.slice(0,PAGE_SIZE),items.length);announce(`${items.length} requests`);}
    if(page==='model'){const items=filteredAttributes();$('#table-content').innerHTML=attributeTable(items.slice(0,PAGE_SIZE),items.length);announce(`${items.length} attributes`);}
  }
  function quoted(r,p){
    const text=r?.text;
    if(!r?.excerpt_only&&typeof text==='string'&&Number.isInteger(p.start)&&Number.isInteger(p.end)&&Array.from(text).slice(p.start,p.end).join('')===p.quote){const chars=Array.from(text);return esc(chars.slice(0,p.start).join(''))+'<mark>'+esc(p.quote)+'</mark>'+esc(chars.slice(p.end).join(''));}
    return esc((!r?.excerpt_only&&text)||p.quote||text||'Quotation unavailable');
  }
  function proofCard(p){const r=demandById.get(p.record_id);if(productMode)return `<article class="evidence-card compact-proof"><blockquote>${quoted(r,p)}</blockquote><button class="text-button" data-demand="${esc(p.record_id)}">View request ${icon('chevron')}</button><details><summary>Source</summary><p class="mono">${esc(p.record_id)} · ${esc(channel(p.source))}${Number.isInteger(p.start)?` · [${p.start}, ${p.end})`:''}</p></details></article>`;return `<article class="evidence-card"><div class="evidence-meta"><span>${icon(channelIcon(p.source))}${esc(channel(p.source))}</span><span>${schemaOnly?esc(r?demandCategory(r):'Category not provided'):`${n(p.count||1)} request${(p.count||1)!==1?'s':''}`}</span></div><blockquote>${quoted(r,p)}</blockquote>${p.interpretation?`<p class="evidence-note"><strong>Proposed interpretation:</strong> ${esc(p.interpretation)}</p>`:''}${p.rationale?`<p class="evidence-note"><strong>Rationale:</strong> ${esc(p.rationale)}</p>`:''}<footer><span>${esc(p.record_id)}${r?.excerpt_only?' · excerpt only':''}</span><span>${!schemaOnly&&!unknownPeriod&&r?.date?esc(r.date)+' · ':''}${Number.isInteger(p.start)?`[${p.start}, ${p.end})`:''}</span></footer></article>`;}
  function inspectorOpen(html,kind=schemaOnly?'TO REVIEW':'OPPORTUNITY'){$('#inspector-content').innerHTML=html;$('#inspector-kind').textContent=kind;if(!$('#inspector').open){lastFocus=document.activeElement;$('#inspector').showModal();}$('#inspector').scrollTop=0;}
  function detailBody(c){
    const gap=(c.value_status==='not_observed_semantic'?{...gaps.value_gap,diagnosis:'The review proposes no observed value matching the need; this conclusion still needs confirmation.'}:gaps[c.gap_type])||{diagnosis:'Diagnosis not provided.',next:'Review the request.'};
    const proofs=c.demand_records||[];
    if(detailTab==='evidence')return `<h3>${n(countRecords(c))} source texts</h3>${proofs.map(proofCard).join('')||empty('No quotation available')}`;
    if(schemaOnly){
      const facet=facetByKey.get(c.fact_key||c.key);
      const modelReference=(facet?`<button class="text-button" data-facet="${esc(facet.key)}">View ${n((facet.values||[]).length)} observed values for ${esc(facet.label||facet.key)}</button>`:'')+(c.matched_value!=null?`<p>Model value: ${esc(c.matched_value)}</p>`:'')+(c.category_refs?.length?`<p>Existing categories: ${scopeSummary(c.category_refs)}</p>`:'');
      const valueDetail=c.requested_value!=null?`<div class="comparison-box"><div><small>REQUESTED VALUE</small><strong>${esc(c.requested_value)}</strong><p>${esc(valueStatus(c.value_status))} · ${semanticReview?'agent-proposed interpretation':'exact comparison only'}.</p></div><div><small>RECONSTRUCTED MODEL</small>${modelReference||'<p>No reference established for this criterion.</p>'}</div></div>${c.value_evidence?proofCard(c.value_evidence):''}`:'';
      if(detailTab==='definition')return `<dl class="fact-contract"><dt>Identifier</dt><dd class="mono">${esc(c.key)}</dd><dt>Attribute</dt><dd>${esc(c.fact_key||'Needs clarification')}</dd><dt>Definition</dt><dd>${esc(c.definition||'To define')}</dd><dt>Detection</dt><dd>${esc(analysisLabel)}. Conclusions still need confirmation.</dd><dt>Model</dt><dd>${esc(modelVersion)}</dd></dl>${valueDetail}`;
      return `<div class="diagnosis"><h3>${esc(gap.diagnosis)}</h3><p>${esc(gap.next)}</p></div><p>${esc(lexicalDescription)}</p>${valueDetail}<h3>In customers’ words</h3>${proofs.slice(0,2).map(proofCard).join('')||empty('No quotation available')}<button class="text-button" data-detail-tab="evidence">All source queries (${n(countRecords(c))})</button>`;
    }
    if(detailTab==='definition')return `<dl class="fact-contract"><dt>Identifier</dt><dd class="mono">${esc(c.key)}</dd><dt>Definition</dt><dd>${esc(c.definition||'To define')}</dd><dt>Expressions</dt><dd>${values(c.aliases)}</dd><dt>Detection</dt><dd>${esc(({configured_phrase:'Configured phrase',supplied_grounded_intent:'Annotation with quotation',explicit_attribute_request:'Explicit attribute request',unresolved:'Intent to clarify'})[c.detection]||c.detection||'Not provided')}</dd><dt>Model</dt><dd>${esc(D.model.version||'Unversioned')}</dd></dl><details><summary>View need data</summary><pre>${esc(JSON.stringify(c,null,2))}</pre></details>`;
    return `<div class="diagnosis"><h3>${esc(gap.diagnosis)}</h3><p>${esc(gap.next)}</p></div><div class="comparison-box"><div><small>OBSERVED DEMAND</small><strong>${esc(c.label)}</strong><p>${n(c.demand_events)} events across ${n(uniqueSources(c).length)} channels.</p></div><div><small>CURRENT BUSINESS MODEL</small><strong>${c.gap_type==='schema_gap'?'No matching attribute':c.gap_type==='unresolved_intent'?'Intent not established':esc(c.key)}</strong><p>${c.gap_type==='schema_gap'?'The request remains visible even without product evidence.':c.gap_type==='unresolved_intent'?'No match is asserted.':`${n(c.known_assignment_count)} / ${n(D.summary.inventory_products)} products populated in the input model.`}</p></div></div><div class="title-actions" style="margin:26px 0 14px"><h3>In customers’ words</h3><button class="text-button" data-detail-tab="evidence">View all (${n(countRecords(c))})</button></div>${proofs.slice(0,2).map(proofCard).join('')||empty('No quotation available')}`;
  }
  function openCandidate(key,tabName='diagnostic'){
    if(productMode){const item=[...productItemById.values()].find(i=>i.candidate_keys.includes(key));if(item)return openProductItem(item.id);}
    const c=candidateByKey.get(key);if(!c)return;
    activeCandidate=key;activeFacet=null;detailTab=tabName;
    inspectorOpen(`<div class="drawer-heading">${badge(c.gap_type)}<h2 id="inspector-title">${esc(candidateTitle(c))}</h2><span class="mono muted">${esc(c.key)}</span><p>${esc(c.definition||'Definition to clarify from the request.')}</p><div class="drawer-stats"><div><strong class="num">${n(volume(c))}</strong><small>${schemaOnly?'corpus queries':'requests'}</small></div><div><strong class="num">${n(countRecords(c))}</strong><small>texts</small></div><div><strong class="num">${n(uniqueSources(c).length)}</strong><small>sources</small></div></div></div><div class="drawer-tabs" aria-label="Opportunity details">${[['diagnostic','Diagnosis'],['evidence','Source requests'],['definition','Definition']].map(([key,label])=>`<button data-detail-tab="${key}" class="${detailTab===key?'active':''}" aria-pressed="${detailTab===key}">${label}</button>`).join('')}</div><div class="drawer-body">${detailBody(c)}</div>`);
  }
  function representedDetail(p){
    const facet=facetByKey.get(p.fact_key);
    return `<section class="method-section"><h3>${esc(p.label||p.fact_key||'Represented criterion')}</h3><p>${esc(p.rationale||'')}</p>${facet?`<p>Model attribute: <button class="text-button" data-facet="${esc(facet.key)}">${esc(facet.label||facet.key)}</button></p>`:''}${p.matched_value!=null?`<p>Model value: ${esc(p.matched_value)}</p>`:''}${p.category_refs?.length?`<p>Model categories: ${scopeSummary(p.category_refs)}</p>`:''}${p.evidence?proofCard(p.evidence):''}</section>`;
  }
  function openDemand(id){const r=demandById.get(id);if(!r)return;if(productMode)return openProductDemand(r);activeCandidate=null;activeFacet=null;inspectorOpen(`<div class="drawer-heading"><h2 id="inspector-title">${schemaOnly?'Corpus query':'Source request'}</h2><span class="mono muted">${esc(r.id)}</span><p>Query category: ${esc(demandCategory(r))}</p></div><div class="drawer-body">${proofCard({record_id:r.id,source:r.source,quote:r.text,count:r.count})}<h3>${schemaOnly?'Candidate matches':'Related needs'}</h3>${demandTags(r)}${semanticReview?representedMatches(r).map(representedDetail).join(''):''}${schemaOnly?`<p>${esc(lexicalDescription)}</p>`:''}${schemaOnly?representedMatches(r).filter(p=>p.value_evidence).map(p=>`<h3>${esc(valueStatus(p.value_status))}</h3>${proofCard(p.value_evidence)}`).join(''):''}</div>`,'CUSTOMER REQUEST');}
  function methodology(){
    activeCandidate=null;activeFacet=null;
    if(schemaOnly){inspectorOpen(`<div class="drawer-heading"><h2 id="inspector-title">Method & counting</h2></div><div class="drawer-body"><section class="method-section"><h3>Corpus queries</h3><p>Each row counts once. The count field is a sampling weight, not an actual frequency or a customer event count. Observation period unknown. A query can contribute to several candidates; their counts cannot be added together.</p></section><section class="method-section"><h3>Reconstructed model and observed values</h3><p>${esc(schemaDescription)} Observed values are not exhaustive and are not canonical lists of allowed values.</p></section><section class="method-section"><h3>${esc(analysisLabel)}</h3>${semanticReview?`<p>${n(D.analysis.reviewed_records)} queries · ${n(D.analysis.reviewed_criteria)} criteria reviewed. Imported agent decisions${D.analysis.independent_audit===false?' · no independent audit':''}.</p>`:''}<p>${esc(lexicalDescription)} An exact value match does not validate the other query constraints. An unobserved value needs confirmation; values that were not decoded remain unassessed or need clarification.</p></section><section class="method-section"><h3>Distinct categories</h3><p>query_class describes queries and product_class describes model product categories. These taxonomies differ; this view asserts no automatic equivalence.</p></section><section class="method-section"><h3>Read-only preview</h3><p>The comparison covers queries and the data model with its observed values, without product instances. No remote calls or model changes are made.</p></section></div>`,'METHODOLOGY');return;}
    inspectorOpen(`<div class="drawer-heading"><h2 id="inspector-title">Method & counting</h2></div><div class="drawer-body"><section class="method-section"><h3>Requests ≠ unique customers</h3><p>The total counts each record's volume once. A request can contribute to several opportunities, so volumes per need cannot be added together.</p></section><section class="method-section"><h3>The input model is the reference</h3><p>Attributes and assignments are from the start of the Benchmark. Values extracted or proposed later do not change this coverage measure.</p></section><section class="method-section"><h3>Priority by observed volume</h3><p>Ranking uses request counts, without invented revenue or impact scores. Opportunities are diagnoses to review, not ontology validations.</p></section><section class="method-section"><h3>Detection method</h3><p>${esc(D.metrics.detector||'No method provided for this result.')}</p><p>Configured phrase detection does not measure comprehensive semantic understanding. Unrecognised intents still need clarification.</p></section>${D.synthetic?'<section class="method-section"><h3>Synthetic data</h3><p>This dataset illustrates how the tool works. It does not establish accuracy on your real data.</p></section>':''}</div>`,'METHODOLOGY');
  }
  function download(){
    let data,name,type;
    if(page==='model'){data=JSON.stringify(D.model,null,2);name='pilon-benchmark-model.json';type='application/json';}
    else {
      const csvCell=v=>{let s=String(v??'');if(/^(?:\s*[=+@\-]|[\t\r\n])/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};
      const rows=productMode&&['overview','opportunities'].includes(page)?[['criterion','category','values','requested_values','basis','source_query_count','source_query_ids','fact_key'],...(page==='opportunities'?filteredProducts():[...P.filters,...P.explore]).map(i=>[i.label,i.category_refs.join(' | '),i.values.map(valueText).join(' | '),(i.requested_values||i.values).map(valueText).join(' | '),i.basis,i.demand_count,i.record_ids.join(' | '),i.fact_key])]:schemaOnly?(page==='demands'?[['id','source','query_class','text','sampling_weight','lexical_candidates'],...filteredDemands().map(r=>[r.id,r.source,r.query_class,r.text,r.count??1,JSON.stringify(representedMatches(r))])]:page==='sources'?[['source','corpus_queries'],...Object.entries(D.channels).map(([s,c])=>[s,c.records])]:[['key','label','gap_type','corpus_queries','requested_value','value_status'],...(page==='opportunities'?filteredCandidates():candidates).map(c=>[c.key,candidateTitle(c),c.gap_type,countRecords(c),c.requested_value,c.value_status])]):page==='demands'?[['id','source','text','count'],...filteredDemands().map(r=>[r.id,r.source,r.text,r.count||1])]:page==='sources'?[['source','records','events'],...Object.entries(D.channels).map(([s,c])=>[s,c.records,c.events])]:[['key','label','gap_type','demand_events','source_records','known_assignment_count'],...(page==='opportunities'?filteredCandidates():candidates).map(c=>[c.key,candidateTitle(c),c.gap_type,c.demand_events,countRecords(c),c.known_assignment_count])];
      data='\uFEFF'+rows.map(row=>row.map(csvCell).join(';')).join('\r\n');name=`pilon-benchmark-${page}.csv`;type='text/csv;charset=utf-8';
    }
    const url=URL.createObjectURL(new Blob([data],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);announce('Export downloaded.');
  }
  function navigate(){
    const raw=location.hash.slice(1).split('?');const next=Object.hasOwn(pages,raw[0])?raw[0]:'overview';if(raw[0]==='main')return;if(!Object.hasOwn(pages,raw[0]))history.replaceState(null,'','#overview');
    if(page!==next){query='';sourceFilter='all';gapFilter='all';categoryFilter='all';pageIndex=0;}
    page=next;const params=new URLSearchParams(raw[1]||'');if(gaps[params.get('gap')])gapFilter=params.get('gap');if(Object.hasOwn(D.channels,params.get('source')))sourceFilter=params.get('source');
    if(params.has('q'))query=params.get('q');
    if(productMode&&page==='opportunities'){if(Object.hasOwn(productLabels,params.get('mode')))recommendationMode=params.get('mode');else if(params.has('gap'))recommendationMode=params.get('gap')==='unresolved_intent'?'uncertain':params.get('gap')==='filter_proposal'?'filters':'explore';}
    $('#inspector').close();render();window.scrollTo(0,0);
    if(page==='demands'&&demandById.has(params.get('record')))openDemand(params.get('record'));
  }
  document.addEventListener('click',e=>{
    const b=e.target.closest('button,[data-candidate]');if(!b)return;
    if(b.dataset.product)openProductItem(b.dataset.product);
    else if(b.dataset.recommendationMode){recommendationMode=b.dataset.recommendationMode;pageIndex=0;render();}
    else if(b.dataset.candidate)openCandidate(b.dataset.candidate);
    else if(b.dataset.facet)openFacet(b.dataset.facet);
    else if(b.dataset.valueStep){valuePageIndex+=Number(b.dataset.valueStep);updateValues();}
    else if(b.dataset.demand)openDemand(b.dataset.demand);
    else if(b.dataset.detailTab&&activeCandidate)openCandidate(activeCandidate,b.dataset.detailTab);
    else if(b.dataset.gap){gapFilter=b.dataset.gap;pageIndex=0;render();}
    else if(b.dataset.gapLink)location.hash=`opportunities?gap=${b.dataset.gapLink}`;
    else if(b.dataset.sourceLink)location.hash=`demands?source=${encodeURIComponent(b.dataset.sourceLink)}`;
    else if(b.dataset.pageStep){pageIndex+=Number(b.dataset.pageStep);render();}
  });
  document.addEventListener('input',e=>{if(e.target.id==='search'){query=e.target.value;updateTable();}if(e.target.id==='value-search'){valueQuery=e.target.value;valuePageIndex=0;updateValues();}});
  document.addEventListener('change',e=>{if(e.target.id==='source-filter'){sourceFilter=e.target.value;updateTable();}if(e.target.id==='category-filter'){categoryFilter=e.target.value;updateTable();}if(e.target.id==='sort'){sort=e.target.value;updateTable();}if(e.target.id==='value-category-filter'){valueCategory=e.target.value;valuePageIndex=0;updateValues();}});
  $('#export').addEventListener('click',download);
  $('#methodology').addEventListener('click',methodology);
  $('#close-inspector').addEventListener('click',()=>$('#inspector').close());
  $('#inspector').addEventListener('click',e=>{if(e.target===$('#inspector')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
  $('#inspector').addEventListener('close',()=>{activeCandidate=null;activeFacet=null;if(lastFocus?.isConnected)lastFocus.focus();});
  window.addEventListener('hashchange',navigate);navigate();
})();
