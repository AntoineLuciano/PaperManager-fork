/**
 * Loader for the Knowledge Chat demo widget. Small and free of React: it gives every
 * `[data-pm-chat-demo]` element a shadow root (so the host page's styles and the widget's
 * stay apart), keeps the element's own content (a placeholder) visible through a slot, and
 * loads the app only when the element comes near the viewport.
 */
const base = new URL('.', import.meta.url).href;

function boot(el: HTMLElement) {
  if (el.shadowRoot) return;
  const root = el.attachShadow({ mode: 'open' });
  root.innerHTML = '<slot></slot>';
  const data = new URL(el.dataset.pmChatDemo || './', document.baseURI).href;
  const start = () => import('./app').then((m) => m.mount(el, root, { base, data }));
  if (!('IntersectionObserver' in window)) { start(); return; }
  const io = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) { io.disconnect(); start(); }
  }, { rootMargin: '800px 0px' });
  io.observe(el);
}

function scan() {
  document.querySelectorAll<HTMLElement>('[data-pm-chat-demo]').forEach(boot);
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scan);
else scan();
