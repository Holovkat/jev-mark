/* Adds navigation and explicit caller metadata to gateway-served portal pages. */
(() => {
  if (document.getElementById('jev-analytics-link')) return;
  const link = document.createElement('a');
  link.id = 'jev-analytics-link'; link.href = '/analytics'; link.textContent = 'Service analytics ↗';
  link.style.cssText = 'position:fixed;bottom:16px;right:18px;z-index:1000;padding:10px 16px;border:1px solid #60a5fa80;border-radius:999px;background:#101b2e;color:#e8f0ff;font:600 13px system-ui;text-decoration:none;box-shadow:0 5px 24px #0005';
  document.body.append(link);
  if (!location.pathname.startsWith('/workbench')) return;
  const original = window.fetch.bind(window);
  window.fetch = (input, init) => {
    try {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      const method = (init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (url.origin === location.origin && url.pathname === '/v1/decision' && method === 'POST') {
        const headers = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined));
        if (!headers.has('X-JEV-Client')) headers.set('X-JEV-Client', 'workbench');
        if (!headers.has('X-JEV-Purpose')) headers.set('X-JEV-Purpose', 'interactive-test');
        init = { ...init, headers };
      }
    } catch { /* Metadata must never stop an existing request. */ }
    return original(input, init);
  };
})();
