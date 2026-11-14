from datetime import date, timedelta
from unittest.mock import patch, MagicMock

import pytest

import config
import notifier


@pytest.fixture(autouse=True)
def tmp_config(monkeypatch, tmp_path):
    path = str(tmp_path / ".sweep_config.json")
    monkeypatch.setattr(config, "CONFIG_PATH", path)


def test_should_remind_when_no_last_cleaned():
    cfg = {"last_cleaned": None}
    assert notifier.should_remind(cfg) is True


def test_should_remind_when_overdue():
    old = (date.today() - timedelta(days=4)).isoformat()
    assert notifier.should_remind({"last_cleaned": old}) is True


def test_should_not_remind_when_recent():
    recent = (date.today() - timedelta(days=1)).isoformat()
    assert notifier.should_remind({"last_cleaned": recent}) is False


def test_should_remind_exactly_at_threshold():
    threshold = (date.today() - timedelta(days=3)).isoformat()
    assert notifier.should_remind({"last_cleaned": threshold}) is True


def test_mark_cleaned_saves_today():
    notifier.mark_cleaned()
    cfg = config.load()
    assert cfg["last_cleaned"] == date.today().isoformat()


def test_send_notification_calls_osascript():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        notifier.send_notification("Sweep", "Time to clean!")
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "osascript"
