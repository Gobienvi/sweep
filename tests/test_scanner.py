import os
import time

import numpy as np
import pytest
from PIL import Image

import scanner


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_image(path: str, color: int = 128, size=(64, 64)):
    img = Image.fromarray(np.full((*size, 3), color, dtype=np.uint8))
    img.save(path)


# ── scan_screenshots ──────────────────────────────────────────────────────────

def test_scan_screenshots_finds_screenshots(tmp_path):
    (tmp_path / "Screenshot 2026-01-01.png").touch()
    (tmp_path / "photo.jpg").touch()
    results = scanner.scan_screenshots([str(tmp_path)])
    assert len(results) == 1
    assert "Screenshot" in results[0]


def test_scan_screenshots_ignores_non_screenshots(tmp_path):
    (tmp_path / "photo.jpg").touch()
    assert scanner.scan_screenshots([str(tmp_path)]) == []


def test_scan_screenshots_missing_folder():
    assert scanner.scan_screenshots(["/nonexistent/path"]) == []


# ── scan_bad_photos ───────────────────────────────────────────────────────────

def test_scan_bad_photos_detects_dark_image(tmp_path):
    dark = str(tmp_path / "dark.jpg")
    _make_image(dark, color=5)  # very dark
    results = scanner.scan_bad_photos(str(tmp_path))
    assert dark in results


def test_scan_bad_photos_ignores_good_image(tmp_path):
    good = str(tmp_path / "good.jpg")
    # bright, high-contrast checkerboard → high Laplacian variance
    arr = np.zeros((64, 64, 3), dtype=np.uint8)
    arr[::2, ::2] = 255
    arr[1::2, 1::2] = 200
    Image.fromarray(arr).save(good)
    results = scanner.scan_bad_photos(str(tmp_path))
    assert good not in results


def test_scan_bad_photos_missing_folder():
    assert scanner.scan_bad_photos("/nonexistent") == []


# ── scan_duplicates ───────────────────────────────────────────────────────────

def test_scan_duplicates_finds_identical_images(tmp_path):
    a = str(tmp_path / "a.jpg")
    b = str(tmp_path / "b.jpg")
    _make_image(a, color=100)
    _make_image(b, color=100)
    groups = scanner.scan_duplicates(str(tmp_path))
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_scan_duplicates_no_duplicates(tmp_path):
    a = str(tmp_path / "a.jpg")
    b = str(tmp_path / "b.jpg")
    # use structurally distinct patterns so phash gives different hashes
    arr_a = np.zeros((64, 64, 3), dtype=np.uint8)
    arr_a[:32, :] = 255  # top half white
    arr_b = np.zeros((64, 64, 3), dtype=np.uint8)
    arr_b[:, :32] = 255  # left half white
    Image.fromarray(arr_a).save(a)
    Image.fromarray(arr_b).save(b)
    groups = scanner.scan_duplicates(str(tmp_path))
    assert groups == []


def test_scan_duplicates_missing_folder():
    assert scanner.scan_duplicates("/nonexistent") == []


# ── scan_downloads_all ───────────────────────────────────────────────────────

def test_scan_downloads_all_finds_files(tmp_path):
    f = tmp_path / "report.pdf"
    f.write_bytes(b"x" * 1024)
    old_time = time.time() - 40 * 86400
    os.utime(str(f), (old_time, old_time))
    results = scanner.scan_downloads_all(str(tmp_path))
    paths = [r["path"] for r in results]
    assert str(f) in paths


def test_scan_downloads_all_age_days(tmp_path):
    f = tmp_path / "new.zip"
    f.write_bytes(b"x")
    results = scanner.scan_downloads_all(str(tmp_path))
    assert results[0]["age_days"] >= 0


def test_scan_downloads_all_missing_folder():
    assert scanner.scan_downloads_all("/nonexistent") == []


# ── scan_cache_size ───────────────────────────────────────────────────────────

def test_scan_cache_size_returns_sizes(tmp_path):
    d = tmp_path / "cache"
    d.mkdir()
    (d / "file.dat").write_bytes(b"x" * 1024)
    result = scanner.scan_cache_size([str(d)])
    assert result[str(d)] == 1024


def test_scan_cache_size_skips_missing():
    result = scanner.scan_cache_size(["/nonexistent/cache"])
    assert result == {}
