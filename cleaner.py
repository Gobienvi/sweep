import os
import shutil
import subprocess

from send2trash import send2trash


def move_to_trash(paths: list[str]) -> tuple[int, int]:
    ok = 0
    fail = 0
    for path in paths:
        if not os.path.exists(path):
            continue
        try:
            send2trash(path)
            ok += 1
        except Exception:
            try:
                _osascript_trash(path)
                ok += 1
            except Exception:
                fail += 1
    return ok, fail


def _osascript_trash(path: str) -> None:
    script = f'tell application "Finder" to delete POSIX file "{path}"'
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, timeout=10
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode())


def clean_caches(dirs: list[str]) -> tuple[int, int]:
    ok = 0
    fail = 0
    for d in dirs:
        expanded = os.path.expanduser(d)
        if not os.path.isdir(expanded):
            continue
        try:
            shutil.rmtree(expanded)
            ok += 1
        except Exception:
            fail += 1
    return ok, fail


def clean_node_modules(items: list[dict]) -> tuple[int, int]:
    ok = 0
    fail = 0
    for item in items:
        path = item["path"]
        if not os.path.isdir(path):
            continue
        try:
            shutil.rmtree(path)
            ok += 1
        except Exception:
            fail += 1
    return ok, fail


def prune_docker() -> dict:
    try:
        result = subprocess.run(
            ["docker", "system", "prune", "-f", "--volumes"],
            capture_output=True, text=True, timeout=120
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout.strip() or result.stderr.strip(),
        }
    except FileNotFoundError:
        return {"success": False, "output": "Docker not installed"}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "Docker prune timed out"}
