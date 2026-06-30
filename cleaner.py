import os
import shutil
import subprocess

from send2trash import send2trash


def move_to_trash(paths: list[str]) -> tuple[int, int]:
    ok = 0
    fail = 0
    for path in paths:
        if not os.path.exists(path):
            ok += 1  # already gone — goal achieved
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
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "Finder" to delete POSIX file "{escaped}"'
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, timeout=10
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode())


def _clear_dir_contents(path: str) -> bool:
    """Move each item inside a directory to Trash when the dir itself can't be trashed."""
    cleared = False
    try:
        entries = list(os.scandir(path))
    except OSError:
        return False
    for entry in entries:
        try:
            send2trash(entry.path)
            cleared = True
        except Exception:
            pass
    return cleared


def clean_caches(dirs: list[str]) -> tuple[int, int]:
    ok = 0
    fail = 0
    for d in dirs:
        expanded = os.path.expanduser(d)
        if not os.path.isdir(expanded):
            continue
        try:
            send2trash(expanded)
            ok += 1
        except Exception:
            # Dir itself is protected (e.g. ~/Library/Caches in use by macOS)
            # — clear its contents instead
            if _clear_dir_contents(expanded):
                ok += 1
            else:
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
            send2trash(path)
            ok += 1
        except Exception:
            fail += 1
    return ok, fail


def empty_trash() -> dict:
    try:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "Finder" to empty trash'],
            capture_output=True, text=True, timeout=60
        )
        return {"success": result.returncode == 0}
    except Exception:
        return {"success": False}



def delete_permanent(paths: list[str]) -> tuple[int, int]:
    """Permanently delete files/dirs (used for language files inside app bundles)."""
    ok, fail = 0, 0
    for path in paths:
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            elif os.path.isfile(path):
                os.remove(path)
            ok += 1
        except Exception:
            fail += 1
    return ok, fail


def remove_login_items(names: list[str]) -> tuple[int, int]:
    ok, fail = 0, 0
    try:
        from Foundation import NSAppleScript
    except ImportError:
        return 0, len(names)
    for name in names:
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        source = f'tell application "System Events" to delete login item "{escaped}"'
        script = NSAppleScript.alloc().initWithSource_(source)
        _, error = script.executeAndReturnError_(None)
        if error:
            fail += 1
        else:
            ok += 1
    return ok, fail


def prune_docker() -> dict:
    try:
        result = subprocess.run(
            ["docker", "system", "prune", "-f"],
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
