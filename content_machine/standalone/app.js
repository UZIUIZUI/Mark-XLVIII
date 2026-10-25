// Content-Maschine (standalone): laeuft komplett im Handy, ruft Gemini/Veo direkt auf.
const $ = s => document.querySelector(s);
const API = 'https://generativelanguage.googleapis.com/v1beta';
const TEXT_MODEL = 'gemini-2.5-flash';
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const li = a => (a || []).map(x => `<li>${esc(x)}</li>`).join('');
const toast = m => { const t = $('#toast'); t.textContent = m; t.style.display = 'block'; clearTimeout(toast.t); toast.t = setTimeout(() => t.style.display = 'none', 3500); };

// ---------- Speicher (IndexedDB: Daten + Video-Blobs)
const dbp = new Promise((res, rej) => { const r = indexedDB.open('cm', 1); r.onupgradeneeded = () => r.result.createObjectStore('kv'); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
const tx = async (mode, fn) => { const d = await dbp; return new Promise((res, rej) => { const t = d.transaction('kv', mode), q = fn(t.objectStore('kv')); t.oncomplete = () => res(q?.result); t.onerror = () => rej(t.error); }); };
const kvGet = (k, d) => tx('readonly', s => s.get(k)).then(v => v ?? d);
const kvSet = (k, v) => tx('readwrite', s => s.put(v, k));
const kvDel = k => tx('readwrite', s => s.delete(k));

let S = {key: '', niche: '', res: '4k', vmodel: 'veo-3.1-generate-preview', ap: false, apInterval: 120, apMax: 3, lastRun: 0, apCount: 0};
let analyses = [], posts = [];
const save = () => Promise.all([kvSet('settings', S), kvSet('analyses', analyses), kvSet('posts', posts)]);

// ---------- Gemini
async function gfetch(path, body, method = 'POST') {
  if (!S.key) throw new Error('Erst API-Key unter „Autopilot“ eintragen');
  const r = await fetch(API + path, {method, headers: {'x-goog-api-key': S.key, 'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error?.message || `HTTP ${r.status}`);
  return j;
}
const parseJson = t => JSON.parse(t.trim().replace(/^```(json)?|```$/g, ''));
async function gjson(parts, temperature = 0.7) {
  const j = await gfetch(`/models/${TEXT_MODEL}:generateContent`, {contents: [{parts}], generationConfig: {responseMimeType: 'application/json', temperature}});
  return parseJson(j.candidates[0].content.parts[0].text);
}
const b64 = f => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result.split(',')[1]); r.onerror = rej; r.readAsDataURL(f); });

const ANALYZE = `Du bist Senior-Stratege fuer TikTok und Instagram Reels. Analysiere das Material und antworte NUR als JSON:
{"summary":"2 Saetze","score":0-100,"hook":"Bewertung der ersten 2 Sekunden","strengths":["..."],"weaknesses":["..."],
"style_prompt":"wiederverwendbare Stilbeschreibung (Licht, Farben, Kamera, Tempo, Stimmung) fuer KI-Video, englisch",
"ideas":[{"topic":"...","hook":"..."}],"hashtags":["..."]}
Deutsch (style_prompt englisch). 3 ideas.`;
const IDEA = (niche, topic, style, done) => `Du bist Content-Produzent fuer TikTok und Instagram Reels (9:16, 8-Sekunden-Clip mit Ton).
Nische: ${niche || 'frei waehlbar'}
Thema-Wunsch: ${topic || 'waehle selbst ein starkes Thema'}
Gelernter Stil: ${style || 'keiner'}
Schon produziert (nicht wiederholen): ${done || 'nichts'}
Antworte NUR als JSON: {"topic":"...","hook":"...","video_prompt":"detaillierter englischer Veo-Prompt: Szene, Kamera, Licht, Bewegung, Ton/Dialog, 9:16, cinematic","caption":"Deutsch, Hook in Zeile 1, kurzer CTA","hashtags":["#..","#..","#..","#..","#.."]}`;

// ---------- Analyse
$('#files').onchange = e => $('#fileLabel').textContent = e.target.files.length ? `✅ ${e.target.files.length} Datei(en)` : '📎 Bilder / Videos wählen';
$('.drop').onclick = () => $('#files').click();
$('#btnAnalyze').onclick = async () => {
  const files = [...$('#files').files]; if (!files.length) return toast('Erst Dateien wählen');
  if (files.reduce((a, f) => a + f.size, 0) > 15e6) return toast('Zusammen max. 15 MB – kürzeres Video oder weniger Dateien');
  const a = {id: Date.now().toString(36), status: 'running', n: files.length, created: Date.now()};
  analyses.unshift(a); render(); $('#btnAnalyze').disabled = true;
  try {
    const parts = [];
    for (const f of files) parts.push({inline_data: {mime_type: f.type || 'image/jpeg', data: await b64(f)}});
    parts.push({text: ANALYZE + ($('#note').value ? `\nZusatzinfo: ${$('#note').value}` : '')});
    a.result = await gjson(parts); a.status = 'done';
    $('#files').value = ''; $('#fileLabel').textContent = '📎 Bilder / Videos wählen';
  } catch (e) { a.status = 'failed'; a.error = e.message; }
  $('#btnAnalyze').disabled = false; await save(); render();
};
const learnedStyle = () => analyses.filter(a => a.status === 'done').slice(0, 5).map(a => a.result.style_prompt).filter(Boolean).join(' | ');

// ---------- Video
async function renderVideo(prompt, onStep) {
  const chain = [S.res, ...['1080p', '720p'].filter(r => r !== S.res)];
  let op, used, lastErr;
  for (const res of chain) {
    try {
      op = await gfetch(`/models/${S.vmodel}:predictLongRunning`, {instances: [{prompt}], parameters: {aspectRatio: '9:16', resolution: res, durationSeconds: 8}});
      used = res; break;
    } catch (e) { lastErr = e; }
  }
  if (!op) throw new Error('Veo-Start fehlgeschlagen: ' + lastErr.message);
  while (!op.done) { await new Promise(r => setTimeout(r, 10000)); op = await gfetch('/' + op.name, null, 'GET'); onStep?.(); }
  if (op.error) throw new Error(op.error.message);
  const v = op.response?.generateVideoResponse;
  const uri = v?.generatedSamples?.[0]?.video?.uri;
  if (!uri) throw new Error(v?.raiMediaFilteredReasons?.[0] || 'Kein Video geliefert (Inhaltsfilter?). Anderes Thema probieren.');
  const r = await fetch(uri, {headers: {'x-goog-api-key': S.key}});
  if (!r.ok) throw new Error('Download fehlgeschlagen: HTTP ' + r.status);
  return {blob: await r.blob(), res: used};
}
async function produce(topic, source = 'manual') {
  const done = posts.slice(0, 15).map(p => p.topic).join(', ');
  const idea = await gjson([{text: IDEA(S.niche, topic, learnedStyle(), done)}], 1.0);
  const p = {id: Date.now().toString(36), created: Date.now(), source, status: 'generating', topic: idea.topic, caption: idea.caption, hashtags: idea.hashtags || [], prompt: idea.video_prompt};
  posts.unshift(p); await save(); render();
  try {
    const {blob, res} = await renderVideo(p.prompt);
    await kvSet('video:' + p.id, blob); p.status = 'ready'; p.res = res;
  } catch (e) { p.status = 'failed'; p.error = e.message; }
  await save(); render();
}
$('#btnCreate').onclick = async () => {
  $('#btnCreate').disabled = true; toast('KI schreibt Skript… Video dauert 1–3 Min. (siehe Studio)');
  try { const t = $('#topic').value; $('#topic').value = ''; document.querySelector('[data-tab=studio]').click(); await produce(t); }
  catch (e) { toast(e.message); }
  $('#btnCreate').disabled = false;
};

// ---------- Studio
const STAT = {generating: '🎞️ Wird generiert…', ready: '✅ Fertig', failed: '❌ Fehler'};
const urls = {};
async function videoUrl(id) { return urls[id] ||= URL.createObjectURL(await kvGet('video:' + id)); }
async function render() {
  $('#analyses').innerHTML = analyses.map(a => {
    if (a.status === 'failed') return `<div class="card"><span class="pill err">Fehler</span> ${esc(a.error)}<br><button class="small danger" onclick="delA('${a.id}')">Löschen</button></div>`;
    if (a.status !== 'done') return `<div class="card"><span class="spin">⏳</span> Analyse läuft…</div>`;
    const r = a.result;
    return `<div class="card"><div class="score">${esc(r.score)}<small class="muted"> /100 Viral-Potenzial</small></div><p>${esc(r.summary)}</p>
      <p class="muted"><b>Hook:</b> ${esc(r.hook)}</p><b>Stärken</b><ul>${li(r.strengths)}</ul><b>Schwächen</b><ul>${li(r.weaknesses)}</ul>
      <b>Ideen</b><br>${(r.ideas || []).map((i, n) => `<button class="small" onclick="fromIdea('${a.id}',${n})">🎬 ${esc(i.topic)}</button>`).join('')}
      <p class="cap">${esc((r.hashtags || []).join(' '))}</p><button class="small danger" onclick="delA('${a.id}')">Löschen</button></div>`;
  }).join('') || '<p class="muted">Noch keine Analysen.</p>';
  const html = [];
  for (const p of posts) {
    const v = p.status === 'ready' ? `<video controls playsinline src="${await videoUrl(p.id)}"></video>` : (p.status === 'generating' ? '<p class="muted"><span class="spin">⏳</span> Veo rendert… App offen lassen</p>' : '');
    html.push(`<div class="card"><b>${esc(p.topic)}</b> ${p.source === 'autopilot' ? '<span class="pill">🤖</span>' : ''}<br><span class="pill">${STAT[p.status]}</span>${p.res ? `<span class="pill">${p.res}</span>` : ''}${v}
      <div class="cap">${esc(p.caption)}\n${esc(p.hashtags.join(' '))}</div>${p.error ? `<p class="muted">ℹ️ ${esc(p.error)}</p>` : ''}
      ${p.status === 'ready' ? `<button class="small primary" onclick="share('${p.id}')">📲 Posten (TikTok / Instagram)</button><button class="small" onclick="copyCap('${p.id}')">📋 Caption</button><button class="small" onclick="dl('${p.id}')">⬇️ Speichern</button>` : ''}
      <button class="small danger" onclick="delP('${p.id}')">🗑️</button></div>`);
  }
  $('#posts').innerHTML = html.join('') || '<p class="muted">Noch nichts erzeugt.</p>';
}
const fullCap = p => `${p.caption}\n\n${p.hashtags.join(' ')}`;
window.delA = async id => { analyses = analyses.filter(a => a.id !== id); await save(); render(); };
window.delP = async id => { if (!confirm('Löschen?')) return; posts = posts.filter(p => p.id !== id); await kvDel('video:' + id); await save(); render(); };
window.fromIdea = async (aid, n) => {
  const i = analyses.find(a => a.id === aid).result.ideas[n]; document.querySelector('[data-tab=studio]').click();
  try { await produce(i.topic); } catch (e) { toast(e.message); }
};
window.copyCap = async id => { await navigator.clipboard.writeText(fullCap(posts.find(p => p.id === id))); toast('Caption kopiert – in TikTok/Instagram einfügen'); };
window.share = async id => {  // Teilen-Menue -> TikTok / Instagram App waehlen
  const p = posts.find(x => x.id === id), file = new File([await kvGet('video:' + id)], `${p.topic.slice(0, 30)}.mp4`, {type: 'video/mp4'});
  try { await navigator.clipboard.writeText(fullCap(p)); } catch {}
  if (navigator.canShare?.({files: [file]})) navigator.share({files: [file], text: fullCap(p)}).catch(() => {});
  else toast('Teilen nicht unterstützt – nutze „Speichern“');
};
window.dl = async id => { const a = document.createElement('a'); a.href = await videoUrl(id); a.download = id + '.mp4'; a.click(); };

// ---------- Einstellungen & Autopilot
function fillSettings() {
  $('#apiKey').value = S.key; $('#niche').value = S.niche; $('#res').value = S.res; $('#vmodel').value = S.vmodel;
  $('#apOn').checked = S.ap; $('#apInterval').value = S.apInterval; $('#apMax').value = S.apMax;
  $('#badge').innerHTML = S.key ? '' : '<span class="pill err">Key fehlt</span>';
}
$('#btnSave').onclick = async () => {
  Object.assign(S, {key: $('#apiKey').value.trim(), niche: $('#niche').value, res: $('#res').value, vmodel: $('#vmodel').value.trim()});
  await save(); fillSettings(); toast('Gespeichert');
};
$('#apOn').onchange = $('#apInterval').onchange = $('#apMax').onchange = async () => {
  Object.assign(S, {ap: $('#apOn').checked, apInterval: +$('#apInterval').value || 120, apMax: +$('#apMax').value || 1});
  if (S.ap) { S.apCount = 0; try { window.wl = await navigator.wakeLock?.request('screen'); } catch {} }
  await save(); tickStatus();
};
async function autoRun() {
  try { S.lastRun = Date.now(); S.apCount++; await save(); await produce('', 'autopilot'); } catch (e) { toast('Autopilot: ' + e.message); }
}
$('#btnRunNow').onclick = () => { document.querySelector('[data-tab=studio]').click(); autoRun(); };
function tickStatus() {
  $('#apStatus').textContent = S.ap ? `Aktiv · ${S.apCount}/${S.apMax} Videos · nächstes in ${Math.max(0, Math.round((S.lastRun + S.apInterval * 6e4 - Date.now()) / 6e4))} Min.` : 'Aus';
}
setInterval(() => {
  tickStatus();
  if (S.ap && S.apCount < S.apMax && !posts.some(p => p.status === 'generating') && Date.now() - S.lastRun >= S.apInterval * 6e4) autoRun();
}, 15000);

// ---------- Tabs & Start
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.id === 'tab-' + b.dataset.tab));
});
(async () => {
  S = {...S, ...await kvGet('settings', {})}; analyses = await kvGet('analyses', []); posts = await kvGet('posts', []);
  // Abgebrochene Jobs (App wurde geschlossen) als Fehler markieren
  [...analyses, ...posts].forEach(x => { if (['running', 'generating'].includes(x.status)) { x.status = 'failed'; x.error = 'Abgebrochen (App wurde geschlossen)'; } });
  fillSettings(); render(); tickStatus();
  if (!S.key) document.querySelector('[data-tab=auto]').click();
  navigator.storage?.persist?.();
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
})();
