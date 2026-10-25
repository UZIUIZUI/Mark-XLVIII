const $ = s => document.querySelector(s);
let token = localStorage.getItem('cm_token') || '';
let state = null, timer = null;
const PLATS = {instagram: '📸 Instagram', tiktok: '🎵 TikTok'};

function toast(m) { const t = $('#toast'); t.textContent = m; t.style.display = 'block'; setTimeout(() => t.style.display = 'none', 3500); }
async function api(path, opt = {}) {
  opt.headers = Object.assign({'X-Token': token}, opt.headers || {});
  if (opt.json) { opt.body = JSON.stringify(opt.json); opt.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(path, opt);
  if (r.status === 401) { token = prompt('App-Token (steht im Server-Log):') || ''; localStorage.setItem('cm_token', token); return api(path, opt); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const li = a => (a || []).map(x => `<li>${esc(x)}</li>`).join('');

// Tabs
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.id === 'tab-' + b.dataset.tab));
  refresh();
});

// Plattform-Chips
function chips(el, sel) {
  el.innerHTML = '';
  for (const [k, v] of Object.entries(PLATS)) {
    const c = document.createElement('button'); c.className = 'chip' + (sel.includes(k) ? ' on' : ''); c.textContent = v; c.dataset.k = k;
    c.onclick = () => c.classList.toggle('on'); el.appendChild(c);
  }
}
const picked = el => [...el.querySelectorAll('.chip.on')].map(c => c.dataset.k);

// Analyse
$('#files').onchange = e => $('#fileLabel').textContent = e.target.files.length ? `✅ ${e.target.files.length} Datei(en) gewählt` : '📎 Bilder / Videos wählen';
$('.drop').onclick = () => $('#files').click();
$('#btnAnalyze').onclick = async () => {
  const f = $('#files').files; if (!f.length) return toast('Erst Dateien wählen');
  const fd = new FormData(); [...f].forEach(x => fd.append('files', x)); fd.append('note', $('#note').value);
  $('#btnAnalyze').disabled = true; toast('Lade hoch…');
  try { await api('/api/analyze', {method: 'POST', body: fd}); $('#files').value = ''; $('#fileLabel').textContent = '📎 Bilder / Videos wählen'; toast('Analyse läuft'); }
  catch (e) { toast(e.message); }
  $('#btnAnalyze').disabled = false; refresh();
};
function renderAnalyses(list) {
  $('#analyses').innerHTML = list.map(a => {
    if (a.status === 'failed') return `<div class="card"><span class="pill err">Fehler</span> ${esc(a.error)}<button class="small danger" onclick="delA('${a.id}')">Löschen</button></div>`;
    if (a.status !== 'done') return `<div class="card"><span class="spin">⏳</span> Analyse läuft… (${esc((a.files || []).length)} Datei(en))</div>`;
    const r = a.result;
    return `<div class="card"><div class="score">${esc(r.score)}<small class="muted"> /100 Viral-Potenzial</small></div>
      <p>${esc(r.summary)}</p><p class="muted"><b>Hook:</b> ${esc(r.hook)}</p>
      <b>Stärken</b><ul>${li(r.strengths)}</ul><b>Schwächen</b><ul>${li(r.weaknesses)}</ul>
      <b>Ideen</b>${(r.ideas || []).map(i => `<button class="small" onclick="fromIdea('${esc(i.topic).replace(/'/g, '’')}','${a.id}')">🎬 ${esc(i.topic)}</button>`).join('')}
      <p class="cap">${esc((r.hashtags || []).join(' '))}</p>
      <button class="small danger" onclick="delA('${a.id}')">Löschen</button></div>`;
  }).join('') || '<p class="muted">Noch keine Analysen.</p>';
}
window.delA = async id => { await api('/api/analyses/' + id, {method: 'DELETE'}); refresh(); };
window.fromIdea = async (topic, aid) => {
  const a = (await api('/api/analyses')).find(x => x.id === aid);
  try { await api('/api/posts', {method: 'POST', json: {topic, style: a?.result?.style_prompt, platforms: state.settings.platforms}}); toast('Video wird erzeugt → Studio'); }
  catch (e) { toast(e.message); }
};

// Erstellen
$('#btnCreate').onclick = async () => {
  $('#btnCreate').disabled = true; toast('KI schreibt Skript…');
  try {
    await api('/api/posts', {method: 'POST', json: {topic: $('#topic').value, platforms: picked($('#platChips')), publish: $('#pubAfter').checked}});
    $('#topic').value = ''; toast('Video wird erzeugt – siehe Studio (dauert ein paar Minuten)');
  } catch (e) { toast(e.message); }
  $('#btnCreate').disabled = false;
};

