/* Local, dependency-free Benchmark interactions. No inference or remote request. */
(() => {
  'use strict';
  const D = JSON.parse(document.getElementById('benchmark-data').textContent);
  D.attributes ||= D.model.facets || [];
  const $ = s => document.querySelector(s);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const n = v => v == null ? '—' : new Intl.NumberFormat('fr-FR').format(v);
  const schemaOnly = D.model.assessment_scope === 'schema_only';
  const semanticReview = schemaOnly && D.analysis?.method === 'agent_semantic_review' && D.analysis?.status === 'reviewed';
  const analysisLabel = semanticReview ? 'Revue sémantique fournie' : 'Détecteur local lexical';
  const matchLabel = semanticReview ? 'rapprochement proposé par la revue' : 'correspondance lexicale candidate';
  const unknownPeriod = D.model.observation_period === 'unknown';
  const modelVersion = D.model.version || D.model.provenance?.version || 'Version non renseignée';
  const schemaDescription = 'Modèle reconstitué à partir des noms d’attributs et valeurs observées publiés dans WANDS ; ce n’est pas l’ontologie officielle de production de Wayfair.';
  const lexicalDescription = semanticReview
    ? 'Revue sémantique fournie : les rapprochements et propositions restent à confirmer. Une requête non interprétée ne prouve pas qu’un attribut manque ; la disponibilité des filtres n’est pas établie par le modèle.'
    : 'Détecteur local lexical : les rapprochements sont des correspondances candidates, sans validation de la requête complète. Une requête non qualifiée ne prouve pas qu’un attribut manque.';
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
    schema_gap:{label:'Attribut absent', plural:'Attributs absents',color:'#8c73db', diagnosis:'Ce besoin n’a pas d’attribut dans le modèle.',next:'Définir l’attribut et ses valeurs attendues. Sa disponibilité dans les sources produit reste à évaluer.'},
    coverage_gap:{label:'Couverture incomplète',plural:'Couverture incomplète',color:'#d6a251',diagnosis:'L’attribut existe, mais sa couverture produit est incomplète.',next:'Identifier les produits sans valeur dans le modèle. Une mention dans une source n’est pas encore une valeur intégrée.'},
    retrieval_gap:{label:'Recherche à corriger',plural:'Recherche à corriger',color:'#6a9dbf',diagnosis:'Le modèle couvre le besoin, mais la demande reste mal servie.',next:'Examiner les filtres, le classement et les résultats de recherche associés à cette demande.'},
    unresolved_intent:{label:'À qualifier',plural:'Besoins à qualifier',color:'#abb2c2',diagnosis:'La demande est conservée, mais son intention reste à préciser.',next:'Clarifier le besoin avant de proposer un attribut. Aucun fait n’est créé à partir de cette seule ambiguïté.'}
  };
  if(schemaOnly){
    delete gaps.coverage_gap;
    delete gaps.retrieval_gap;
    gaps.unresolved_intent = {...gaps.unresolved_intent,label:'Non interprétée',plural:'Requêtes non interprétées',diagnosis:'Cette requête n’a pas été interprétée par le détecteur lexical.',next:'Elle reste dans la file de qualification ; aucun manque d’attribut ou de valeur n’est établi.'};
    gaps.schema_gap = {...gaps.schema_gap, label:'Attribut à examiner', plural:'Attributs à examiner', diagnosis:'Un attribut candidat est signalé hors du schéma reconstitué.', next:'Examiner la requête et les noms d’attributs publiés avant de conclure à un manque du modèle.'};
    gaps.value_gap = {label:'Valeur non observée · à confirmer', plural:'Valeurs à confirmer',color:'#c49057',diagnosis:'La valeur demandée n’a pas de correspondance exacte dans les valeurs observées.',next:'Les valeurs publiées ne sont pas exhaustives. Vérifier les variantes et le sens de la demande avant de conclure à une valeur manquante.'};
    gaps.filter_proposal = {label:'Filtre à proposer',plural:'Filtres à proposer',color:'#599b90',diagnosis:'Les données sont représentées ; une capacité de filtrage est proposée.',next:'La disponibilité du filtre dans le service réel est inconnue. Cette proposition n’établit pas qu’un filtre manque.'};
    if(semanticReview) gaps.unresolved_intent.diagnosis = 'Cette requête reste non interprétée dans la revue fournie.';
  }
  const channels = {site_search:['Recherche sur le site','search'],support_chat:['Conversations support','demands'],store_review:['Avis clients','star'],feedback_form:['Formulaires clients','sources']};
  const channel = name => channels[name]?.[0] || name || 'Source non renseignée';
  const channelIcon = name => channels[name]?.[1] || 'sources';
  const badge = gap => `<span class="badge ${gaps[gap] ? gap : ''}">${esc(gaps[gap]?.label || gap || 'À vérifier')}</span>`;
  const pages = {
    overview:['Vue d’ensemble','Les écarts entre la demande et votre modèle métier.','overview'],
    opportunities:['Opportunités','Les besoins à traiter, classés par demande observée.','opportunities'],
    demands:['Demandes clients','Les formulations originales et les besoins associés.','demands'],
    model:['Modèle métier','Le référentiel utilisé pour ce Benchmark.','model'],
    sources:['Sources','Les canaux de demande présents dans cet échantillon.','sources'],
    runs:['Historique','Retrouvez les résultats de chaque exécution.','history']
  };
  if(schemaOnly){
    pages.overview[1] = 'Requêtes clients du corpus WANDS comparées au schéma reconstitué.';
    pages.opportunities = ['À examiner',semanticReview?'Propositions issues de la revue sémantique et requêtes restant à qualifier.':'File de qualification : requêtes non interprétées et pistes lexicales à confirmer.','opportunities'];
    pages.demands[1] = 'Requêtes intégrales et catégories du corpus ; fréquence réelle inconnue.';
    pages.model = ['Modèle de données','Attributs, valeurs observées et catégories produit du modèle reconstitué.','model'];
    pages.sources[1] = 'Provenance du corpus de requêtes échantillonnées.';
    pages.runs = ['Exécutions','Résultats enregistrés pour cet aperçu en lecture seule.','history'];
  }
  let page = 'overview', query = '', gapFilter = 'all', sourceFilter = 'all', categoryFilter = 'all', sort = 'volume', pageIndex = 0;
  let activeCandidate = null, detailTab = 'diagnostic', lastFocus = null;
  let activeFacet = null, valueQuery = '', valueCategory = 'all', valuePageIndex = 0;
  const PAGE_SIZE = 25;
  const ready = D.ready;
  const candidates = D.candidates.filter(c => !schemaOnly || !['coverage_gap','retrieval_gap'].includes(c.gap_type));
  const candidateByKey = new Map(candidates.map(c => [c.key,c]));
  const demandById = new Map(D.demands.map(r => [r.id,r]));
  const uniqueSources = c => [...new Set((c.demand_records || []).map(p => p.source))];
  const countRecords = c => new Set((c.demand_records || []).map(p => p.record_id)).size;
  const volume = c => schemaOnly ? countRecords(c) : c.demand_events || 0;
  const maxVolume = Math.max(1,...candidates.map(volume));
  const candidateTitle = c => c.gap_type === 'unresolved_intent'
    ? (c.demand_records || []).map(p => demandById.get(p.record_id)?.text || p.quote).find(Boolean) || c.label || c.key
    : c.gap_type === 'value_gap' || (semanticReview && c.requested_value!=null) ? `${c.label||c.fact_key} : ${c.requested_value??'valeur à préciser'}` : c.label || c.key;
  const demandCategory = r => r.query_class || (schemaOnly ? 'Non renseignée' : r.category || D.model.category || 'Non renseignée');
  const scopes = f => Array.isArray(f.scopes) ? f.scopes : [];
  const facetByKey = new Map(D.attributes.map(f => [f.key,f]));
  const modelValueCount = D.attributes.reduce((total,f) => total+(f.values || []).length,0);
  const valueText = value => typeof value === 'object' ? JSON.stringify(value) : String(value);
  const valueScopes = (f,value) => Object.hasOwn(f.value_scopes || {},valueText(value)) ? f.value_scopes[valueText(value)] : [];
  const gapCount = key => candidates.filter(c => c.gap_type === key).length;
  const representedMatches = r => (r.represented || []).filter(p => !schemaOnly || p.status === 'schema_represented');
  const representedCount = D.demands.filter(r => representedMatches(r).length).length;
  const uninterpretedCount = D.demands.filter(r => r.matches.some(p=>candidateByKey.get(p.candidate_key)?.gap_type==='unresolved_intent') || (!r.matches.length&&!representedMatches(r).length)).length;
  const reviewLabel = schemaOnly ? 'éléments à examiner' : 'opportunités';
  const stateLabel = D.status === 'failed' ? 'Échec' : ready ? (schemaOnly?(semanticReview?`Revue sémantique fournie · ${n(D.analysis.reviewed_records)} requêtes revues`:'Données importées · analyse sémantique non effectuée'):'Benchmark disponible') : D.status === 'empty' ? 'Aucune exécution' : 'En attente de résultat';
  const statusClass = D.status === 'failed' ? 'failed' : ready && !schemaOnly ? 'complete' : '';
  $('#navigation').innerHTML = Object.entries(pages).filter(([k]) => k !== 'runs').map(([key,[label,,ico]],i) => `${i===3?'<div class="nav-separator"></div>':''}<a href="#${key}" title="${label}">${icon(ico)}<span class="nav-text">${label}</span>${key==='opportunities'?`<span class="nav-count">${n(candidates.length)}</span>`:''}</a>`).join('');
  document.querySelectorAll('[data-icon]').forEach(el => el.innerHTML = icon(el.dataset.icon));
  $('#workspace-name').textContent = D.model.category || (schemaOnly ? 'WANDS' : 'Espace local');
  $('#snapshot-state').textContent = stateLabel;
  $('#snapshot-state').className = `badge ${statusClass}`;
  $('#demo-label').textContent = D.synthetic ? 'DÉMO' : '';
  $('#demo-banner').hidden = !D.synthetic;
  $('#category').innerHTML = `${icon('box')}${esc(D.model.category || (schemaOnly ? 'WANDS' : 'Catégorie non renseignée'))}${schemaOnly?' · Schéma uniquement':''}`;
  const date = value => value ? new Date(`${value}T12:00:00`).toLocaleDateString('fr-FR',{day:'numeric',month:'short',year:'numeric'}) : '—';
  $('#period').innerHTML = unknownPeriod || schemaOnly ? 'Période d’observation inconnue' : `${icon('calendar')}${esc(date(D.model.window_start))} – ${esc(date(D.model.window_end))}`;
  $('#footer-context').textContent = `${modelVersion} · ${D.complete_inputs?'Corpus fourni':'Extraits disponibles'} · Lecture seule`;
  $('#scope-notice').hidden = !schemaOnly;
  $('#scope-notice').textContent = semanticReview
    ? 'Aperçu en lecture seule · modèle WANDS reconstitué, non officiel. Revue sémantique fournie ; propositions à confirmer, capacités de filtrage inconnues.'
    : 'Aperçu local en lecture seule · modèle WANDS reconstitué, non officiel. Détection lexicale : correspondances candidates, sans validation des requêtes complètes. Non qualifiée ≠ attribut manquant.';
  if(schemaOnly) document.querySelectorAll('a[href="#runs"]').forEach(a => {a.setAttribute('aria-label','Voir les exécutions');a.title='Exécutions';if(a.classList.contains('history-link'))a.innerHTML=`${icon('history')} Exécutions`;});
  function empty(title,description='') { return `<div class="empty">${icon('search')}<h2>${esc(title)}</h2><p>${esc(description)}</p></div>`; }
  function announce(text) { $('#announcement').textContent = text; }
  function metric(label,value,caption,ico,accent=false) { return `<div class="metric"><div class="metric-label">${label}${icon(ico)}</div><strong class="num">${n(value)}</strong><small class="${accent?'accent':''}">${caption}</small></div>`; }
  function notice() {
    if(D.status==='failed') return `<div class="state-notice failed">Exécution interrompue. Les résultats disponibles sont partiels.${D.error?`<details><summary>Voir l’erreur</summary><pre>${esc(D.error)}</pre></details>`:''}</div>`;
    return ready ? '' : `<div class="state-notice">${D.status==='empty'?'Aucun Benchmark disponible.':'Le Benchmark n’a pas encore produit de résultat.'}</div>`;
  }
  function channelSymbols(c) { return `<span class="channel-list">${uniqueSources(c).map(s=>`<span class="channel-symbol" title="${esc(channel(s))}" aria-label="${esc(channel(s))}">${icon(channelIcon(s))}</span>`).join('')}</span>`; }
  function coverage(c) {
    if(c.gap_type==='schema_gap') return '<span class="muted">Attribut absent</span>';
    if(c.gap_type==='unresolved_intent') return '<span class="muted">Non évaluée</span>';
    return `<span class="num">${n(c.known_assignment_count)} <span class="muted">/ ${n(D.summary.inventory_products)} produits</span></span>`;
  }
  function opportunityTable(items,compact=false,total=items.length) {
    if(!items.length) return empty(schemaOnly?'Aucun élément à examiner':'Aucune opportunité affichée',query||gapFilter!=='all'?'Modifiez la recherche ou les filtres.':ready?(schemaOnly?'Aucune piste lexicale signalée ; les requêtes ne sont pas validées pour autant.':'Aucun écart détecté dans ce résultat.'):'Les résultats apparaîtront après le Benchmark.');
    return `<div class="table-wrap"><table class="opportunity-table" aria-label="Opportunités de connaissance"><thead><tr><th>Besoin client</th><th>${schemaOnly?'Qualification':'Diagnostic'}</th><th>${schemaOnly?'Requêtes':'Demandes'}</th><th class="channel-col">${schemaOnly?'Sources':'Canaux'}</th>${schemaOnly?'':'<th class="coverage-col">Modèle actuel</th>'}<th class="open-col"><span class="sr-only">Détail</span></th></tr></thead><tbody>${items.map(c=>`<tr><td><button class="item-title" data-candidate="${esc(c.key)}">${esc(candidateTitle(c))}</button><span class="item-subtitle">${n(countRecords(c))} texte${countRecords(c)>1?'s':''} source${countRecords(c)>1?'s':''}</span></td><td>${badge(c.gap_type)}</td><td><span class="cell-metric"><b class="num">${n(volume(c))}</b><span class="mini-track"><i style="width:${Math.min(100,100*volume(c)/maxVolume)}%"></i></span></span></td><td class="channel-col">${channelSymbols(c)}</td>${schemaOnly?'':`<td class="coverage-col">${coverage(c)}</td>`}<td class="open-col"><button class="icon-button" data-candidate="${esc(c.key)}" aria-label="Examiner ${esc(candidateTitle(c))}">${icon('chevron')}</button></td></tr>`).join('')}</tbody></table></div><div class="table-bottom"><span>${compact?`${n(items.length)} ${reviewLabel} · ${schemaOnly?'requêtes du corpus':'priorité par volume'}`:`${n(total)} ${reviewLabel}`}</span>${compact?'<a href="#opportunities" class="text-button">Tout explorer</a>':pager(total)}</div>`;
  }
  function overview() {
    const s=D.summary;
    let start=0; const slices=Object.entries(gaps).map(([key,g])=>{let end=start+(gapCount(key)/Math.max(1,candidates.length))*100;const out=`${g.color} ${start}% ${end}%`;start=end;return out;}).join(',');
    const metrics = schemaOnly
      ? metric('Requêtes du corpus',D.complete_inputs?s.demand_records:null,D.complete_inputs?'Échantillon · fréquence réelle inconnue':`${n(s.demand_records)} références disponibles · corpus incomplet`,'demands')+metric('Requêtes rapprochées',ready?representedCount:null,semanticReview?'Rapprochements proposés par la revue':'Correspondances lexicales candidates','search')+metric('Requêtes non interprétées',ready?uninterpretedCount:null,'File de qualification · aucun manque établi','opportunities')+metric('Attributs publiés',s.attributes,`${n(modelValueCount)} paires attribut–valeur observées`,'model')
      : metric('Demandes observées',D.complete_inputs?s.demand_events:null,`${n(s.demand_records)} textes sources`,'demands')+metric('Opportunités',ready?s.opportunity_count:null,'Besoins non entièrement couverts','opportunities')+metric('Attributs à envisager',ready?s.schema_gaps:null,'Absents du modèle actuel','model',true)+metric('Attributs existants',s.attributes,`${n(s.inventory_products)} produits dans le périmètre`,'box');
    return `${notice()}<div class="metrics">${metrics}</div>
    <div class="overview-grid"><section class="panel"><div class="panel-heading"><div><h2>Ce que les clients demandent</h2><small>${schemaOnly?'Les 5 premières requêtes à examiner':'Les 5 premiers besoins · événements observés'}</small></div></div><div class="panel-body">${candidates.length?candidates.slice(0,5).map(c=>`<button class="rank-row" data-candidate="${esc(c.key)}" title="Examiner ${esc(candidateTitle(c))}"><span class="rank-label">${esc(candidateTitle(c))}</span><span class="bar-track"><span class="bar-fill" style="display:block;width:${100*volume(c)/maxVolume}%"></span></span><strong class="num">${n(volume(c))}</strong></button>`).join(''):empty('Aucun besoin disponible')}</div></section>
    <section class="panel"><div class="panel-heading"><div><h2>${schemaOnly?'Pistes à examiner':'Où sont les écarts ?'}</h2><small>${schemaOnly?'File de qualification':'Répartition des opportunités'}</small></div></div><div class="panel-body"><div class="gap-chart"><div class="donut" style="background:${candidates.length?`conic-gradient(${slices})`:'#f0f1f6'}" role="img" aria-label="${n(candidates.length)} ${reviewLabel}"><div class="donut-center">${ready?n(candidates.length):'—'}<small>${schemaOnly?'à examiner':'opportunités'}</small></div></div><div class="legend">${Object.entries(gaps).map(([key,g])=>`<button data-gap-link="${key}"><i class="swatch ${key}"></i>${g.plural}<strong>${ready?n(gapCount(key)):'—'}</strong></button>`).join('')}</div></div></div></section></div>
    <section class="panel"><div class="panel-heading"><div><h2>${schemaOnly?'Requêtes à examiner':'Opportunités à explorer'}</h2><small>${schemaOnly?'Des requêtes à qualifier ; les manques restent à confirmer.':'De la demande client au manque identifié.'}</small></div><a class="text-button" href="#opportunities">Voir tout</a></div>${opportunityTable(candidates.slice(0,5),true)}</section>`;
  }
  function filteredCandidates() {
    const q=query.toLocaleLowerCase();
    return candidates.filter(c=>(gapFilter==='all'||c.gap_type===gapFilter)&&(sourceFilter==='all'||uniqueSources(c).includes(sourceFilter))&&[candidateTitle(c),c.key,c.definition,...(c.demand_records||[]).map(p=>demandById.get(p.record_id)?.text||p.quote)].join(' ').toLocaleLowerCase().includes(q)).sort((a,b)=>sort==='name'?String(candidateTitle(a)).localeCompare(String(candidateTitle(b))):sort==='sources'?uniqueSources(b).length-uniqueSources(a).length:volume(b)-volume(a));
  }
  function sourceOptions() {return `<option value="all">${schemaOnly?'Toutes les sources':'Tous les canaux'}</option>${Object.keys(D.channels).map(s=>`<option value="${esc(s)}" ${sourceFilter===s?'selected':''}>${esc(channel(s))}</option>`).join('')}`;}
  function categoryOptions(items,selected=categoryFilter,label='Toutes les catégories') {
    return `<option value="all">${esc(label)}</option>${[...new Set(items)].sort((a,b)=>a.localeCompare(b)).map(value=>`<option value="${esc(value)}" ${selected===value?'selected':''}>${esc(value)}</option>`).join('')}`;
  }
  function searchBox(placeholder) {return `<label class="search-field">${icon('search')}<input id="search" type="search" aria-label="${esc(placeholder)}" placeholder="${esc(placeholder)}" value="${esc(query)}"></label>`;}
  function pager(total) {return total>PAGE_SIZE?`<span class="pagination"><button data-page-step="-1" aria-label="Page précédente" ${pageIndex===0?'disabled':''}>${icon('back')}</button>${pageIndex+1} / ${Math.ceil(total/PAGE_SIZE)}<button data-page-step="1" aria-label="Page suivante" ${(pageIndex+1)*PAGE_SIZE>=total?'disabled':''}>${icon('chevron')}</button></span>`:'';}
  function opportunities() {
    const items=filteredCandidates();
    return `${notice()}<div class="filter-tabs" aria-label="Diagnostics"><button data-gap="all" class="${gapFilter==='all'?'active':''}" aria-pressed="${gapFilter==='all'}">Tous<span>${n(candidates.length)}</span></button>${Object.entries(gaps).map(([key,g])=>`<button data-gap="${key}" class="${gapFilter===key?'active':''}" aria-pressed="${gapFilter===key}">${g.plural}<span>${n(gapCount(key))}</span></button>`).join('')}</div><section class="panel"><div class="toolbar">${searchBox('Rechercher un besoin ou une citation')}<select id="source-filter" aria-label="Filtrer par source">${sourceOptions()}</select><select id="sort" aria-label="Trier les opportunités"><option value="volume" ${sort==='volume'?'selected':''}>${schemaOnly?'Nombre de requêtes du corpus':'Demande décroissante'}</option><option value="name" ${sort==='name'?'selected':''}>Nom du besoin</option><option value="sources" ${sort==='sources'?'selected':''}>Nombre de sources</option></select></div><div id="table-content">${opportunityTable(items.slice(pageIndex*PAGE_SIZE,(pageIndex+1)*PAGE_SIZE),false,items.length)}</div></section>`;
  }
  function filteredDemands(){const q=query.toLocaleLowerCase();return D.demands.filter(r=>(sourceFilter==='all'||r.source===sourceFilter)&&(categoryFilter==='all'||demandCategory(r)===categoryFilter)&&[r.text,r.id,demandCategory(r),...r.matches.map(m=>m.candidate_key),...representedMatches(r).flatMap(m=>[m.fact_key,m.label])].join(' ').toLocaleLowerCase().includes(q)).sort((a,b)=>schemaOnly?0:(b.count||1)-(a.count||1));}
  function valueStatus(status){return ({observed_exact:'Valeur observée · correspondance exacte',observed_semantic:'Valeur observée · rapprochement sémantique proposé',represented_by_category:'Représenté par une catégorie du modèle',attribute_represented:'Attribut représenté dans le modèle',not_observed_exact:'Valeur non observée · à confirmer',not_observed_semantic:'Valeur non observée selon la revue · à confirmer',not_assessed:'Valeur non évaluée',unresolved:'Valeur à qualifier'})[status]||'Valeur non évaluée';}
  function demandTags(r){
    const matched = r.matches.map(p=>candidateByKey.get(p.candidate_key)).filter(Boolean);
    const links = matched.map(c=>`<button class="tag tag-button" data-candidate="${esc(c.key)}">${esc(c.gap_type==='unresolved_intent'?(schemaOnly?'Non interprétée':'À qualifier'):candidateTitle(c))}</button>`).join('');
    const represented = representedMatches(r).map(p=>`<span class="tag schema-match">${esc(p.label||p.fact_key)} · ${schemaOnly?matchLabel:'déjà représenté'}${schemaOnly?`<span class="item-subtitle">${esc(valueStatus(p.value_status))}${p.requested_value!=null?` : ${esc(p.requested_value)}`:''}</span>`:''}</span>`).join('');
    const qualification = schemaOnly ? (represented?'<p class="match-note">Requête complète non validée.</p>':!matched.length?'<span class="muted">À qualifier · aucune conclusion sur un attribut manquant</span>':'') : '';
    return `<div class="tags">${links}${represented}${qualification||(!links&&!represented?'<span class="muted">Aucun écart rattaché</span>':'')}</div>`;
  }
  function demandTable(items,total) {
    return items.length?`<div class="table-wrap"><table class="demand-table" aria-label="Demandes sources"><thead><tr><th>${schemaOnly?'Requête originale':'Demande originale'}</th><th>Catégorie</th><th>Source</th>${schemaOnly?'':'<th>Volume</th>'}${schemaOnly||unknownPeriod?'':'<th class="date-col">Date</th>'}<th>${schemaOnly?(semanticReview?'Qualification proposée':'Qualification lexicale'):'Besoins associés'}</th></tr></thead><tbody>${items.map(r=>`<tr><td class="quote-cell"><button data-demand="${esc(r.id)}">${esc(r.text||'Texte intégral indisponible')}</button><span class="item-subtitle">${esc(r.id)}${r.excerpt_only?' · extrait disponible uniquement':''}</span></td><td>${esc(demandCategory(r))}</td><td>${esc(channel(r.source))}</td>${schemaOnly?'':`<td class="num">${n(r.count||1)}</td>`}${schemaOnly||unknownPeriod?'':`<td class="date-col muted">${esc(r.date||'—')}</td>`}<td>${demandTags(r)}</td></tr>`).join('')}</tbody></table></div><div class="table-bottom"><span>${n(total)} ${schemaOnly?'requêtes du corpus':'formulations'} · chaque ligne compte une seule fois</span>${pager(total)}</div>`:empty('Aucune demande affichée','Modifiez la recherche, la catégorie ou la source.');
  }
  function demands(){const items=filteredDemands();return `<section class="panel"><div class="toolbar">${searchBox('Rechercher dans les demandes')}<select id="category-filter" aria-label="Filtrer par catégorie de requête">${categoryOptions(D.demands.map(demandCategory),categoryFilter,'Toutes les catégories de requêtes')}</select><select id="source-filter" aria-label="Filtrer par source">${sourceOptions()}</select></div><div id="table-content">${demandTable(items.slice(pageIndex*PAGE_SIZE,(pageIndex+1)*PAGE_SIZE),items.length)}</div>${schemaOnly?'<div class="placeholder-note">Les catégories de requêtes (query_class) et les catégories produit (product_class) du modèle sont des taxonomies distinctes ; aucune équivalence n’est présumée.</div>':''}</section>`;}
  function values(v){return Array.isArray(v)&&v.length?`<div class="tags">${v.map(x=>`<span class="tag">${esc(typeof x==='object'?JSON.stringify(x):x)}</span>`).join('')}</div>`:'<span class="muted small">Valeurs non renseignées</span>';}
  function filteredAttributes(){const q=query.toLocaleLowerCase();return D.attributes.filter(f=>(categoryFilter==='all'||scopes(f).includes(categoryFilter))&&([f.key,f.label,f.definition,...scopes(f)].join(' ').toLocaleLowerCase().includes(q)||(f.values||[]).some(v=>(categoryFilter==='all'||valueScopes(f,v).includes(categoryFilter))&&valueText(v).toLocaleLowerCase().includes(q))));}
  function attributeTable(items,total){
    return items.length?`<div class="table-wrap"><table class="attribute-table" aria-label="Attributs du modèle"><thead><tr><th>Attribut</th><th>Catégories produit</th><th>Valeurs${schemaOnly?' observées':''}</th><th>${schemaOnly?'Origine du modèle':'Définition'}</th></tr></thead><tbody>${items.map(f=>`<tr><td><button class="item-title" data-facet="${esc(f.key)}">${esc(f.label||f.key)}</button><code class="item-subtitle">${esc(f.key)}</code></td><td>${esc(scopes(f).slice(0,3).join(', ')||'Non renseignées')}${scopes(f).length>3?`<span class="item-subtitle">+ ${n(scopes(f).length-3)} catégories · voir le détail</span>`:''}</td><td><button class="text-button" data-facet="${esc(f.key)}">${n((f.values||[]).length)} valeurs</button>${schemaOnly?'<span class="item-subtitle">Observées · non exhaustives</span>':''}</td><td>${schemaOnly?esc(['observed_attribute_names','observed_attribute_names_and_values'].includes(f.schema_source)?'Attribut publié · modèle reconstitué':'Origine non renseignée'):esc(f.definition||'Définition non renseignée.')}</td></tr>`).join('')}</tbody></table></div><div class="table-bottom"><span>${n(total)} attributs · ${n(D.attributes.length)} au total</span>${pager(total)}</div>`:empty('Aucun attribut affiché','Modifiez la recherche ou la catégorie.');
  }
  function provenance(){
    if(!D.model.provenance)return '';
    // Metadata stays inert text: opening the preview never fetches published URLs.
    return `<details class="provenance"><summary>Provenance publiée</summary><pre>${esc(JSON.stringify(D.model.provenance,null,2))}</pre></details>`;
  }
  function modelView(){
    const items=filteredAttributes();
    const categories=[...(D.model.categories||[]),...D.attributes.flatMap(scopes)];
    return `<section class="panel"><div class="panel-heading"><div><h2>Attributs du modèle</h2><small>${n(D.attributes.length)} attributs · ${n(modelValueCount)} paires attribut–valeur${schemaOnly?' observées':''} · ${n(new Set(categories).size)} catégories produit</small><small>${esc(modelVersion)}</small></div>${icon('model')}</div>${schemaOnly?`<div class="placeholder-note">${esc(schemaDescription)} Les valeurs observées sont non exhaustives ; elles ne constituent pas des listes canoniques de valeurs autorisées.</div>`:''}<div class="toolbar">${searchBox('Rechercher un attribut, une valeur ou une catégorie')}<select id="category-filter" aria-label="Filtrer par catégorie produit">${categoryOptions(categories,categoryFilter,'Toutes les catégories produit')}</select></div><div id="table-content">${attributeTable(items.slice(pageIndex*PAGE_SIZE,(pageIndex+1)*PAGE_SIZE),items.length)}</div><div class="placeholder-note">Le modèle affiché est celui utilisé au début du Benchmark. <a class="text-button" href="#opportunities?gap=schema_gap">Examiner les attributs candidats (${n(gapCount('schema_gap'))})</a></div>${provenance()}</section>`;
  }
  function filteredValues(f){const q=valueQuery.toLocaleLowerCase();return (f.values||[]).filter(v=>(valueCategory==='all'||valueScopes(f,v).includes(valueCategory))&&valueText(v).toLocaleLowerCase().includes(q));}
  function scopeSummary(items){return esc(items.slice(0,3).join(', ')||'Non renseignées')+(items.length>3?`<details class="scope-details"><summary>+ ${n(items.length-3)} catégories</summary><p>${esc(items.slice(3).join(', '))}</p></details>`:'');}
  function facetValuesTable(f){
    const all=filteredValues(f), items=all.slice(valuePageIndex*PAGE_SIZE,(valuePageIndex+1)*PAGE_SIZE);
    return (items.length?`<div class="table-wrap"><table class="value-table" aria-label="Valeurs de l’attribut"><thead><tr><th>${schemaOnly?'Valeur observée':'Valeur'}</th><th>Catégories produit</th></tr></thead><tbody>${items.map(v=>`<tr><td class="value-text">${esc(valueText(v))}</td><td>${scopeSummary(valueScopes(f,v))}</td></tr>`).join('')}</tbody></table></div>`:empty('Aucune valeur affichée','Ajustez la recherche ou la catégorie ; une absence dans cet échantillon n’est pas une preuve d’impossibilité.'))+`<div class="table-bottom"><span>${n(all.length)} valeurs affichables · ${n((f.values||[]).length)} au total</span>${all.length>PAGE_SIZE?`<span class="pagination"><button data-value-step="-1" aria-label="Valeurs précédentes" ${valuePageIndex===0?'disabled':''}>${icon('back')}</button>${valuePageIndex+1} / ${Math.ceil(all.length/PAGE_SIZE)}<button data-value-step="1" aria-label="Valeurs suivantes" ${(valuePageIndex+1)*PAGE_SIZE>=all.length?'disabled':''}>${icon('chevron')}</button></span>`:''}</div>`;
  }
  function openFacet(key){
    const f=facetByKey.get(key);if(!f)return;
    activeCandidate=null;activeFacet=key;valueQuery='';valuePageIndex=0;valueCategory=categoryFilter;
    inspectorOpen(`<div class="drawer-heading"><h2 id="inspector-title">${esc(f.label||f.key)}</h2><span class="mono muted">${esc(f.key)}</span><p>${schemaOnly?'Valeurs observées · non exhaustives. Elles ne constituent pas une liste canonique ; une valeur absente reste à confirmer.':esc(f.definition||'Définition non renseignée.')}</p></div><div class="drawer-body"><details><summary>${n(scopes(f).length)} catégories produit de cet attribut</summary><p>${esc(scopes(f).join(', ')||'Non renseignées')}</p></details></div><div class="toolbar"><label class="search-field">${icon('search')}<input id="value-search" type="search" aria-label="Rechercher une valeur" placeholder="Rechercher une valeur"></label><select id="value-category-filter" aria-label="Filtrer les valeurs par catégorie produit">${categoryOptions(scopes(f),valueCategory,'Toutes les catégories produit')}</select></div><div id="value-content">${facetValuesTable(f)}</div>`,'ATTRIBUT DU MODÈLE');
  }
  function updateValues(){const f=facetByKey.get(activeFacet);if(f){$('#value-content').innerHTML=facetValuesTable(f);announce(`${filteredValues(f).length} valeurs`);}}
  function sources(){return `<section class="panel"><div class="panel-heading"><div><h2>${schemaOnly?'Sources du corpus':'Canaux observés'}</h2><small>${n(Object.keys(D.channels).length)} sources · ${n(D.summary.demand_records)} formulations</small></div><span class="badge">Échantillon importé</span></div><div class="source-row ${schemaOnly?'schema-source-row':''} muted"><span>Source</span><span class="num">${schemaOnly?'Requêtes':'Lignes'}</span>${schemaOnly?'':'<span class="num">Demandes</span>'}</div>${Object.entries(D.channels).sort(([,a],[,b])=>schemaOnly?b.records-a.records:b.events-a.events).map(([s,c])=>`<div class="source-row ${schemaOnly?'schema-source-row':''}"><div class="source-name"><span class="channel-symbol">${icon(channelIcon(s))}</span><div><button class="text-button" data-source-link="${esc(s)}">${esc(channel(s))}</button><small class="item-subtitle">${esc(s)}</small></div></div><span class="num">${n(c.records)}</span>${schemaOnly?'':`<span class="num">${n(c.events)}</span>`}</div>`).join('')||empty('Aucune source disponible')}<div class="placeholder-note">${schemaOnly?'Requêtes échantillonnées ; période d’observation et fréquence réelle inconnues.':unknownPeriod?'Période d’observation inconnue.':'Volumes observés sur la période sélectionnée. Aucune connexion en temps réel n’est présumée.'}</div>${provenance()}</section>`;}
  function runs(){return `<section class="panel"><div class="panel-heading"><div><h2>Exécutions enregistrées</h2><small>Ouvrir un résultat ne relance aucun calcul.</small></div></div>${D.jobs.length?`<div class="table-wrap"><table class="run-table" aria-label="Exécutions enregistrées"><thead><tr><th>Exécution</th>${schemaOnly?'':'<th>Création</th>'}<th>État du traitement</th><th></th></tr></thead><tbody>${D.jobs.map(j=>`<tr class="run-row ${j.id===D.id?'run-current':''}"><td><a href="/jobs/${encodeURIComponent(j.id)}#overview">${esc(j.id)}</a>${j.id===D.id?'<span class="item-subtitle">Résultat affiché</span>':''}</td>${schemaOnly?'':`<td class="muted">${j.created?esc(new Date(j.created*1000).toLocaleString('fr-FR')):'—'}</td>`}<td><span class="badge ${j.status==='completed'?'complete':j.status==='failed'?'failed':''}">${esc(({completed:'Terminé',failed:'Échec',queued:'En attente',running:'En cours'})[j.status]||j.status)}</span></td><td><a class="icon-button" href="/jobs/${encodeURIComponent(j.id)}#overview" aria-label="Ouvrir ${esc(j.id)}">${icon('chevron')}</a></td></tr>`).join('')}</tbody></table></div>`:empty('Aucune exécution enregistrée')}</section>`;}
  function render(){
    const [title,description]=pages[page];
    $('#page-title').textContent=title;$('#breadcrumb').textContent=title;$('#page-description').textContent=description;
    $('#eyebrow').textContent=schemaOnly?'REQUÊTES & MODÈLE DE DONNÉES':page==='model'?'RÉFÉRENTIEL DE CONNAISSANCE':page==='runs'?'TRAÇABILITÉ':'DEMANDE & CONNAISSANCE PRODUIT';
    document.querySelectorAll('#navigation a').forEach(a=>{if(a.hash===`#${page}`)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
    $('#content').innerHTML=({overview,opportunities,demands,model:modelView,sources,runs})[page]();
    $('#export').hidden=page==='runs';
  }
  function updateTable(){
    pageIndex=0;
    if(page==='opportunities'){const items=filteredCandidates();$('#table-content').innerHTML=opportunityTable(items.slice(0,PAGE_SIZE),false,items.length);announce(`${items.length} opportunités`);}
    if(page==='demands'){const items=filteredDemands();$('#table-content').innerHTML=demandTable(items.slice(0,PAGE_SIZE),items.length);announce(`${items.length} demandes`);}
    if(page==='model'){const items=filteredAttributes();$('#table-content').innerHTML=attributeTable(items.slice(0,PAGE_SIZE),items.length);announce(`${items.length} attributs`);}
  }
  function quoted(r,p){
    const text=r?.text;
    if(!r?.excerpt_only&&typeof text==='string'&&Number.isInteger(p.start)&&Number.isInteger(p.end)&&Array.from(text).slice(p.start,p.end).join('')===p.quote){const chars=Array.from(text);return esc(chars.slice(0,p.start).join(''))+'<mark>'+esc(p.quote)+'</mark>'+esc(chars.slice(p.end).join(''));}
    return esc((!r?.excerpt_only&&text)||p.quote||text||'Citation indisponible');
  }
  function proofCard(p){const r=demandById.get(p.record_id);return `<article class="evidence-card"><div class="evidence-meta"><span>${icon(channelIcon(p.source))}${esc(channel(p.source))}</span><span>${schemaOnly?esc(r?demandCategory(r):'Catégorie non renseignée'):`${n(p.count||1)} demande${(p.count||1)>1?'s':''}`}</span></div><blockquote>${quoted(r,p)}</blockquote>${p.interpretation?`<p class="evidence-note"><strong>Interprétation proposée :</strong> ${esc(p.interpretation)}</p>`:''}${p.rationale?`<p class="evidence-note"><strong>Justification :</strong> ${esc(p.rationale)}</p>`:''}<footer><span>${esc(p.record_id)}${r?.excerpt_only?' · extrait uniquement':''}</span><span>${!schemaOnly&&!unknownPeriod&&r?.date?esc(r.date)+' · ':''}${Number.isInteger(p.start)?`[${p.start}, ${p.end})`:''}</span></footer></article>`;}
  function inspectorOpen(html,kind=schemaOnly?'À EXAMINER':'OPPORTUNITÉ'){$('#inspector-content').innerHTML=html;$('#inspector-kind').textContent=kind;if(!$('#inspector').open){lastFocus=document.activeElement;$('#inspector').showModal();}$('#inspector').scrollTop=0;}
  function detailBody(c){
    const gap=(c.value_status==='not_observed_semantic'?{...gaps.value_gap,diagnosis:'La revue ne propose pas de valeur observée correspondant au besoin ; cette conclusion reste à confirmer.'}:gaps[c.gap_type])||{diagnosis:'Diagnostic non renseigné.',next:'Examiner la demande.'};
    const proofs=c.demand_records||[];
    if(detailTab==='evidence')return `<h3>${n(countRecords(c))} formulations sources</h3>${proofs.map(proofCard).join('')||empty('Aucune citation disponible')}`;
    if(schemaOnly){
      const facet=facetByKey.get(c.fact_key||c.key);
      const modelReference=(facet?`<button class="text-button" data-facet="${esc(facet.key)}">Voir les ${n((facet.values||[]).length)} valeurs observées de ${esc(facet.label||facet.key)}</button>`:'')+(c.matched_value!=null?`<p>Valeur du modèle : ${esc(c.matched_value)}</p>`:'')+(c.category_refs?.length?`<p>Catégories existantes : ${scopeSummary(c.category_refs)}</p>`:'');
      const valueDetail=c.requested_value!=null?`<div class="comparison-box"><div><small>VALEUR DEMANDÉE</small><strong>${esc(c.requested_value)}</strong><p>${esc(valueStatus(c.value_status))} · ${semanticReview?'interprétation proposée par les agents':'comparaison exacte uniquement'}.</p></div><div><small>MODÈLE RECONSTITUÉ</small>${modelReference||'<p>Aucune référence établie pour ce critère.</p>'}</div></div>${c.value_evidence?proofCard(c.value_evidence):''}`:'';
      if(detailTab==='definition')return `<dl class="fact-contract"><dt>Identifiant</dt><dd class="mono">${esc(c.key)}</dd><dt>Attribut</dt><dd>${esc(c.fact_key||'À qualifier')}</dd><dt>Définition</dt><dd>${esc(c.definition||'À définir')}</dd><dt>Détection</dt><dd>${esc(analysisLabel)}. Les conclusions restent à confirmer.</dd><dt>Modèle</dt><dd>${esc(modelVersion)}</dd></dl>${valueDetail}`;
      return `<div class="diagnosis"><h3>${esc(gap.diagnosis)}</h3><p>${esc(gap.next)}</p></div><p>${esc(lexicalDescription)}</p>${valueDetail}<h3>Dans les mots des clients</h3>${proofs.slice(0,2).map(proofCard).join('')||empty('Aucune citation disponible')}<button class="text-button" data-detail-tab="evidence">Toutes les requêtes sources (${n(countRecords(c))})</button>`;
    }
    if(detailTab==='definition')return `<dl class="fact-contract"><dt>Identifiant</dt><dd class="mono">${esc(c.key)}</dd><dt>Définition</dt><dd>${esc(c.definition||'À définir')}</dd><dt>Expressions</dt><dd>${values(c.aliases)}</dd><dt>Détection</dt><dd>${esc(({configured_phrase:'Expression configurée',supplied_grounded_intent:'Annotation avec citation',explicit_attribute_request:'Demande explicite d’attribut',unresolved:'Intention à préciser'})[c.detection]||c.detection||'Non renseignée')}</dd><dt>Modèle</dt><dd>${esc(D.model.version||'Non versionné')}</dd></dl><details><summary>Voir les données du besoin</summary><pre>${esc(JSON.stringify(c,null,2))}</pre></details>`;
    return `<div class="diagnosis"><h3>${esc(gap.diagnosis)}</h3><p>${esc(gap.next)}</p></div><div class="comparison-box"><div><small>DEMANDE OBSERVÉE</small><strong>${esc(c.label)}</strong><p>${n(c.demand_events)} événements sur ${n(uniqueSources(c).length)} canaux.</p></div><div><small>MODÈLE MÉTIER ACTUEL</small><strong>${c.gap_type==='schema_gap'?'Aucun attribut correspondant':c.gap_type==='unresolved_intent'?'Intention non établie':esc(c.key)}</strong><p>${c.gap_type==='schema_gap'?'La demande reste visible même sans preuve produit.':c.gap_type==='unresolved_intent'?'Aucune correspondance n’est affirmée.':`${n(c.known_assignment_count)} / ${n(D.summary.inventory_products)} produits renseignés dans le modèle d’entrée.`}</p></div></div><div class="title-actions" style="margin:26px 0 14px"><h3>Dans les mots des clients</h3><button class="text-button" data-detail-tab="evidence">Tout voir (${n(countRecords(c))})</button></div>${proofs.slice(0,2).map(proofCard).join('')||empty('Aucune citation disponible')}`;
  }
  function openCandidate(key,tabName='diagnostic'){
    const c=candidateByKey.get(key);if(!c)return;
    activeCandidate=key;activeFacet=null;detailTab=tabName;
    inspectorOpen(`<div class="drawer-heading">${badge(c.gap_type)}<h2 id="inspector-title">${esc(candidateTitle(c))}</h2><span class="mono muted">${esc(c.key)}</span><p>${esc(c.definition||'Définition à préciser à partir de la demande.')}</p><div class="drawer-stats"><div><strong class="num">${n(volume(c))}</strong><small>${schemaOnly?'requêtes du corpus':'demandes'}</small></div><div><strong class="num">${n(countRecords(c))}</strong><small>formulations</small></div><div><strong class="num">${n(uniqueSources(c).length)}</strong><small>sources</small></div></div></div><div class="drawer-tabs" aria-label="Détail de l’opportunité">${[['diagnostic','Diagnostic'],['evidence','Demandes sources'],['definition','Définition']].map(([key,label])=>`<button data-detail-tab="${key}" class="${detailTab===key?'active':''}" aria-pressed="${detailTab===key}">${label}</button>`).join('')}</div><div class="drawer-body">${detailBody(c)}</div>`);
  }
  function openDemand(id){const r=demandById.get(id);if(!r)return;activeCandidate=null;activeFacet=null;inspectorOpen(`<div class="drawer-heading"><h2 id="inspector-title">${schemaOnly?'Requête du corpus':'Demande source'}</h2><span class="mono muted">${esc(r.id)}</span><p>Catégorie de requête : ${esc(demandCategory(r))}</p></div><div class="drawer-body">${proofCard({record_id:r.id,source:r.source,quote:r.text,count:r.count})}<h3>${schemaOnly?'Rapprochements candidats':'Besoins associés'}</h3>${demandTags(r)}${semanticReview?representedMatches(r).map(p=>`<section class="method-section"><h3>${esc(p.label||p.fact_key||'Critère représenté')}</h3><p>${esc(p.rationale||'')}</p>${p.matched_value!=null?`<p>Valeur du modèle : ${esc(p.matched_value)}</p>`:''}${p.category_refs?.length?`<p>Catégories du modèle : ${scopeSummary(p.category_refs)}</p>`:''}${p.evidence?proofCard(p.evidence):''}</section>`).join(''):''}${schemaOnly?`<p>${esc(lexicalDescription)}</p>`:''}${schemaOnly?representedMatches(r).filter(p=>p.value_evidence).map(p=>`<h3>${esc(valueStatus(p.value_status))}</h3>${proofCard(p.value_evidence)}`).join(''):''}</div>`,'DEMANDE CLIENT');}
  function methodology(){
    activeCandidate=null;activeFacet=null;
    if(schemaOnly){inspectorOpen(`<div class="drawer-heading"><h2 id="inspector-title">Méthode & comptage</h2></div><div class="drawer-body"><section class="method-section"><h3>Requêtes du corpus</h3><p>Chaque ligne compte une seule fois. Le champ count est un poids d’échantillonnage, pas une fréquence réelle ni un nombre d’événements clients. Période d’observation inconnue. Une requête peut contribuer à plusieurs pistes ; leurs nombres ne sont pas additionnables.</p></section><section class="method-section"><h3>Modèle reconstitué et valeurs observées</h3><p>${esc(schemaDescription)} Les valeurs observées sont non exhaustives et ne constituent pas des listes canoniques de valeurs autorisées.</p></section><section class="method-section"><h3>${esc(analysisLabel)}</h3>${semanticReview?`<p>${n(D.analysis.reviewed_records)} requêtes · ${n(D.analysis.reviewed_criteria)} critères revus. Décisions d’agents importées${D.analysis.independent_audit===false?' · sans audit indépendant':''}.</p>`:''}<p>${esc(lexicalDescription)} Une correspondance exacte avec une valeur ne valide pas les autres contraintes de la requête. Une valeur non observée reste à confirmer ; les valeurs non décodées restent non évaluées ou à qualifier.</p></section><section class="method-section"><h3>Catégories distinctes</h3><p>query_class décrit les requêtes et product_class les catégories produit du modèle. Ces taxonomies ne sont pas identiques ; aucune équivalence automatique n’est affirmée par cette vue.</p></section><section class="method-section"><h3>Aperçu en lecture seule</h3><p>La comparaison porte sur les requêtes et le modèle de données avec ses valeurs observées, sans instances produit. Aucun appel distant ni modification du modèle n’est effectué.</p></section></div>`,'MÉTHODOLOGIE');return;}
    inspectorOpen(`<div class="drawer-heading"><h2 id="inspector-title">Méthode & comptage</h2></div><div class="drawer-body"><section class="method-section"><h3>Demandes ≠ clients uniques</h3><p>Le total additionne le volume de chaque enregistrement une seule fois. Une même demande peut contribuer à plusieurs opportunités ; les volumes par besoin ne sont donc pas additionnables.</p></section><section class="method-section"><h3>Le modèle d’entrée fait référence</h3><p>Les attributs et affectations sont ceux du début du Benchmark. Les valeurs extraites ou proposées ensuite ne modifient pas cette mesure de couverture.</p></section><section class="method-section"><h3>Priorité par volume observé</h3><p>Le classement utilise le nombre de demandes, sans score de revenu ou d’impact inventé. Les opportunités sont des diagnostics à examiner, pas des validations ontologiques.</p></section><section class="method-section"><h3>Détection utilisée</h3><p>${esc(D.metrics.detector||'Méthode non renseignée pour ce résultat.')}</p><p>La détection par expressions configurées ne mesure pas une compréhension sémantique exhaustive. Les intentions non reconnues restent à qualifier.</p></section>${D.synthetic?'<section class="method-section"><h3>Données synthétiques</h3><p>Ce jeu illustre le fonctionnement. Il ne permet pas de conclure à la précision sur vos données réelles.</p></section>':''}</div>`,'MÉTHODOLOGIE');
  }
  function download(){
    let data,name,type;
    if(page==='model'){data=JSON.stringify(D.model,null,2);name='pilon-benchmark-model.json';type='application/json';}
    else {
      const csvCell=v=>{let s=String(v??'');if(/^(?:\s*[=+@\-]|[\t\r\n])/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};
      const rows=schemaOnly?(page==='demands'?[['id','source','query_class','text','sampling_weight','lexical_candidates'],...filteredDemands().map(r=>[r.id,r.source,r.query_class,r.text,r.count??1,JSON.stringify(representedMatches(r))])]:page==='sources'?[['source','corpus_queries'],...Object.entries(D.channels).map(([s,c])=>[s,c.records])]:[['key','label','gap_type','corpus_queries','requested_value','value_status'],...(page==='opportunities'?filteredCandidates():candidates).map(c=>[c.key,candidateTitle(c),c.gap_type,countRecords(c),c.requested_value,c.value_status])]):page==='demands'?[['id','source','text','count'],...filteredDemands().map(r=>[r.id,r.source,r.text,r.count||1])]:page==='sources'?[['source','records','events'],...Object.entries(D.channels).map(([s,c])=>[s,c.records,c.events])]:[['key','label','gap_type','demand_events','source_records','known_assignment_count'],...(page==='opportunities'?filteredCandidates():candidates).map(c=>[c.key,candidateTitle(c),c.gap_type,c.demand_events,countRecords(c),c.known_assignment_count])];
      data='\uFEFF'+rows.map(row=>row.map(csvCell).join(';')).join('\r\n');name=`pilon-benchmark-${page}.csv`;type='text/csv;charset=utf-8';
    }
    const url=URL.createObjectURL(new Blob([data],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);announce('Export téléchargé.');
  }
  function navigate(){
    const raw=location.hash.slice(1).split('?');const next=Object.hasOwn(pages,raw[0])?raw[0]:'overview';if(raw[0]==='main')return;if(!Object.hasOwn(pages,raw[0]))history.replaceState(null,'','#overview');
    if(page!==next){query='';sourceFilter='all';gapFilter='all';categoryFilter='all';pageIndex=0;}
    page=next;const params=new URLSearchParams(raw[1]||'');if(gaps[params.get('gap')])gapFilter=params.get('gap');if(Object.hasOwn(D.channels,params.get('source')))sourceFilter=params.get('source');
    $('#inspector').close();render();window.scrollTo(0,0);
  }
  document.addEventListener('click',e=>{
    const b=e.target.closest('button,[data-candidate]');if(!b)return;
    if(b.dataset.candidate)openCandidate(b.dataset.candidate);
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
