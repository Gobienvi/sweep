import json
import os

CONFIG_PATH = os.path.expanduser("~/.sweep_config.json")


def load() -> dict:
    if not os.path.exists(CONFIG_PATH):
        default = {"last_cleaned": None}
        save(default)
        return default
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save(data: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)
