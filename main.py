import os
import threading
import urllib.request
import json

import rumps

import cleaner
import config
import notifier
import report
import scanner
import server
from version import __version__, GITHUB_REPO


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _icon_path() -> str:
    import sys, os
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "menu-icon.png")


class SweepApp(rumps.App):
    def __init__(self):
        super().__init__("Sweep", icon=_icon_path(), template=True, quit_button=None)
        self.menu = [
            rumps.MenuItem("Sweep Now", callback=self.sweep_now),
            rumps.MenuItem("Scan Only", callback=self.scan_only),
            None,
            rumps.MenuItem("Last cleaned: never"),
            rumps.MenuItem(f"Version {__version__}"),
            None,
            rumps.MenuItem("Quit Sweep", callback=rumps.quit_application),
        ]
        self._status_item = self.menu["Last cleaned: never"]
        self._version_item = self.menu[f"Version {__version__}"]
        self._refresh_status()
        self._schedule_reminder()
        threading.Thread(target=self._check_for_update, daemon=True).start()
        threading.Thread(target=self._startup_scan, daemon=True).start()

    def _startup_scan(self):
        """Silent background scan on startup — badges menu bar with junk size."""
        self.title = None
        fast = [
            ("screenshots",    scanner.scan_screenshots,    []),
            ("downloads",      scanner.scan_downloads_all,  []),
            ("cache_sizes",    scanner.scan_cache_size,     {}),
            ("browser_caches", scanner.scan_browser_caches, {}),
            ("node_modules",   scanner.scan_node_modules,   []),
            ("recordings",     scanner.scan_recordings,     []),
            ("trash",          scanner.scan_trash,          {"size": 0, "path": ""}),
            ("ios_backups",    scanner.scan_ios_backups,    []),
        ]
        result: dict = {}
        lock = threading.Lock()

        def _run(key, fn, default):
            try:
                val = fn()
            except Exception:
                val = default
            with lock:
                result[key] = val

        threads = [threading.Thread(target=_run, args=(k, f, d), daemon=True) for k, f, d in fast]
        for t in threads: t.start()
        for t in threads: t.join()

        def _sz(p):
            try: return os.path.getsize(p)
            except OSError: return 0

        cache_sizes = result.get("cache_sizes", {})
        browser_caches = result.get("browser_caches", {})
        trash = result.get("trash", {"size": 0})

        total = (
            sum(_sz(p) for p in result.get("screenshots", []))
            + sum(f["size"] for f in result.get("downloads", []))
            + sum(cache_sizes.values())
            + sum(browser_caches.values())
            + sum(i["size"] for i in result.get("node_modules", []))
            + sum(i["size"] for i in result.get("recordings", []))
            + trash.get("size", 0)
            + sum(i["size"] for i in result.get("ios_backups", []))
        )

        self.title = None
        if total > 50 * 1024 * 1024:
            self._status_item.title = f"Found {_format_bytes(total)} to clean — open Scan Only"
        else:
            self._status_item.title = "Mac looks clean ✓"

    def _check_for_update(self):
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            req = urllib.request.Request(url, headers={"User-Agent": "Sweep-App"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            latest = data.get("tag_name", "").lstrip("v")
            if latest and latest != __version__:
                self._version_item.title = f"⬆️ Update available: v{latest}"
                notifier.send_notification(
                    "Sweep Update",
                    f"Version {latest} is available — visit github.com/{GITHUB_REPO}/releases"
                )
        except Exception:
            pass

    def _schedule_reminder(self):
        rumps.Timer(self._check_reminder, 3600).start()

    def _check_reminder(self, _sender):
        cfg = config.load()
        if notifier.should_remind(cfg):
            notifier.send_notification(
                "Sweep", "Time to clean up your Mac! Open Sweep to free some space."
            )

    def _do_scan(self) -> dict:
        screenshots = scanner.scan_screenshots()
        bad_photos = scanner.scan_bad_photos()
        duplicate_groups = scanner.scan_duplicates()
        downloads = scanner.scan_downloads_all()
        cache_sizes = scanner.scan_cache_size()
        browser_caches = scanner.scan_browser_caches()
        node_modules = scanner.scan_node_modules()
        ios_backups = scanner.scan_ios_backups()
        xcode_archives = scanner.scan_xcode_archives()
        large_files = scanner.scan_large_files()
        recordings = scanner.scan_recordings()
        docker = scanner.scan_docker()
        duplicates = [f for group in duplicate_groups for f in group[1:]]
        return {
            "screenshots": screenshots,
            "bad_photos": bad_photos,
            "duplicates": duplicates,
            "downloads": downloads,
            "cache_dirs": list(cache_sizes.keys()),
            "cache_sizes": cache_sizes,
            "total_cache": sum(cache_sizes.values()),
            "browser_caches": browser_caches,
            "node_modules": node_modules,
            "ios_backups": ios_backups,
            "xcode_archives": xcode_archives,
            "large_files": large_files,
            "recordings": recordings,
            "docker": docker,
        }

    @rumps.clicked("Scan Only")
    def scan_only(self, _sender):
        self.title = None
        port = server.start()
        server.set_scanning("Starting…")
        report.open_loading_page(port)
        threading.Thread(target=self._scan_and_report, args=(port,), daemon=True).start()

    def _scan_and_report(self, port: int):
        server.clear_scan_trigger()  # arm before first scan so any /rescan during scan is captured
        self._run_scan_steps(port)
        while server.wait_for_scan_trigger(timeout=3600):
            server.clear_scan_trigger()  # re-arm before next scan
            self.title = None
            self._run_scan_steps(port)

    def _run_scan_steps(self, port: int):
        steps = [
            ("screenshots",     lambda: scanner.scan_screenshots(),      "Scanning screenshots…",            []),
            ("bad_photos",      lambda: scanner.scan_bad_photos(),        "Scanning photos for blur & darkness…", []),
            ("duplicates",      lambda: scanner.scan_duplicates(),        "Finding duplicate photos…",        []),
            ("downloads",       lambda: scanner.scan_downloads_all(),     "Checking downloads…",              []),
            ("cache_sizes",     lambda: scanner.scan_cache_size(),        "Measuring dev caches…",            {}),
            ("browser_caches",  lambda: scanner.scan_browser_caches(),    "Checking browser caches…",         {}),
            ("node_modules",    lambda: scanner.scan_node_modules(),      "Finding node_modules…",            []),
            ("ios_backups",     lambda: scanner.scan_ios_backups(),       "Checking iOS backups…",            []),
            ("xcode_archives",  lambda: scanner.scan_xcode_archives(),    "Checking Xcode archives…",         []),
            ("large_files",     lambda: scanner.scan_large_files(),       "Finding large files…",             []),
            ("recordings",      lambda: scanner.scan_recordings(),        "Checking recordings…",             []),
            ("docker",          lambda: scanner.scan_docker(),            "Checking Docker…",                 {}),
            ("trash",           lambda: scanner.scan_trash(),             "Checking Trash…",                  {"size": 0, "path": ""}),
            ("language_files",  lambda: scanner.scan_language_files(),    "Scanning language files…",         []),
            ("mail_attachments",lambda: scanner.scan_mail_attachments(),  "Checking mail attachments…",       []),
        ]
        total = len(steps)
        data: dict = {}
        completed = [0]
        lock = threading.Lock()

        server.set_scanning("Scanning your Mac…", pct=0)

        def _run(key, fn, default):
            try:
                result = fn()
            except Exception:
                result = default
            with lock:
                data[key] = result
                completed[0] += 1
                pct = int(completed[0] / total * 90)
                server.set_scanning(f"Scanned {completed[0]} of {total}…", pct=pct)

        threads = [
            threading.Thread(target=_run, args=(key, fn, default), daemon=True)
            for key, fn, _label, default in steps
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        duplicate_groups = data.pop("duplicates")
        cache_sizes = data["cache_sizes"]
        result = {
            **data,
            "duplicates": [f for group in duplicate_groups for f in group[1:]],
            "cache_dirs": list(cache_sizes.keys()),
            "total_cache": sum(cache_sizes.values()),
        }
        server.set_scanning("Building report…", pct=95)
        html = report.build_report_html(result, port=port)
        server.set_done(html)
        self.title = None

    @rumps.clicked("Sweep Now")
    def sweep_now(self, _sender):
        self.title = None
        threading.Thread(target=self._sweep_and_report, daemon=True).start()

    def _sweep_and_report(self):
        # Sweep Now only cleans regeneratable items — caches, node_modules, Docker.
        # Files that require user judgment (screenshots, photos, downloads, recordings)
        # are left for the Scan Only UI where the user can review and decide.
        result = self._do_scan()

        cache_ok, cache_fail = cleaner.clean_caches(result["cache_dirs"])

        nm_ok, nm_fail = cleaner.clean_node_modules(result["node_modules"])

        docker_result = {}
        if result["docker"].get("available"):
            docker_result = cleaner.prune_docker()

        notifier.mark_cleaned()
        self._refresh_status()

        total_ok = cache_ok + nm_ok
        total_fail = cache_fail + nm_fail
        docker_msg = " · Docker pruned" if docker_result.get("success") else ""

        notifier.send_notification(
            "Sweep Done",
            f"Cleared {total_ok} caches & modules · {total_fail} error(s){docker_msg}",
        )
        self.title = None

    def _refresh_status(self):
        cfg = config.load()
        last = cfg.get("last_cleaned") or "never"
        self._status_item.title = f"Last cleaned: {last}"


if __name__ == "__main__":
    cfg = config.load()
    if notifier.should_remind(cfg):
        notifier.send_notification(
            "Sweep", "Time to clean up your Mac! Open Sweep to free some space."
        )
    SweepApp().run()
