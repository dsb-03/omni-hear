#!/bin/bash
# Copies the landing page from site/ into docs/ (the GitHub Pages root,
# which also hosts the APT repo). docs/ is never edited by hand; run this
# after changing site/, and it also runs from update-apt-repo.sh.
#
# Usage: ./scripts/sync-site.sh
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE_DIR="$REPO_ROOT/site"
DOCS_DIR="$REPO_ROOT/docs"

mkdir -p "$DOCS_DIR"
# Only the site's own files; never touches dists/, pool/ or pubkey.gpg.
for f in "$SITE_DIR"/*; do
    cp -r "$f" "$DOCS_DIR/"
done
# Serve files as-is (no Jekyll pass over the APT repo or the page).
touch "$DOCS_DIR/.nojekyll"
echo "==> Synced site/ into docs/. Commit and push docs/ to publish."
