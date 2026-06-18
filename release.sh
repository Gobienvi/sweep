#!/bin/bash
set -e

VERSION=${1:-$(python -c "from version import __version__; print(__version__)")}
APP_NAME="Sweep"
DMG_NAME="${APP_NAME}-${VERSION}.dmg"
REPO="Gobienvi/sweep"

echo "▶ Building ${APP_NAME} v${VERSION}..."

# ── 1. update version.py ──────────────────────────────────────────────────────
sed -i '' "s/__version__ = \".*\"/__version__ = \"${VERSION}\"/" version.py

# ── 2. activate venv and build .app ──────────────────────────────────────────
source venv/bin/activate
bash build.sh

# ── 3. create DMG ─────────────────────────────────────────────────────────────
echo "▶ Creating DMG..."
STAGING="staging_dmg"
rm -rf "${STAGING}"
mkdir "${STAGING}"

# copy app and add Applications symlink
cp -r "dist/${APP_NAME}.app" "${STAGING}/"
ln -s /Applications "${STAGING}/Applications"

# create writable DMG from staging folder
hdiutil create \
  -volname "${APP_NAME}" \
  -srcfolder "${STAGING}" \
  -ov -format UDRW \
  -fs HFS+ \
  "dist/${APP_NAME}_tmp.dmg" > /dev/null

# convert to compressed read-only DMG
hdiutil convert \
  "dist/${APP_NAME}_tmp.dmg" \
  -format UDZO \
  -o "dist/${DMG_NAME}" > /dev/null

rm -f "dist/${APP_NAME}_tmp.dmg"
rm -rf "${STAGING}"

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
