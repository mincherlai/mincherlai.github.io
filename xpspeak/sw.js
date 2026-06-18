/* Service worker: cache the app shell so XPSPeak opens offline after first load.
   The Pyodide/scipy wasm is large and served from a CDN; the browser's HTTP
   cache handles it, while this SW guarantees the local app shell is available. */
const CACHE = "xpspeak-v1";
const SHELL = [
  "./", "./index.html", "./style.css", "./app.js", "./bridge.py",
  "./manifest.webmanifest",
  "./icons/icon-192.png", "./icons/icon-512.png", "./icons/apple-touch-icon.png",
  "./samples/As3d_demo.prn", "./samples/Ag3d_demo.asc",
  "./xpspeak/__init__.py", "./xpspeak/functions.py", "./xpspeak/background.py",
  "./xpspeak/model.py", "./xpspeak/fitting.py", "./xpspeak/io_import.py",
  "./xpspeak/io_native.py",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Same-origin app shell: cache-first. CDN (Pyodide/Plotly): let the network +
  // browser cache handle it (don't intercept cross-origin range requests).
  if (url.origin === location.origin) {
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
  }
});
