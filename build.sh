#!/bin/bash
set -e

# ── Notarization credentials ──────────────────────────────────────────────────
# Fill these in once you have an Apple Developer account ($99/year).
# Get TEAM_ID from: https://developer.apple.com/account → Membership → Team ID
# Get APP_PASSWORD from: https://appleid.apple.com → App-Specific Passwords
# IDENTITY comes from: security find-identity -v -p codesigning
#
NOTARIZE=false   # set to true once credentials are filled in below
TEAM_ID=""
APPLE_ID=""
APP_PASSWORD=""
IDENTITY=""      # e.g. "Developer ID Application: Jun Kim (ABC123XYZ)"
# ─────────────────────────────────────────────────────────────────────────────

source venv/bin/activate

pyinstaller -y --clean \
  --name Sweep \
  --windowed \
  --onedir \
  --osx-bundle-identifier "com.gobienvi.sweep" \
  --add-data "assets:assets" \
  --hidden-import rumps \
  --hidden-import PIL \
  --hidden-import imagehash \
  --hidden-import send2trash \
  --hidden-import numpy \
  --hidden-import scipy \
  --hidden-import scipy.ndimage \
  --hidden-import WebKit \
  main.py

# Inject privacy usage descriptions so macOS TCC remembers permissions
PLIST="dist/Sweep.app/Contents/Info.plist"
add_key() {
  /usr/libexec/PlistBuddy -c "Add :$1 string '$2'" "$PLIST" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Set :$1 '$2'" "$PLIST"
}

add_key NSDesktopFolderUsageDescription    "Sweep scans your Desktop for screenshots and junk files."
add_key NSDownloadsFolderUsageDescription  "Sweep scans your Downloads folder for old files."
add_key NSDocumentsFolderUsageDescription  "Sweep scans Documents for recordings and large files."
add_key NSPicturesFolderUsageDescription   "Sweep scans your Photos library for blurry and duplicate images."
add_key NSRemovableVolumesUsageDescription "Sweep scans removable drives for junk files."
add_key NSAppleEventsUsageDescription      "Sweep uses System Events to read and manage your login items."

VERSION=$(python -c "from version import __version__; print(__version__)")
DMG="dist/Sweep-${VERSION}.dmg"

if [ "$NOTARIZE" = true ]; then
  # ── Signed + notarized build (for distribution) ───────────────────────────
  echo "Signing with Developer ID…"
  codesign --deep --force --options runtime \
    --entitlements entitlements.plist \
    --sign "$IDENTITY" \
    "dist/Sweep.app"

  codesign --verify --deep --strict "dist/Sweep.app"
  echo "Signature verified ✓"

  echo "Creating DMG…"
  rm -rf dist/dmg-staging
  mkdir dist/dmg-staging
  cp -r "dist/Sweep.app" dist/dmg-staging/
  ln -s /Applications dist/dmg-staging/Applications
  rm -f "$DMG"
  hdiutil create \
    -volname "Sweep" \
    -srcfolder dist/dmg-staging \
    -ov -format UDZO \
    "$DMG"
  rm -rf dist/dmg-staging

  echo "Submitting to Apple notarization service…"
  xcrun notarytool submit "$DMG" \
    --apple-id "$APPLE_ID" \
    --team-id "$TEAM_ID" \
    --password "$APP_PASSWORD" \
    --wait

  echo "Stapling notarization ticket to DMG…"
  xcrun stapler staple "$DMG"

  echo "Verifying notarization…"
  spctl --assess --type open --context context:primary-signature "$DMG"
  echo "Notarization complete ✓"

else
  # ── Ad-hoc signed build (for local testing only) ─────────────────────────
  codesign --force --deep --options runtime \
    --entitlements entitlements.plist \
    --sign - "dist/Sweep.app"

  rm -rf dist/dmg-staging
  mkdir dist/dmg-staging
  cp -r "dist/Sweep.app" dist/dmg-staging/
  ln -s /Applications dist/dmg-staging/Applications
  rm -f "$DMG"
  hdiutil create \
    -volname "Sweep" \
    -srcfolder dist/dmg-staging \
    -ov -format UDZO \
    "$DMG"
  rm -rf dist/dmg-staging
fi

echo ""
echo "Build complete:   dist/Sweep.app"
echo "Installer ready:  $DMG"
if [ "$NOTARIZE" = false ]; then
  echo ""
  echo "⚠️  Ad-hoc signed only — users will see Gatekeeper warning."
  echo "   Set NOTARIZE=true with Developer ID credentials to ship publicly."
fi
