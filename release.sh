#!/bin/bash
set -e

VERSION=${1:-$(python -c "from version import __version__; print(__version__)")}
APP_NAME="Sweep"
DMG_NAME="${APP_NAME}-${VERSION}.dmg"
REPO="Gobienvi/sweep"

echo "▶ Building ${APP_NAME} v${VERSION}..."

# ── 1. update version.py ──────────────────────────────────────────────────────
sed -i '' "s/__version__ = \".*\"/__version__ = \"${VERSION}\"/" version.py
git add version.py
# skip the commit if version.py already had this version (otherwise set -e aborts)
if ! git diff --cached --quiet version.py; then
  git commit -m "chore: bump version to ${VERSION}"
fi
git push

# ── 2. activate venv and build .app ──────────────────────────────────────────
source venv/bin/activate
bash build.sh

# ── 3. DMG ────────────────────────────────────────────────────────────────────
# build.sh already creates dist/${DMG_NAME} — just make sure it's there.
if [ ! -f "dist/${DMG_NAME}" ]; then
  echo "✗ dist/${DMG_NAME} not found — build.sh should have created it"
  exit 1
fi
echo "✓ DMG ready: dist/${DMG_NAME}"

# ── 4. publish to GitHub (optional — needs gh CLI) ───────────────────────────
if command -v gh &>/dev/null; then
  echo "▶ Creating GitHub release v${VERSION}..."
  gh release create "v${VERSION}" \
    "dist/${DMG_NAME}" \
    --repo "${REPO}" \
    --title "Sweep v${VERSION}" \
    --notes "Download **${DMG_NAME}**, open it, and drag Sweep to Applications." \
    --latest
  echo "✓ Published: https://github.com/${REPO}/releases/tag/v${VERSION}"
else
  echo "ℹ️  gh CLI not found — upload dist/${DMG_NAME} to GitHub releases manually."
  echo "   Install with: brew install gh"
fi
