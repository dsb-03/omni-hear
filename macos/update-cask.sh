#!/bin/bash
# Regenerate Casks/omnihear.rb in the Homebrew tap repo for a new release and
# push it. Run by CI after the DMG is built and attached to the Release.
#
# Env:
#   VERSION    release version, e.g. 1.4.0
#   TAP_REPO   owner/name of the tap repo, e.g. you/homebrew-omnihear
#   GH_TOKEN   PAT with push access to TAP_REPO
#   GITHUB_REPOSITORY  auto-set in Actions -> source repo hosting the release
set -e

: "${VERSION:?VERSION not set}"
: "${TAP_REPO:?TAP_REPO not set (owner/homebrew-omnihear)}"
: "${GH_TOKEN:?GH_TOKEN not set}"
SRC_REPO="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}"

DMG="omnihear-${VERSION}-arm64.dmg"
[ -f "$DMG" ] || { echo "missing $DMG" >&2; exit 1; }
SHA256="$(shasum -a 256 "$DMG" | awk '{print $1}')"
URL="https://github.com/${SRC_REPO}/releases/download/v${VERSION}/${DMG}"

WORK="$(mktemp -d)"
git clone --depth 1 "https://x-access-token:${GH_TOKEN}@github.com/${TAP_REPO}.git" "$WORK"
mkdir -p "$WORK/Casks"

cat > "$WORK/Casks/omnihear.rb" <<EOF
cask "omnihear" do
  version "${VERSION}"
  sha256 "${SHA256}"

  url "${URL}"
  name "Omnihear"
  desc "Push-to-talk local Whisper transcription"
  homepage "https://github.com/${SRC_REPO}"

  depends_on arch: :arm64
  depends_on macos: :big_sur


  app "omnihear.app"

  zap trash: [
    "~/Library/Application Support/omnihear",
  ]
end
EOF

cd "$WORK"
git config user.name "github-actions"
git config user.email "github-actions@users.noreply.github.com"
git add Casks/omnihear.rb
if git diff --cached --quiet; then
  echo "cask already up to date"
else
  git commit -m "omnihear ${VERSION}"
  git push
  echo "pushed cask update for ${VERSION}"
fi
