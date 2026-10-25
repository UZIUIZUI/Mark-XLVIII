const C='cm-sa-v1',SHELL=['./','./style.css','./app.js','./icon.svg'];
self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(SHELL))));
self.addEventListener('fetch',e=>{if(new URL(e.request.url).origin!==location.origin)return;
  e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));});
