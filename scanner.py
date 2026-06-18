import glob
import os
import subprocess
import time

import imagehash
import numpy as np
from PIL import Image

BLUR_THRESHOLD = 100.0
DARK_THRESHOLD = 30.0
OLD_DAYS = 30
LARGE_FILE_MB = 500
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".heic", ".webp")
SCREENSHOT_PATTERNS = ("Screenshot", "Screen Shot", "Capture")
SCREENSHOT_FOLDERS = [
    os.path.expanduser("~/Desktop"),
    os.path.expanduser("~/Downloads"),
]
DOWNLOAD_FOLDER = os.path.expanduser("~/Downloads")
CACHE_DIRS = [
    "~/Library/Caches",
    "~/.npm/_cacache",
    "~/.cache/pip",
    "~/.cache/uv",
    "~/.bun/install/cache",
    "~/.pnpm-store",
    "~/.yarn/cache",
    "~/.gradle/caches",
    "~/.m2/repository",
    "~/.cache/Cypress",
    "~/.cache/ms-playwright",
    "~/Library/Developer/Xcode/DerivedData",
    "~/Library/Developer/CoreSimulator/Caches",
    "~/Library/Logs",
]
BROWSER_CACHES = {
    "Chrome":   "~/Library/Application Support/Google/Chrome/Default/Cache",
    "Safari":   "~/Library/Caches/com.apple.Safari",
    "Arc":      "~/Library/Application Support/Arc/User Data/Default/Cache",
    "Firefox":  "~/Library/Application Support/Firefox/Profiles",
    "Brave":    "~/Library/Application Support/BraveSoftware/Brave-Browser/Default/Cache",
    "Edge":     "~/Library/Application Support/Microsoft Edge/Default/Cache",
}
NODE_MODULES_SEARCH_ROOTS = [
    "~/Projects", "~/Code", "~/code", "~/dev", "~/Dev",
    "~/workspace", "~/Sites", "~/repos", "~/Developer",
    "~/Desktop", "~/Documents",
]
IOS_BACKUP_DIR = "~/Library/Application Support/MobileSync/Backup"
XCODE_ARCHIVES_DIR = "~/Library/Developer/Xcode/Archives"
RECORDING_DIRS = [
    "~/Documents/Zoom",
    "~/Documents/Microsoft Teams",
    "~/Documents/Recordings",
    "~/Movies/Zoom",
]

# dirs to skip when walking for node_modules / large files
_SKIP_DIRS = {
    "venv", ".venv", "env", ".git", "dist", "build",
    ".Trash", "Library", "Applications",
}


# ── existing scanners ─────────────────────────────────────────────────────────

def scan_screenshots(folders: list[str] | None = None) -> list[str]:
    folders = folders or SCREENSHOT_FOLDERS
    found = []
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for fname in os.listdir(folder):
            if any(fname.startswith(p) for p in SCREENSHOT_PATTERNS):
                found.append(os.path.join(folder, fname))
    return found


def _laplacian_variance(img: Image.Image) -> float:
    gray = img.convert("L")
    arr = np.array(gray, dtype=float)
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]])
    from scipy.ndimage import convolve
    lap = convolve(arr, kernel)
    return float(np.var(lap))


def _mean_brightness(img: Image.Image) -> float:
    gray = img.convert("L")
    return float(np.mean(np.array(gray)))


def _is_bad_photo(path: str) -> bool:
    try:
        with Image.open(path) as img:
            if _mean_brightness(img) < DARK_THRESHOLD:
                return True
            if _laplacian_variance(img) < BLUR_THRESHOLD:
                return True
    except Exception:
        return False
    return False


def scan_bad_photos(folder: str | None = None) -> list[str]:
    folder = folder or os.path.expanduser("~/Pictures")
    bad = []
    if not os.path.isdir(folder):
        return bad
    for root, _, files in os.walk(folder):
        for fname in files:
            if fname.lower().endswith(IMAGE_EXTENSIONS):
                path = os.path.join(root, fname)
                if _is_bad_photo(path):
                    bad.append(path)
    return bad


def scan_duplicates(folder: str | None = None) -> list[list[str]]:
    folder = folder or os.path.expanduser("~/Pictures")
    hash_map: dict[str, list[str]] = {}
    if not os.path.isdir(folder):
        return []
    for root, _, files in os.walk(folder):
        for fname in files:
            if fname.lower().endswith(IMAGE_EXTENSIONS):
                path = os.path.join(root, fname)
                try:
                    with Image.open(path) as img:
                        h = str(imagehash.phash(img))
                    hash_map.setdefault(h, []).append(path)
                except Exception:
                    continue
    return [paths for paths in hash_map.values() if len(paths) > 1]


def scan_old_downloads(folder: str | None = None, days: int = OLD_DAYS) -> list[str]:
    folder = folder or DOWNLOAD_FOLDER
    if not os.path.isdir(folder):
        return []
    cutoff = time.time() - days * 86400
    old = []
    for fname in os.listdir(folder):
        path = os.path.join(folder, fname)
        if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
            old.append(path)
    return old


