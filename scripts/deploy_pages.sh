#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/render_site.py

git push origin main
sha="$(git subtree split --prefix public)"
git push origin "${sha}:refs/heads/gh-pages"
printf 'Published %s to GitHub Pages\n' "$sha"
