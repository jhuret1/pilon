'use strict';
let run = null, selected = null;
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = n => '$' + Number(n || 0).toFixed(6);
function proof(e) {
  const a = e.attributes || {}, row = run.rows[e.review_index];
  return `<article class="proof"><div class="value">${esc(a.value)} <span class="tag">${esc(e.route)}</span></div><blockquote>“${esc(e.quote)}”</blockquote><small>${esc(a.concept)} · ${esc(e.proof_status)} · meaning: ${esc(e.qualification_status)}</small><div class="chips">${['presence','condition','subject','temporality'].map(k=>`<span class="chip">${k}: ${esc(a[k])}</span>`).join('')}</div><small>${esc(row.item_title)} · ${esc(row.review_id)} · ${esc(row.language)} · characters [${e.start}, ${e.end})</small><details><summary>Read source review and decision</summary><p>${esc(row.text)}</p><p>Context: ${esc(a.context || '—')}</p><p>Routing: ${esc(e.enrichment_mode || e.route)} · ${esc(e.answers?.routing?.choice || '—')}</p></details></article>`;
}
function renderConcepts() {
  const q = $('query').value.toLowerCase();
  const facts = run.facts.filter(f=>[f.name,f.definition,...f.values].join(' ').toLowerCase().includes(q));
  $('count').textContent = `${facts.length} candidate concepts`;
  $('concepts').innerHTML = facts.length ? facts.map(f=>`<button class="concept ${selected === f.id ? 'selected':''}" data-fact="${esc(f.id)}"><span class="family">${esc(f.family)}</span><b>${esc(f.name)}</b><p>${esc(f.definition)}</p><small>${f.evidence_ids.length} source assertions · ${f.values.length} observed values</small></button>`).join('') : '<p class="empty">No concepts match this search.</p>';
  document.querySelectorAll('[data-fact]').forEach(b=>b.onclick=()=>select(b.dataset.fact));
}
function select(id) {
  selected = id; renderConcepts();
  const f = run.facts.find(x=>x.id===id);
  $('detail').innerHTML = `<span class="tag">CANDIDATE · NOT VALIDATED</span><h2>${esc(f.name)}</h2><p>${esc(f.definition)}</p><h3>Observed values</h3><p>Extracted values, not a certified enumeration or entailment audit.</p><div class="chips">${f.values.map(v=>`<span class="chip">${esc(v)}</span>`).join('')}</div><h3>Source assertions</h3>${run.extractions.filter(e=>e.fact_id===id).map(proof).join('')}`;
}
async function load(id) {
  const r = await fetch('/api/runs/'+encodeURIComponent(id));
  if(!r.ok) throw Error('Could not load the experiment.');
  run = await r.json(); selected = null;
  $('notice').textContent = run.quality_notice + ` Status: ${run.status}.` + (run.error ? ` ${run.error}` : '');
  const m = run.metrics;
  $('stats').innerHTML = [[run.processed+'/'+run.rows.length,'reviews processed'],[run.facts.length,'candidate concepts'],[m.extractions,'extracted assertions'],[m.exact_spans,'exact source spans'],[money(m.cost),'reported API cost']].map(([v,l])=>`<div class="stat"><strong>${v}</strong><span>${l}</span></div>`).join('');
  renderConcepts(); if(run.facts.length) select(run.facts[0].id);
  $('assertions').innerHTML = run.extractions.map(proof).join('') || '<p class="empty">No assertions extracted yet.</p>';
  $('routes').innerHTML = Object.entries(m.routes).map(([key,n])=>`<div class="bar-row"><span>${esc(key)}</span><progress value="${n}" max="${m.extractions || 1}" aria-label="${esc(key)}"></progress><span>${n} · ${(100*n/(m.extractions||1)).toFixed(1)}%</span></div>`).join('');
  $('costs').innerHTML = `<p>Wall time: ${m.wall_seconds.toFixed(2)} s · API calls: ${m.calls} · cost awaiting confirmation: ${m.unknown_cost} calls (${money(m.reserved)} reserved).</p><p>Precision / recall: <b>not measured</b>. Source alignment is a structural check, not proof of factual correctness.</p><div class="table-wrap"><table><thead><tr><th>Stage</th><th>API calls</th><th>Reported cost</th><th>p50 / p95 latency</th></tr></thead><tbody>${Object.entries(m.stages).map(([k,s])=>`<tr><td>${esc(k)}</td><td>${s.calls}</td><td>${money(s.cost)}</td><td>${s.p50_ms === null ? '—' : s.p50_ms.toFixed(0)+' / '+s.p95_ms.toFixed(0)+' ms'}</td></tr>`).join('')}</tbody></table></div><p>Provider: ${esc(run.config.provider)} · embedding contract: ${esc(run.config.embedding_contract)}</p>`;
}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!==b.dataset.tab);document.querySelectorAll('[data-tab]').forEach(t=>t.classList.toggle('active',t===b));});
$('query').oninput=()=>run && renderConcepts();
$('runs').onchange=()=>load($('runs').value).catch(e=>$('notice').textContent=e.message);
$('download').onclick=()=>{if(!run)return; const url=URL.createObjectURL(new Blob([JSON.stringify(run,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`pilon-${run.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
(async()=>{try{const response=await fetch('/api/runs');if(!response.ok)throw Error('Local server unavailable.');const runs=await response.json();$('runs').innerHTML=runs.map(r=>`<option value="${esc(r.id)}">${esc(r.provider)} · ${esc(r.id)} · ${esc(r.status)}</option>`).join('');if(runs.length)await load(runs[0].id);else $('notice').textContent='No experiments yet. Run “pilon demo” in your terminal for an offline example.';}catch(e){$('notice').textContent=e.message;}})();
