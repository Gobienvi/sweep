#!/bin/bash
set -e

source venv/bin/activate

pyinstaller -y \
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

# Re-sign after plist edit
codesign --force --deep --sign - "dist/Sweep.app"

# Package into a distributable .dmg
VERSION=$(python -c "from version import __version__; print(__version__)")
DMG="dist/Sweep-${VERSION}.dmg"
rm -f "$DMG"
hdiutil create \
  -volname "Sweep" \
  -srcfolder "dist/Sweep.app" \
  -ov -format UDZO \
  "$DMG"

echo "Build complete: dist/Sweep.app"
echo "Installer ready: $DMG"
