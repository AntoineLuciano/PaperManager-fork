/**
 * Prerender the demo for the host page (run under Node after `vite build --ssr`):
 *
 *   node dist-ssr/prerender.js <demo.json> <bundle URL> <data URL> <outDir> [<data dir>]
 *
 * Writes into outDir:
 *   fragment.html     the element's content: a declarative shadow root holding the whole demo
 *   pm-chat-demo.css  the stylesheet inside that shadow root (KaTeX, kchat.css, the widget's own)
 *   katex-fonts.css   KaTeX's @font-face rules, which must live in the document
 * Card stills' sizes are read from <data dir>/cards/sizes.json when it exists (width/height attributes).
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { Writable } from 'node:stream';
import { prerenderToNodeStream } from 'react-dom/static';
import kchatCss from '../../src/components/kchat/kchat.css?raw';
import katexCss from 'katex/dist/katex.min.css?raw';
import demoCss from './demo.css?inline';
import { where } from './config';
import { Widget, type Tab } from './View';

/** Tailwind's violets are oklch; restated in hex so the accent mapping finds them too. */
const VIOLETS = ':host{--color-violet-50:#f5f3ff;--color-violet-100:#ede9fe;--color-violet-200:#ddd6fe;'
  + '--color-violet-300:#c4b5fd;--color-violet-400:#a78bfa;--color-violet-500:#8b5cf6;--color-violet-600:#7c3aed;'
  + '--color-violet-700:#6d28d9;--color-violet-800:#5b21b6;--color-violet-900:#4c1d95;--color-violet-950:#2e1065}';

async function render(node: React.ReactNode): Promise<string> {
  // No progressive chunking: complete boundaries stay inline instead of being outlined behind a script.
  const { prelude } = await prerenderToNodeStream(node, { progressiveChunkSize: Number.POSITIVE_INFINITY });
  const chunks: Buffer[] = [];
  await new Promise<void>((resolve, reject) => {
    prelude.pipe(new Writable({
      write(c, _e, cb) { chunks.push(Buffer.from(c)); cb(); },
      final(cb) { resolve(); cb(); },
    })).on('error', reject);
  });
  return Buffer.concat(chunks).toString('utf8');
}

async function main() {
  const [dataPath, base, data, outDir, dataDir] = process.argv.slice(2);
  const { tabs } = JSON.parse(readFileSync(dataPath, 'utf8')) as { tabs: Tab[] };
  where.static = true;
  where.base = base;
  where.data = data;
  const sizes = dataDir && join(dataDir, 'cards', 'sizes.json');
  if (sizes && existsSync(sizes)) where.sizes = JSON.parse(readFileSync(sizes, 'utf8'));

  // The first pass resolves the lazily imported structure block; the second renders without
  // suspending, so the markup has no streaming boundaries or scripts.
  await render(<Widget tabs={tabs} />);
  const html = await render(<Widget tabs={tabs} />);
  if (/<script/i.test(html)) throw new Error('prerender still suspended somewhere');
  // KaTeX writes \min, \max, … as an <mi> plus an invisible function application inside a sub- or
  // superscript, which gives <msub> three children; Firefox reports that as invalid MathML.
  const mathml = html.replace(/(<mi>[A-Za-z]+<\/mi><mo>\u2061<\/mo>)(<\/msub>|<\/msup>)/g, '<mrow>$1</mrow>$2');
  const faces = katexCss.match(/@font-face\{[^}]*\}/g) ?? [];
  const fonts = faces.map((f) => {
    const woff2 = /url\(fonts\/([\w-]+\.woff2)\)\s*format\("woff2"\)/.exec(f);
    return woff2 ? f.replace(/src:[^;}]*/, `src:url(${base}fonts/${woff2[1]}) format("woff2")`) : '';
  }).join('\n');
  writeFileSync(join(outDir, 'katex-fonts.css'), fonts);
  writeFileSync(join(outDir, 'pm-chat-demo.css'), `${katexCss.replace(/@font-face\{[^}]*\}/g, '')}\n${kchatCss}\n${demoCss}\n${VIOLETS}\n`);
  // One line, no blank lines: the host page may be Markdown.
  const fragment = `<link rel="stylesheet" href="${base}katex-fonts.css">`
    + `<template shadowrootmode="open"><link rel="stylesheet" href="${base}pm-chat-demo.css">`
    + `<div class="pmd-root">${mathml}</div></template>`;
  writeFileSync(join(outDir, 'fragment.html'), fragment.replace(/\n+/g, '&#10;'));
}

main().catch((e) => { console.error(e); process.exit(1); });
