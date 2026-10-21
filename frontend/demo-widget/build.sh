#!/usr/bin/env bash
# Build the Knowledge Chat demo: the browser bundle, then the prerendered page fragment.
#
#   demo-widget/build.sh <demo.json> <target dir> <target URL> [<include file>]
#
#   demo.json    written by export_demo.py
#   target dir   where the bundle goes (a data/ directory next to it is kept: data/cards/ holds
#                the card stills and their sizes.json, data/structures/ the coordinates)
#   target URL   the URL of the target dir on the site, e.g. /assets/pm-chat-demo/
#   include file the fragment for the page (wrapped in {% raw %} for Jekyll when it ends in .html)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
demo="$(realpath "$1")"; target="$2"; url="$3"; include="${4:-}"
cd "$here/.."
npx vite build --config demo-widget/vite.config.ts
npx vite build --config demo-widget/vite.config.ts --ssr
node "$here/dist-ssr/prerender.mjs" "$demo" "$url" "${url}data/" "$here/dist" "$target/data"
mkdir -p "$target"
find "$target" -mindepth 1 -maxdepth 1 ! -name data -exec rm -rf {} +
cp -R "$here/dist/." "$target/"
rm -f "$target/fragment.html"
if [ -n "$include" ]; then
  { printf '{%% raw %%}'; cat "$here/dist/fragment.html"; printf '{%% endraw %%}\n'; } > "$include"
  echo "fragment written to $include"
fi
echo "bundle copied to $target"
