import os
import tempfile

import pytest

import cleaner


def test_move_to_trash_moves_file(tmp_path):
    f = tmp_path / "junk.txt"
    f.write_text("delete me")
    ok, fail = cleaner.move_to_trash([str(f)])
    assert ok == 1
    assert fail == 0
    assert not f.exists()


def test_move_to_trash_skips_missing():
    ok, fail = cleaner.move_to_trash(["/nonexistent/file.txt"])
    assert ok == 1  # already gone counts as success
    assert fail == 0


def test_move_to_trash_counts_multiple(tmp_path):
    files = []
    for i in range(3):
        f = tmp_path / f"file{i}.txt"
        f.write_text("x")
        files.append(str(f))
    ok, fail = cleaner.move_to_trash(files)
    assert ok == 3
    assert fail == 0


def test_clean_caches_removes_dir(tmp_path):
    cache = tmp_path / "mycache"
    cache.mkdir()
    (cache / "data.bin").write_bytes(b"\x00" * 512)
    ok, fail = cleaner.clean_caches([str(cache)])
    assert ok == 1
    assert fail == 0
    assert not cache.exists()


def test_clean_caches_skips_missing():
    ok, fail = cleaner.clean_caches(["/nonexistent/cache"])
    assert ok == 0
    assert fail == 0