def scan_cache_size(dirs: list[str] | None = None) -> dict[str, int]:
    dirs = dirs or CACHE_DIRS
    result: dict[str, int] = {}
    for d in dirs:
        expanded = os.path.expanduser(d)
        if not os.path.isdir(expanded):
            continue
        total = 0
        for root, _, files in os.walk(expanded):
            for fname in files:
                try:
                    total += os.path.getsize(os.path.join(root, fname))
                except OSError:
                    continue
        result[expanded] = total
    return result


# ── new scanners ──────────────────────────────────────────────────────────────

def scan_browser_caches() -> dict[str, int]:
    result: dict[str, int] = {}
    for browser, path in BROWSER_CACHES.items():
        expanded = os.path.expanduser(path)
        # Firefox stores profiles in subdirs — find cache2 inside each profile
        if browser == "Firefox":
            pattern = os.path.join(expanded, "*.default*", "cache2")
            matches = glob.glob(pattern)
            total = 0
            for match in matches:
                if os.path.isdir(match):
                    for root, _, files in os.walk(match):
                        for fname in files:
                            try:
                                total += os.path.getsize(os.path.join(root, fname))
                            except OSError:
                                continue
            if total:
                result[browser] = total
        elif os.path.isdir(expanded):
            total = 0
            for root, _, files in os.walk(expanded):
                for fname in files:
                    try:
                        total += os.path.getsize(os.path.join(root, fname))
                    except OSError:
                        continue
            if total:
                result[browser] = total
    return result


def _dir_size(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for fname in files:
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                continue
    return total


def scan_node_modules(roots: list[str] | None = None, days: int = OLD_DAYS) -> list[dict]:
    roots = roots or NODE_MODULES_SEARCH_ROOTS
    cutoff = time.time() - days * 86400
    found = []
    for root in roots:
        expanded = os.path.expanduser(root)
        if not os.path.isdir(expanded):
            continue
        for dirpath, dirnames, _ in os.walk(expanded):
            # skip deeply nested and known unrelated dirs
            dirnames[:] = [
                d for d in dirnames
                if d not in _SKIP_DIRS and not d.startswith(".")
            ]
            if "node_modules" in dirnames:
                nm_path = os.path.join(dirpath, "node_modules")
                mtime = os.path.getmtime(nm_path)
                if mtime < cutoff:
                    size = _dir_size(nm_path)
                    found.append({"path": nm_path, "size": size, "mtime": mtime})
                dirnames.remove("node_modules")  # don't recurse into it
    return found


def scan_ios_backups() -> list[dict]:
    backup_root = os.path.expanduser(IOS_BACKUP_DIR)
    if not os.path.isdir(backup_root):
        return []
    backups = []
    try:
        entries = os.listdir(backup_root)
    except PermissionError:
        return []
    for name in entries:
        path = os.path.join(backup_root, name)
        if os.path.isdir(path):
            try:
                size = _dir_size(path)
                mtime = os.path.getmtime(path)
                backups.append({"path": path, "size": size, "mtime": mtime})
            except PermissionError:
                continue
    return sorted(backups, key=lambda x: x["mtime"], reverse=True)


def scan_xcode_archives() -> list[dict]:
    archive_root = os.path.expanduser(XCODE_ARCHIVES_DIR)
    if not os.path.isdir(archive_root):
        return []
    archives = []
    for root, dirnames, _ in os.walk(archive_root):
        for d in dirnames:
            if d.endswith(".xcarchive"):
                path = os.path.join(root, d)
                size = _dir_size(path)
                mtime = os.path.getmtime(path)
                archives.append({"path": path, "size": size, "mtime": mtime})
    return sorted(archives, key=lambda x: x["mtime"])


def scan_large_files(min_mb: int = LARGE_FILE_MB) -> list[dict]:
    home = os.path.expanduser("~")
    min_bytes = min_mb * 1024 * 1024
    found = []
    skip_prefixes = [
        os.path.expanduser("~/Library"),
        os.path.expanduser("~/.Trash"),
    ]
    for dirpath, dirnames, files in os.walk(home):
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS
            and not any(
                os.path.join(dirpath, d).startswith(p) for p in skip_prefixes
            )
        ]
        for fname in files:
            path = os.path.join(dirpath, fname)
            try:
                size = os.path.getsize(path)
                if size >= min_bytes:
                    found.append({"path": path, "size": size})
            except OSError:
                continue
    return sorted(found, key=lambda x: x["size"], reverse=True)


def scan_recordings() -> list[dict]:
    found = []
    for d in RECORDING_DIRS:
        expanded = os.path.expanduser(d)
        if not os.path.isdir(expanded):
            continue
        for root, _, files in os.walk(expanded):
            for fname in files:
                if fname.lower().endswith((".mp4", ".mov", ".mkv", ".m4v", ".avi")):
                    path = os.path.join(root, fname)
                    try:
                        size = os.path.getsize(path)
                        found.append({"path": path, "size": size})
                    except OSError:
                        continue
    return sorted(found, key=lambda x: x["size"], reverse=True)


def scan_docker() -> dict:
    try:
        result = subprocess.run(
            ["docker", "system", "df", "--format", "{{.Type}}\t{{.Size}}\t{{.Reclaimable}}"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return {"available": False}
        lines = [l for l in result.stdout.strip().splitlines() if l]
        rows = []
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 3:
                rows.append({"type": parts[0], "size": parts[1], "reclaimable": parts[2]})
        return {"available": True, "rows": rows}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"available": False}
