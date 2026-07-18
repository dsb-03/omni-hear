#!/bin/bash
# Adds a .deb into the docs/ APT repo, regenerates the package indexes,
# and signs the Release file.
#
# Usage:
#   GPG_KEY_ID=you@example.com ./scripts/update-apt-repo.sh omnihear_1.1.0_amd64.deb
#
# Requires: dpkg-dev (dpkg-scanpackages), apt-utils (apt-ftparchive), gnupg
# Requires: GPG_KEY_ID env var set to your signing key's ID/email.
#           The matching private key must already be in your local gpg keyring
#           (or imported, e.g. in CI from a secret).

set -e

DEB_FILE="${1:?Usage: ./update-apt-repo.sh <path-to-deb>}"
: "${GPG_KEY_ID:?Set GPG_KEY_ID to your signing key ID or email}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCS_DIR="$REPO_ROOT/docs"
POOL_DIR="$DOCS_DIR/pool/main/o/omnihear"
DIST_DIR="$DOCS_DIR/dists/stable"
BINARY_DIR="$DIST_DIR/main/binary-amd64"

mkdir -p "$POOL_DIR" "$BINARY_DIR"

echo "==> Copying $DEB_FILE into pool"
cp "$DEB_FILE" "$POOL_DIR/"

echo "==> Regenerating Packages index"
cd "$DOCS_DIR"
dpkg-scanpackages --multiversion pool/ > "$BINARY_DIR/Packages"
gzip -k -f "$BINARY_DIR/Packages"

echo "==> Generating Release file"
apt-ftparchive -c "$REPO_ROOT/scripts/apt-ftparchive.conf" release "$DIST_DIR" > "$DIST_DIR/Release"

echo "==> Signing Release (detached + inline) with key $GPG_KEY_ID"
rm -f "$DIST_DIR/Release.gpg" "$DIST_DIR/InRelease"
# GPG_OPTS lets CI pass --pinentry-mode loopback --passphrase ... for non-interactive signing
gpg --batch --yes $GPG_OPTS --default-key "$GPG_KEY_ID" -abs -o "$DIST_DIR/Release.gpg" "$DIST_DIR/Release"
gpg --batch --yes $GPG_OPTS --default-key "$GPG_KEY_ID" --clearsign -o "$DIST_DIR/InRelease" "$DIST_DIR/Release"

echo "==> Exporting public key to docs/pubkey.gpg"
gpg --armor --export "$GPG_KEY_ID" > "$DOCS_DIR/pubkey.gpg"

echo "==> Done. Commit and push the docs/ folder to publish the update."
