/**
 * Knowledge Chat demo widget: a read-only, embeddable replay of recorded conversations that
 * renders with the app's own components (Markdown, concept cards, structure cards, branch lane).
 *
 *   npx vite build --config demo-widget/vite.config.ts      (from frontend/)
 *   demo-widget/build.sh <target dir>                        (build and copy)
 *
 * Output (demo-widget/dist): pm-chat-demo.js (a small loader, no React), chunks/ (the app,
 * loaded when the widget nears the viewport), fonts/ (KaTeX), vendor/3Dmol-min.js (BSD-3).
 * Nothing is fetched from another host. Embed with
 *
 *   <div data-pm-chat-demo="/path/to/data/"></div>
 *   <script type="module" src="/path/to/pm-chat-demo.js"></script>
 *
 * where the data directory holds manifest.json, one JSON per conversation and
 * structures/*.json.gz, as written by export_demo.py.
 */
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
/**
 * The app's components import their stylesheets for the document; the widget renders in a
 * shadow root and adds the same sheets there itself, so those imports become empty modules.
 */
function dropComponentCss(): Plugin {
  return {
    name: 'pm-demo-drop-component-css',
    enforce: 'pre',
    resolveId(id, importer) {
      if (!importer || importer.startsWith(here) || id.includes('?') || !id.endsWith('.css')) return null;
      return '\0pm-demo-empty-css';
    },
    load(id) {
      return id === '\0pm-demo-empty-css' ? 'export {}' : null;
    },
  };
}

/** KaTeX's woff2 fonts and the vendored 3Dmol.js, copied next to the bundle. */
function copyStatic(): Plugin {
  return {
    name: 'pm-demo-static',
    generateBundle() {
      const fonts = resolve(here, '../node_modules/katex/dist/fonts');
      for (const f of readdirSync(fonts).filter((n) => n.endsWith('.woff2'))) {
        this.emitFile({ type: 'asset', fileName: `fonts/${f}`, source: readFileSync(resolve(fonts, f)) });
      }
      const vendor = resolve(here, '../public/vendor/3dmol');
      this.emitFile({ type: 'asset', fileName: 'vendor/3Dmol-min.js', source: readFileSync(resolve(vendor, '3Dmol-min.js')) });
      this.emitFile({ type: 'asset', fileName: 'vendor/3Dmol-LICENSE.txt', source: readFileSync(resolve(vendor, 'LICENSE')) });
      // Licences of what the bundle contains (the minifier drops their headers).
      const notice = [
        'The Knowledge Chat demo widget is part of PaperManager. Its bundle includes:',
        '- concept views adapted from Get It. (https://github.com/beltromatti/get-it), Apache-2.0',
        '- 3Dmol.js in vendor/ (BSD-3-Clause, see vendor/3Dmol-LICENSE.txt)',
        ...['react', 'react-dom', 'katex', 'highlight.js'].map((p) => {
          const text = readFileSync(resolve(here, `../node_modules/${p}/LICENSE`), 'utf8');
          return `\n==== ${p} ====\n${text}`;
        }),
      ].join('\n');
      this.emitFile({ type: 'asset', fileName: 'THIRD-PARTY-LICENSES.txt', source: notice });
    },
  };
}

export default defineConfig({
  root: here,
  base: './',
  plugins: [dropComponentCss(), react(), tailwindcss(), copyStatic()],
  resolve: {
    alias: [
      // The API client is replaced by the static data the widget ships with.
      { find: /^.*\/api\/client$/, replacement: resolve(here, 'src/client.ts') },
      // Fewer highlight.js grammars than the app's set.
      { find: /^lowlight$/, replacement: resolve(here, 'src/lowlight.ts') },
      // Structure cards: coordinates come from the widget's data directory.
      { find: /^\.\/structure\/StructureBlock$/, replacement: resolve(here, 'src/StructureBlock.tsx') },
    ],
  },
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: resolve(here, 'dist'),
    emptyOutDir: true,
    target: 'es2022',
    cssCodeSplit: false,
    modulePreload: false,
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      input: resolve(here, 'src/entry.ts'),
      output: {
        format: 'es',
        entryFileNames: 'pm-chat-demo.js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
  server: { fs: { allow: [resolve(here, '..')] } },
});
