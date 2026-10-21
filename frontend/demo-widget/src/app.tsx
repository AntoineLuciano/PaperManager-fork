/**
 * Mounts the demo in the shadow root the loader made: the app's stylesheets (KaTeX, kchat.css)
 * and the widget's own, then the React tree.
 */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import kchatCss from '../../src/components/kchat/kchat.css?raw';
import katexCss from 'katex/dist/katex.min.css?raw';
import demoCss from './demo.css?inline';
import Demo from './Demo';
import { where } from './config';

/** KaTeX's @font-face rules must live in the document (fonts declared in a shadow root are ignored). */
function splitKatex(css: string, base: string): { fonts: string; rules: string } {
  const faces = css.match(/@font-face\{[^}]*\}/g) ?? [];
  const fonts = faces.map((f) => {
    const woff2 = /url\(fonts\/([\w-]+\.woff2)\)\s*format\("woff2"\)/.exec(f);
    return woff2 ? f.replace(/src:[^;}]*/, `src:url(${base}fonts/${woff2[1]}) format("woff2")`) : '';
  }).join('\n');
  return { fonts, rules: css.replace(/@font-face\{[^}]*\}/g, '') };
}

export function mount(host: HTMLElement, root: ShadowRoot, at: { base: string; data: string }) {
  Object.assign(where, at);
  const katex = splitKatex(katexCss, at.base);
  if (!document.getElementById('pm-chat-demo-fonts')) {
    const s = document.createElement('style');
    s.id = 'pm-chat-demo-fonts';
    s.textContent = katex.fonts;
    document.head.appendChild(s);
  }
  root.innerHTML = '';
  const style = document.createElement('style');
  style.textContent = `${katex.rules}\n${kchatCss}\n${demoCss}`;
  const box = document.createElement('div');
  box.className = 'pmd-root';
  root.append(style, box);
  host.setAttribute('data-pm-chat-demo-ready', '');
  createRoot(box).render(<StrictMode><Demo root={root} /></StrictMode>);
}
