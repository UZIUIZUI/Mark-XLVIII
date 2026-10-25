// Minimaler Service Worker: macht die App installierbar, cached nur die Shell.
const C='cm-v1',SHELL=['/','/style.css','/app.js','/icon.svg'];
self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(SHELL))));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);
  if(u.pathname.startsWith('/api')||u.pathname.startsWith('/media'))return;
  e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));});
