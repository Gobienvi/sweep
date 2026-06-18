#!/bin/bash
set -e

source venv/bin/activate

pyinstaller -y \
  --name Sweep \
  --windowed \
  --onedir \
  --add-data "assets:assets" \
  --hidden-import rumps \
  --hidden-import PIL \
  --hidden-import imagehash \
  --hidden-import send2trash \
  --hidden-import numpy \
  --hidden-import scipy \
  --hidden-import scipy.ndimage \
  main.py

echo "Build complete: dist/Sweep.app"
