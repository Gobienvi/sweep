import json
import os
import tempfile

import pytest

import config


@pytest.fixture(autouse=True)
def tmp_config(monkeypatch, tmp_path):
    path = str(tmp_path / ".sweep_config.json")
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    return path


def test_load_creates_default_when_missing():
    data = config.load()
    assert data == {"last_cleaned": None}


def test_load_creates_file_when_missing(tmp_config):
    config.load()
    assert os.path.exists(tmp_config)


def test_save_and_load_roundtrip():
    payload = {"last_cleaned": "2026-06-01"}
    config.save(payload)
    assert config.load() == payload


def test_load_returns_existing_data():
    config.save({"last_cleaned": "2026-01-01"})
    data = config.load()
    assert data["last_cleaned"] == "2026-01-01"