// Studio
const STAT = {queued: '⏳ Warteschlange', generating: '🎞️ Wird generiert…', ready: '✅ Fertig', publishing: '📤 Wird gepostet…', published: '🚀 Gepostet', failed: '❌ Fehler'};
function renderPosts(list) {
  $('#posts').innerHTML = list.map(p => {
    const busy = ['queued', 'generating', 'publishing'].includes(p.status);
    const res = Object.entries(p.results || {}).map(([k, v]) => `<span class="pill ${v.ok ? 'ok' : 'err'}">${PLATS[k] || k}: ${v.ok ? 'OK' : esc(v.error)}</span>`).join('');
    return `<div class="card"><b>${esc(p.topic)}</b> ${p.source === 'autopilot' ? '<span class="pill">🤖</span>' : ''}<br>
      <span class="pill">${STAT[p.status] || p.status}</span>${res}
      ${p.upload_path ? `<video controls playsinline preload="metadata" src="/media/${p.id}?t=${token}"></video>` : (busy ? '<p class="muted"><span class="spin">⏳</span> Veo rendert…</p>' : '')}
      <div class="cap">${esc(p.caption)}\n${esc((p.hashtags || []).join(' '))}</div>
      ${p.error ? `<p class="muted">ℹ️ ${esc(p.error)}</p>` : ''}
      ${p.upload_path ? `<button class="small primary" onclick="pub('${p.id}')">🚀 Posten</button>
        <button class="small" onclick="share('${p.id}')">📲 Teilen</button>
        <a href="/media/${p.id}?kind=master&t=${token}"><button class="small">⬇️ 4K</button></a>` : ''}
      <button class="small danger" onclick="delP('${p.id}')">🗑️</button></div>`;
  }).join('') || '<p class="muted">Noch nichts erzeugt.</p>';
}
window.pub = async id => { try { await api(`/api/posts/${id}/publish`, {method: 'POST', json: {}}); toast('Wird gepostet…'); } catch (e) { toast(e.message); } refresh(); };
window.delP = async id => { if (confirm('Löschen?')) { await api('/api/posts/' + id, {method: 'DELETE'}); refresh(); } };
window.share = async id => {  // Handy-Teilen-Menü: direkt in die TikTok-/Instagram-App
  const blob = await (await fetch(`/media/${id}?t=${token}`)).blob();
  const file = new File([blob], 'video.mp4', {type: 'video/mp4'});
  if (navigator.canShare?.({files: [file]})) navigator.share({files: [file]}).catch(() => {});
  else toast('Teilen nicht unterstützt – nutze ⬇️');
};

// Autopilot
$('#btnSave').onclick = async () => {
  state.settings = await api('/api/settings', {method: 'PUT', json: {
    autopilot: $('#apOn').checked, niche: $('#apNiche').value, interval_hours: +$('#apInterval').value || 12,
    videos_per_run: +$('#apCount').value || 1, platforms: picked($('#apPlat')), auto_publish: $('#apPublish').checked}});
  toast('Gespeichert');
};
$('#btnRunNow').onclick = async () => { await api('/api/autopilot/run', {method: 'POST'}); toast('Lauf gestartet → Studio'); };
function renderSettings() {
  const s = state.settings;
  $('#apOn').checked = s.autopilot; $('#apNiche').value = s.niche; $('#apInterval').value = s.interval_hours;
  $('#apCount').value = s.videos_per_run; $('#apPublish').checked = s.auto_publish;
  chips($('#apPlat'), s.platforms); chips($('#platChips'), s.platforms);
  const p = state.platforms, d = x => x ? '<span class="pill ok">verbunden</span>' : '<span class="pill err">nicht konfiguriert</span>';
  $('#platStatus').innerHTML = `<h2>Status</h2><p>KI (Gemini/Veo) ${d(p.ai)}</p><p>Instagram ${d(p.instagram)}</p><p>TikTok ${d(p.tiktok)}</p>
    <p class="muted">Auflösung: ${esc(state.resolution)}. Zugänge in <code>.env</code> eintragen.</p>`;
  $('#badge').innerHTML = state.mock ? '<span class="pill err">DEMO</span>' : '';
}

async function refresh() {
  try {
    if (!state) { state = await api('/api/state'); renderSettings(); }
    const [a, p] = await Promise.all([api('/api/analyses'), api('/api/posts')]);
    renderAnalyses(a); renderPosts(p);
    const busy = a.some(x => ['queued', 'running'].includes(x.status)) || p.some(x => ['queued', 'generating', 'publishing'].includes(x.status));
    clearTimeout(timer); if (busy) timer = setTimeout(refresh, 5000);
  } catch (e) { toast(e.message); }
}
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
refresh();
