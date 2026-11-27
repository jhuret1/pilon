/* Local, dependency-free Benchmark interactions. No inference or remote request. */
(() => {
  'use strict';
  const D = JSON.parse(document.getElementById('benchmark-data').textContent);
  const $ = s => document.querySelector(s);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const n = v => v == null ? '—' : new Intl.NumberFormat('fr-FR').format(v);
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
  let page = 'overview', query = '', gapFilter = 'all', sourceFilter = 'all', sort = 'volume', pageIndex = 0;
  let activeCandidate = null, detailTab = 'diagnostic', lastFocus = null;
  const PAGE_SIZE = 25;
  const ready = D.ready;
  const candidates = D.candidates;
  const maxVolume = Math.max(1,...candidates.map(c => c.demand_events || 0));
  const uniqueSources = c => [...new Set((c.demand_records || []).map(p => p.source))];
  const countRecords = c => new Set((c.demand_records || []).map(p => p.record_id)).size;
  const stateLabel = D.status === 'failed' ? 'Échec' : ready ? 'Benchmark disponible' : D.status === 'empty' ? 'Aucune exécution' : 'En attente de résultat';
  const statusClass = D.status === 'failed' ? 'failed' : ready ? 'complete' : '';
  $('#navigation').innerHTML = Object.entries(pages).filter(([k]) => k !== 'runs').map(([key,[label,,ico]],i) => `${i===3?'<div class="nav-separator"></div>':''}<a href="#${key}" title="${label}">${icon(ico)}<span class="nav-text">${label}</span>${key==='opportunities'?`<span class="nav-count">${n(candidates.length)}</span>`:''}</a>`).join('');
  document.querySelectorAll('[data-icon]').forEach(el => el.innerHTML = icon(el.dataset.icon));
  $('#workspace-name').textContent = D.model.category || 'Espace local';
  $('#snapshot-state').textContent = stateLabel;
  $('#snapshot-state').className = `badge ${statusClass}`;
  $('#demo-label').textContent = D.synthetic ? 'DÉMO' : '';
  $('#demo-banner').hidden = !D.synthetic;
  $('#category').innerHTML = `${icon('box')}${esc(D.model.category || 'Catégorie non renseignée')}`;
  const date = value => value ? new Date(`${value}T12:00:00`).toLocaleDateString('fr-FR',{day:'numeric',month:'short',year:'numeric'}) : '—';
  $('#period').innerHTML = `${icon('calendar')}${esc(date(D.model.window_start))} – ${esc(date(D.model.window_end))}`;
  $('#footer-context').textContent = `${D.model.version || 'Modèle non versionné'} · ${D.complete_inputs?'Périmètre complet':'Extraits disponibles'} · Lecture seule`;
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
    if(!items.length) return empty('Aucune opportunité affichée',query||gapFilter!=='all'?'Modifiez la recherche ou les filtres.':ready?'Aucun écart détecté dans ce résultat.':'Les résultats apparaîtront après le Benchmark.');
    return `<div class="table-wrap"><table class="opportunity-table" aria-label="Opportunités de connaissance"><thead><tr><th>Besoin client</th><th>Diagnostic</th><th>Demandes</th><th class="channel-col">Canaux</th><th class="coverage-col">Modèle actuel</th><th class="open-col"><span class="sr-only">Détail</span></th></tr></thead><tbody>${items.map(c=>`<tr><td><button class="item-title" data-candidate="${esc(c.key)}">${esc(c.label)}</button><span class="item-subtitle">${n(countRecords(c))} texte${countRecords(c)>1?'s':''} source${countRecords(c)>1?'s':''}</span></td><td>${badge(c.gap_type)}</td><td><span class="cell-metric"><b class="num">${n(c.demand_events)}</b><span class="mini-track"><i style="width:${Math.min(100,100*(c.demand_events||0)/maxVolume)}%"></i></span></span></td><td class="channel-col">${channelSymbols(c)}</td><td class="coverage-col">${coverage(c)}</td><td class="open-col"><button class="icon-button" data-candidate="${esc(c.key)}" aria-label="Examiner ${esc(c.label)}">${icon('chevron')}</button></td></tr>`).join('')}</tbody></table></div><div class="table-bottom"><span>${compact?`${n(items.length)} opportunités · priorité par volume`:`${n(total)} opportunités`}</span>${compact?'<a href="#opportunities" class="text-button">Tout explorer</a>':pager(total)}</div>`;
  }
  function overview() {
    const s=D.summary;
    let start=0; const slices=Object.entries(gaps).map(([key,g])=>{let end=start+((s.gaps[key]||0)/Math.max(1,candidates.length))*100;const out=`${g.color} ${start}% ${end}%`;start=end;return out;}).join(',');
    return `${notice()}<div class="metrics">${metric('Demandes observées',D.complete_inputs?s.demand_events:null,`${n(s.demand_records)} textes sources`,'demands')}${metric('Opportunités',ready?s.opportunity_count:null,'Besoins non entièrement couverts','opportunities')}${metric('Attributs à envisager',ready?s.schema_gaps:null,'Absents du modèle actuel','model',true)}${metric('Attributs existants',s.attributes,`${n(s.inventory_products)} produits dans le périmètre`,'box')}</div>
    <div class="overview-grid"><section class="panel"><div class="panel-heading"><div><h2>Ce que les clients demandent</h2><small>Les 5 premiers besoins · événements observés</small></div></div><div class="panel-body">${candidates.length?candidates.slice(0,5).map(c=>`<button class="rank-row" data-candidate="${esc(c.key)}" title="Examiner ${esc(c.label)}"><span class="rank-label">${esc(c.label)}</span><span class="bar-track"><span class="bar-fill" style="display:block;width:${100*(c.demand_events||0)/maxVolume}%"></span></span><strong class="num">${n(c.demand_events)}</strong></button>`).join(''):empty('Aucun besoin disponible')}</div></section>
    <section class="panel"><div class="panel-heading"><div><h2>Où sont les écarts ?</h2><small>Répartition des opportunités</small></div></div><div class="panel-body"><div class="gap-chart"><div class="donut" style="background:${candidates.length?`conic-gradient(${slices})`:'#f0f1f6'}" role="img" aria-label="${n(candidates.length)} opportunités réparties par diagnostic"><div class="donut-center">${ready?n(candidates.length):'—'}<small>opportunités</small></div></div><div class="legend">${Object.entries(gaps).map(([key,g])=>`<button data-gap-link="${key}"><i class="swatch ${key}"></i>${g.plural}<strong>${ready?n(s.gaps[key]||0):'—'}</strong></button>`).join('')}</div></div></div></section></div>
    <section class="panel"><div class="panel-heading"><div><h2>Opportunités à explorer</h2><small>De la demande client au manque identifié.</small></div><a class="text-button" href="#opportunities">Voir tout</a></div>${opportunityTable(candidates.slice(0,5),true)}</section>`;
  }
  function filteredCandidates() {
    const q=query.toLocaleLowerCase();
    return candidates.filter(c=>(gapFilter==='all'||c.gap_type===gapFilter)&&(sourceFilter==='all'||uniqueSources(c).includes(sourceFilter))&&[c.label,c.key,c.definition,...(c.demand_records||[]).map(p=>p.quote)].join(' ').toLocaleLowerCase().includes(q)).sort((a,b)=>sort==='name'?String(a.label).localeCompare(String(b.label)):sort==='sources'?uniqueSources(b).length-uniqueSources(a).length:(b.demand_events||0)-(a.demand_events||0));
  }
  function sourceOptions() {return `<option value="all">Tous les canaux</option>${Object.keys(D.channels).map(s=>`<option value="${esc(s)}" ${sourceFilter===s?'selected':''}>${esc(channel(s))}</option>`).join('')}`;}
  function searchBox(placeholder) {return `<label class="search-field">${icon('search')}<input id="search" type="search" aria-label="${esc(placeholder)}" placeholder="${esc(placeholder)}" value="${esc(query)}"></label>`;}
  function pager(total) {return total>PAGE_SIZE?`<span class="pagination"><button data-page-step="-1" aria-label="Page précédente" ${pageIndex===0?'disabled':''}>${icon('back')}</button>${pageIndex+1} / ${Math.ceil(total/PAGE_SIZE)}<button data-page-step="1" aria-label="Page suivante" ${(pageIndex+1)*PAGE_SIZE>=total?'disabled':''}>${icon('chevron')}</button></span>`:'';}
  function opportunities() {
    const items=filteredCandidates();
    return `${notice()}<div class="filter-tabs" aria-label="Diagnostics"><button data-gap="all" class="${gapFilter==='all'?'active':''}" aria-pressed="${gapFilter==='all'}">Tous<span>${n(candidates.length)}</span></button>${Object.entries(gaps).map(([key,g])=>`<button data-gap="${key}" class="${gapFilter===key?'active':''}" aria-pressed="${gapFilter===key}">${g.plural}<span>${n(D.summary.gaps[key]||0)}</span></button>`).join('')}</div><section class="panel"><div class="toolbar">${searchBox('Rechercher un besoin ou une citation')}<select id="source-filter" aria-label="Filtrer par canal">${sourceOptions()}</select><select id="sort" aria-label="Trier les opportunités"><option value="volume" ${sort==='volume'?'selected':''}>Demande décroissante</option><option value="name" ${sort==='name'?'selected':''}>Nom du besoin</option><option value="sources" ${sort==='sources'?'selected':''}>Nombre de canaux</option></select></div><div id="table-content">${opportunityTable(items.slice(pageIndex*PAGE_SIZE,(pageIndex+1)*PAGE_SIZE),false,items.length)}</div></section>`;
  }
  function filteredDemands(){const q=query.toLocaleLowerCase();return D.demands.filter(r=>(sourceFilter==='all'||r.source===sourceFilter)&&[r.text,r.id,...r.matches.map(m=>m.candidate_key)].join(' ').toLocaleLowerCase().includes(q)).sort((a,b)=>(b.count||1)-(a.count||1));}
  function demandTable(items,total) {
    return items.length?`<div class="table-wrap"><table class="demand-table" aria-label="Demandes sources"><thead><tr><th>Demande originale</th><th>Canal</th><th>Volume</th><th class="date-col">Date</th><th>Besoins associés</th></tr></thead><tbody>${items.map(r=>`<tr><td class="quote-cell"><button data-demand="${esc(r.id)}">${esc(r.text)}</button><span class="item-subtitle">${esc(r.id)}${r.excerpt_only?' · extrait':''}</span></td><td>${esc(channel(r.source))}</td><td class="num">${n(r.count||1)}</td><td class="date-col muted">${esc(r.date||'—')}</td><td><div class="tags">${r.matches.map(p=>{const c=candidates.find(c=>c.key===p.candidate_key);return `<button class="tag tag-button" data-candidate="${esc(p.candidate_key)}">${esc(c?.label||p.candidate_key)}</button>`;}).join('')||'<span class="muted">Aucun écart rattaché</span>'}</div></td></tr>`).join('')}</tbody></table></div><div class="table-bottom"><span>${n(total)} formulations · chaque ligne compte une seule fois</span>${pager(total)}</div>`:empty('Aucune demande affichée','Modifiez la recherche ou le canal.');
  }
  function demands(){const items=filteredDemands();return `<section class="panel"><div class="toolbar">${searchBox('Rechercher dans les demandes')}<select id="source-filter" aria-label="Filtrer par canal">${sourceOptions()}</select></div><div id="table-content">${demandTable(items.slice(pageIndex*PAGE_SIZE,(pageIndex+1)*PAGE_SIZE),items.length)}</div></section>`;}
  function values(v){return Array.isArray(v)&&v.length?`<div class="tags">${v.map(x=>`<span class="tag">${esc(typeof x==='object'?JSON.stringify(x):x)}</span>`).join('')}</div>`:'<span class="muted small">Valeurs non renseignées</span>';}
  function modelView(){return `<div class="model-grid"><section class="panel"><div class="panel-heading"><div><h2>Attributs du modèle</h2><small>${n(D.attributes.length)} attributs · ${esc(D.model.version||'version non renseignée')}</small></div>${icon('model')}</div>${D.attributes.map(f=>`<article class="model-card"><div class="model-card-header"><h3>${esc(f.label||f.key)}</h3><code>${esc(f.key)}</code></div><p>${esc(f.definition||'Définition non renseignée.')}</p>${values(f.values)}</article>`).join('')||empty('Aucun attribut renseigné')}</section><section class="panel"><div class="panel-heading"><div><h2>Besoins hors modèle</h2><small>Détectés dans la demande · pas encore des attributs</small></div>${icon('opportunities')}</div>${candidates.filter(c=>c.gap_type==='schema_gap').map(c=>`<article class="model-card"><div class="model-card-header"><button class="text-button" data-candidate="${esc(c.key)}">${esc(c.label)}</button>${badge(c.gap_type)}</div><p>${esc(c.definition||'Définition à préciser.')}</p><small>${n(c.demand_events)} demandes · ${n(uniqueSources(c).length)} canaux</small></article>`).join('')||empty('Aucun attribut manquant détecté')}<div class="placeholder-note">Le modèle affiché est celui utilisé au début du Benchmark.</div></section></div>`;}
  function sources(){return `<section class="panel"><div class="panel-heading"><div><h2>Canaux observés</h2><small>${n(Object.keys(D.channels).length)} sources · ${n(D.summary.demand_records)} formulations</small></div><span class="badge">Échantillon importé</span></div><div class="source-row muted"><span>Source</span><span class="num">Lignes</span><span class="num">Demandes</span></div>${Object.entries(D.channels).sort(([,a],[,b])=>b.events-a.events).map(([s,c])=>`<div class="source-row"><div class="source-name"><span class="channel-symbol">${icon(channelIcon(s))}</span><div><button class="text-button" data-source-link="${esc(s)}">${esc(channel(s))}</button><small class="item-subtitle">${esc(s)}</small></div></div><span class="num">${n(c.records)}</span><span class="num">${n(c.events)}</span></div>`).join('')||empty('Aucune source disponible')}<div class="placeholder-note">Volumes observés sur la période sélectionnée. Aucune connexion en temps réel n’est présumée.</div></section>`;}
  function runs(){return `<section class="panel"><div class="panel-heading"><div><h2>Exécutions enregistrées</h2><small>Ouvrir un résultat ne relance aucun calcul.</small></div></div>${D.jobs.length?`<div class="table-wrap"><table class="run-table" aria-label="Historique des exécutions"><thead><tr><th>Exécution</th><th>Création</th><th>État du traitement</th><th></th></tr></thead><tbody>${D.jobs.map(j=>`<tr class="run-row ${j.id===D.id?'run-current':''}"><td><a href="/jobs/${encodeURIComponent(j.id)}#overview">${esc(j.id)}</a>${j.id===D.id?'<span class="item-subtitle">Résultat affiché</span>':''}</td><td class="muted">${j.created?esc(new Date(j.created*1000).toLocaleString('fr-FR')):'—'}</td><td><span class="badge ${j.status==='completed'?'complete':j.status==='failed'?'failed':''}">${esc(({completed:'Terminé',failed:'Échec',queued:'En attente',running:'En cours'})[j.status]||j.status)}</span></td><td><a class="icon-button" href="/jobs/${encodeURIComponent(j.id)}#overview" aria-label="Ouvrir ${esc(j.id)}">${icon('chevron')}</a></td></tr>`).join('')}</tbody></table></div>`:empty('Aucune exécution enregistrée')}</section>`;}
  function render(){
    const [title,description]=pages[page];
    $('#page-title').textContent=title;$('#breadcrumb').textContent=title;$('#page-description').textContent=description;
    $('#eyebrow').textContent=page==='model'?'RÉFÉRENTIEL DE CONNAISSANCE':page==='runs'?'TRAÇABILITÉ':'DEMANDE & CONNAISSANCE PRODUIT';
    document.querySelectorAll('#navigation a').forEach(a=>{if(a.hash===`#${page}`)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
    $('#content').innerHTML=({overview,opportunities,demands,model:modelView,sources,runs})[page]();
    $('#export').hidden=page==='runs';
  }
  function updateTable(){
    pageIndex=0;
    if(page==='opportunities'){const items=filteredCandidates();$('#table-content').innerHTML=opportunityTable(items.slice(0,PAGE_SIZE),false,items.length);announce(`${items.length} opportunités`);}
    if(page==='demands'){const items=filteredDemands();$('#table-content').innerHTML=demandTable(items.slice(0,PAGE_SIZE),items.length);announce(`${items.length} demandes`);}
  }
  function quoted(r,p){
    const text=r?.text;
    if(!r?.excerpt_only&&typeof text==='string'&&Number.isInteger(p.start)&&Number.isInteger(p.end)&&Array.from(text).slice(p.start,p.end).join('')===p.quote){const chars=Array.from(text);return esc(chars.slice(0,p.start).join(''))+'<mark>'+esc(p.quote)+'</mark>'+esc(chars.slice(p.end).join(''));}
    return esc(p.quote||text||'Citation indisponible');
  }
  function proofCard(p){const r=D.demands.find(r=>r.id===p.record_id);return `<article class="evidence-card"><div class="evidence-meta"><span>${icon(channelIcon(p.source))}${esc(channel(p.source))}</span><span>${n(p.count||1)} demande${(p.count||1)>1?'s':''}</span></div><blockquote>${quoted(r,p)}</blockquote><footer><span>${esc(p.record_id)}</span><span>${r?.date?esc(r.date)+' · ':''}${Number.isInteger(p.start)?`[${p.start}, ${p.end})`:''}</span></footer></article>`;}
  function inspectorOpen(html,kind='OPPORTUNITÉ'){$('#inspector-content').innerHTML=html;$('#inspector-kind').textContent=kind;if(!$('#inspector').open){lastFocus=document.activeElement;$('#inspector').showModal();}$('#inspector').scrollTop=0;}
  function detailBody(c){
    const gap=gaps[c.gap_type]||{diagnosis:'Diagnostic non renseigné.',next:'Examiner la demande.'};
    const proofs=c.demand_records||[];
    if(detailTab==='evidence')return `<h3>${n(countRecords(c))} formulations sources</h3>${proofs.map(proofCard).join('')||empty('Aucune citation disponible')}`;
    if(detailTab==='definition')return `<dl class="fact-contract"><dt>Identifiant</dt><dd class="mono">${esc(c.key)}</dd><dt>Définition</dt><dd>${esc(c.definition||'À définir')}</dd><dt>Expressions</dt><dd>${values(c.aliases)}</dd><dt>Détection</dt><dd>${esc(({configured_phrase:'Expression configurée',supplied_grounded_intent:'Annotation avec citation',explicit_attribute_request:'Demande explicite d’attribut',unresolved:'Intention à préciser'})[c.detection]||c.detection||'Non renseignée')}</dd><dt>Modèle</dt><dd>${esc(D.model.version||'Non versionné')}</dd></dl><details><summary>Voir les données du besoin</summary><pre>${esc(JSON.stringify(c,null,2))}</pre></details>`;
    return `<div class="diagnosis"><h3>${esc(gap.diagnosis)}</h3><p>${esc(gap.next)}</p></div><div class="comparison-box"><div><small>DEMANDE OBSERVÉE</small><strong>${esc(c.label)}</strong><p>${n(c.demand_events)} événements sur ${n(uniqueSources(c).length)} canaux.</p></div><div><small>MODÈLE MÉTIER ACTUEL</small><strong>${c.gap_type==='schema_gap'?'Aucun attribut correspondant':c.gap_type==='unresolved_intent'?'Intention non établie':esc(c.key)}</strong><p>${c.gap_type==='schema_gap'?'La demande reste visible même sans preuve produit.':c.gap_type==='unresolved_intent'?'Aucune correspondance n’est affirmée.':`${n(c.known_assignment_count)} / ${n(D.summary.inventory_products)} produits renseignés dans le modèle d’entrée.`}</p></div></div><div class="title-actions" style="margin:26px 0 14px"><h3>Dans les mots des clients</h3><button class="text-button" data-detail-tab="evidence">Tout voir (${n(countRecords(c))})</button></div>${proofs.slice(0,2).map(proofCard).join('')||empty('Aucune citation disponible')}`;
  }
  function openCandidate(key,tabName='diagnostic'){
    const c=candidates.find(c=>c.key===key);if(!c)return;
    activeCandidate=key;detailTab=tabName;
    inspectorOpen(`<div class="drawer-heading">${badge(c.gap_type)}<h2 id="inspector-title">${esc(c.label)}</h2><span class="mono muted">${esc(c.key)}</span><p>${esc(c.definition||'Définition à préciser à partir de la demande.')}</p><div class="drawer-stats"><div><strong class="num">${n(c.demand_events)}</strong><small>demandes</small></div><div><strong class="num">${n(countRecords(c))}</strong><small>formulations</small></div><div><strong class="num">${n(uniqueSources(c).length)}</strong><small>canaux</small></div></div></div><div class="drawer-tabs" aria-label="Détail de l’opportunité">${[['diagnostic','Diagnostic'],['evidence','Demandes sources'],['definition','Définition']].map(([key,label])=>`<button data-detail-tab="${key}" class="${detailTab===key?'active':''}" aria-pressed="${detailTab===key}">${label}</button>`).join('')}</div><div class="drawer-body">${detailBody(c)}</div>`);
  }
  function openDemand(id){const r=D.demands.find(r=>r.id===id);if(!r)return;activeCandidate=null;inspectorOpen(`<div class="drawer-heading"><h2 id="inspector-title">Demande source</h2><span class="mono muted">${esc(r.id)}</span></div><div class="drawer-body">${proofCard({record_id:r.id,source:r.source,quote:r.text,count:r.count})}<h3>Besoins associés</h3><div class="tags">${r.matches.map(p=>`<button class="tag tag-button" data-candidate="${esc(p.candidate_key)}">${esc(candidates.find(c=>c.key===p.candidate_key)?.label||p.candidate_key)}</button>`).join('')||'<span class="muted">Aucun écart rattaché</span>'}</div></div>`,'DEMANDE CLIENT');}
  function methodology(){activeCandidate=null;inspectorOpen(`<div class="drawer-heading"><h2 id="inspector-title">Méthode & comptage</h2></div><div class="drawer-body"><section class="method-section"><h3>Demandes ≠ clients uniques</h3><p>Le total additionne le volume de chaque enregistrement une seule fois. Une même demande peut contribuer à plusieurs opportunités ; les volumes par besoin ne sont donc pas additionnables.</p></section><section class="method-section"><h3>Le modèle d’entrée fait référence</h3><p>Les attributs et affectations sont ceux du début du Benchmark. Les valeurs extraites ou proposées ensuite ne modifient pas cette mesure de couverture.</p></section><section class="method-section"><h3>Priorité par volume observé</h3><p>Le classement utilise le nombre de demandes, sans score de revenu ou d’impact inventé. Les opportunités sont des diagnostics à examiner, pas des validations ontologiques.</p></section><section class="method-section"><h3>Détection utilisée</h3><p>${esc(D.metrics.detector||'Méthode non renseignée pour ce résultat.')}</p><p>La détection par expressions configurées ne mesure pas une compréhension sémantique exhaustive. Les intentions non reconnues restent à qualifier.</p></section>${D.synthetic?'<section class="method-section"><h3>Données synthétiques</h3><p>Ce jeu illustre le fonctionnement. Il ne permet pas de conclure à la précision sur vos données réelles.</p></section>':''}</div>`,'MÉTHODOLOGIE');}
  function download(){
    let data,name,type;
    if(page==='model'){data=JSON.stringify(D.model,null,2);name='pilon-benchmark-model.json';type='application/json';}
    else {
      const csvCell=v=>{let s=String(v??'');if(/^(?:\s*[=+@\-]|[\t\r\n])/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};
      const rows=page==='demands'?[['id','source','text','count'],...filteredDemands().map(r=>[r.id,r.source,r.text,r.count||1])]:page==='sources'?[['source','records','events'],...Object.entries(D.channels).map(([s,c])=>[s,c.records,c.events])]:[['key','label','gap_type','demand_events','source_records','known_assignment_count'],...(page==='opportunities'?filteredCandidates():candidates).map(c=>[c.key,c.label,c.gap_type,c.demand_events,countRecords(c),c.known_assignment_count])];
      data='\uFEFF'+rows.map(row=>row.map(csvCell).join(';')).join('\r\n');name=`pilon-benchmark-${page}.csv`;type='text/csv;charset=utf-8';
    }
    const url=URL.createObjectURL(new Blob([data],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);announce('Export téléchargé.');
  }
  function navigate(){
    const raw=location.hash.slice(1).split('?');const next=Object.hasOwn(pages,raw[0])?raw[0]:'overview';if(raw[0]==='main')return;if(!Object.hasOwn(pages,raw[0]))history.replaceState(null,'','#overview');
    if(page!==next){query='';sourceFilter='all';gapFilter='all';pageIndex=0;}
    page=next;const params=new URLSearchParams(raw[1]||'');if(gaps[params.get('gap')])gapFilter=params.get('gap');if(Object.hasOwn(D.channels,params.get('source')))sourceFilter=params.get('source');
    $('#inspector').close();render();window.scrollTo(0,0);
  }
  document.addEventListener('click',e=>{
    const b=e.target.closest('button,[data-candidate]');if(!b)return;
    if(b.dataset.candidate)openCandidate(b.dataset.candidate);
    else if(b.dataset.demand)openDemand(b.dataset.demand);
    else if(b.dataset.detailTab&&activeCandidate)openCandidate(activeCandidate,b.dataset.detailTab);
    else if(b.dataset.gap){gapFilter=b.dataset.gap;pageIndex=0;render();}
    else if(b.dataset.gapLink)location.hash=`opportunities?gap=${b.dataset.gapLink}`;
    else if(b.dataset.sourceLink)location.hash=`demands?source=${encodeURIComponent(b.dataset.sourceLink)}`;
    else if(b.dataset.pageStep){pageIndex+=Number(b.dataset.pageStep);render();}
  });
  document.addEventListener('input',e=>{if(e.target.id==='search'){query=e.target.value;updateTable();}});
  document.addEventListener('change',e=>{if(e.target.id==='source-filter'){sourceFilter=e.target.value;updateTable();}if(e.target.id==='sort'){sort=e.target.value;updateTable();}});
  $('#export').addEventListener('click',download);
  $('#methodology').addEventListener('click',methodology);
  $('#close-inspector').addEventListener('click',()=>$('#inspector').close());
  $('#inspector').addEventListener('click',e=>{if(e.target===$('#inspector')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
  $('#inspector').addEventListener('close',()=>{activeCandidate=null;if(lastFocus?.isConnected)lastFocus.focus();});
  window.addEventListener('hashchange',navigate);navigate();
})();
