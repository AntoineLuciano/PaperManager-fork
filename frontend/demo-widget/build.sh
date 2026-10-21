#!/usr/bin/env bash
# Build the Knowledge Chat demo widget and, given a directory, copy the bundle there.
#   demo-widget/build.sh                      -> demo-widget/dist
#   demo-widget/build.sh ../site/assets/pm-chat-demo
# The conversation data (export_demo.py) is not part of the bundle; it goes wherever the
# embedding element's data-pm-chat-demo attribute points.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here/.."
npx vite build --config demo-widget/vite.config.ts
if [ $# -ge 1 ]; then
  mkdir -p "$1"
  # Replace the previous bundle but keep a data/ directory that lives next to it.
  find "$1" -mindepth 1 -maxdepth 1 ! -name data -exec rm -rf {} +
  cp -R "$here/dist/." "$1/"
  echo "copied to $1"
fi
