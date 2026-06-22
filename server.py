import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import cleaner
import notifier

_instance: HTTPServer | None = None
_port: int = 0
_lock = threading.Lock()

# scan state — written by main.py, read by GET /status and GET /report
_state: dict = {"scanning": False, "step": "", "pct": 0, "report_html": None}
_loading_html: str | None = None
_scan_trigger: threading.Event = threading.Event()


def get_port() -> int:
    return _port


def start() -> int:
    global _instance, _port
    with _lock:
        if _instance:
            return _port
        srv = HTTPServer(("127.0.0.1", 0), _Handler)
        _port = srv.server_address[1]
        _instance = srv
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
    return _port


def set_loading(html: str) -> None:
    global _loading_html
    _loading_html = html


def set_scanning(step: str, pct: int = 0) -> None:
    _state["scanning"] = True
    _state["step"] = step
    _state["pct"] = pct
    _state["report_html"] = None


def set_done(html: str) -> None:
    _state["scanning"] = False
    _state["step"] = ""
    _state["report_html"] = html


def clear_scan_trigger() -> None:
    _scan_trigger.clear()


def wait_for_scan_trigger(timeout: float = 3600) -> bool:
    """Block until browser requests a rescan. Returns True if triggered."""
    return _scan_trigger.wait(timeout=timeout)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, content: str):
        body = content.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _js(self, body: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/assets/lucide.min.js":
            import os, sys
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            fpath = os.path.join(base, "assets", "lucide.min.js")
            try:
                with open(fpath, "rb") as f:
                    self._js(f.read())
            except OSError:
                self._json({"error": "not found"}, 404)

        elif path == "/loading":
            if _loading_html:
                self._html(_loading_html)
            else:
                self._json({"error": "not ready"}, 503)

        elif path == "/status":
            self._json({
                "scanning": _state["scanning"],
                "step": _state["step"],
                "pct": _state["pct"],
                "ready": _state["report_html"] is not None,
            })

        elif path == "/report":
            if _state["report_html"]:
                self._html(_state["report_html"])
            else:
                self._json({"error": "not ready"}, 503)

        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            path = urlparse(self.path).path

            if path == "/clean/files":
                ok, fail = cleaner.move_to_trash(body.get("paths", []))
                if ok: notifier.mark_cleaned()
                self._json({"ok": ok, "fail": fail})

            elif path == "/clean/caches":
                ok, fail = cleaner.clean_caches(body.get("dirs", []))
                if ok: notifier.mark_cleaned()
                self._json({"ok": ok, "fail": fail})

            elif path == "/clean/node_modules":
                items = [{"path": p} for p in body.get("paths", [])]
                ok, fail = cleaner.clean_node_modules(items)
                if ok: notifier.mark_cleaned()
                self._json({"ok": ok, "fail": fail})

            elif path == "/clean/docker":
                result = cleaner.prune_docker()
                if result.get("success"): notifier.mark_cleaned()
                self._json(result)

            elif path == "/clean/trash":
                result = cleaner.empty_trash()
                if result.get("success"): notifier.mark_cleaned()
                self._json(result)

            elif path == "/clean/lang":
                ok, fail = cleaner.delete_permanent(body.get("paths", []))
                if ok: notifier.mark_cleaned()
                self._json({"ok": ok, "fail": fail})

            elif path == "/reveal":
                import subprocess as _sp
                _sp.run(["open", "-R", body.get("path", "")], capture_output=True)
                self._json({"ok": True})

            elif path == "/rescan":
                _state["report_html"] = None
                _scan_trigger.set()
                self._json({"ok": True})

            else:
                self._json({"error": "not found"}, 404)

        except Exception as e:
            self._json({"ok": 0, "fail": 0, "error": str(e)}, 500)
