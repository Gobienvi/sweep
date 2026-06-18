import subprocess
from datetime import date

import config

REMIND_AFTER_DAYS = 3


def should_remind(cfg: dict) -> bool:
    last = cfg.get("last_cleaned")
    if last is None:
        return True
    return (date.today() - date.fromisoformat(last)).days >= REMIND_AFTER_DAYS


def mark_cleaned() -> None:
    cfg = config.load()
    cfg["last_cleaned"] = date.today().isoformat()
    config.save(cfg)


def send_notification(title: str, message: str) -> None:
    script = f'display notification "{message}" with title "{title}" sound name "Glass"'
    subprocess.run(["osascript", "-e", script], capture_output=True)
