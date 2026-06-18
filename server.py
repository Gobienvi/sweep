import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import cleaner

_instance: HTTPServer | None = None
_port: int = 0
_lock = threading.Lock()

# scan state — written by main.py, read by GET /status and GET /report
_state: dict = {"scanning": False, "step": "", "report_html": None}


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


def set_scanning(step: str) -> None:
    _state["scanning"] = True
    _state["step"] = step
    _state["report_html"] = None


def set_done(html: str) -> None:
    _state["scanning"] = False
    _state["step"] = ""
    _state["report_html"] = html


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, content: str):
        body = content.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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

        if path == "/status":
            self._json({
                "scanning": _state["scanning"],
                "step": _state["step"],
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
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        path = urlparse(self.path).path

        if path == "/clean/files":
            ok, fail = cleaner.move_to_trash(body.get("paths", []))
            self._json({"ok": ok, "fail": fail})

        elif path == "/clean/caches":
            ok, fail = cleaner.clean_caches(body.get("dirs", []))
            self._json({"ok": ok, "fail": fail})

        elif path == "/clean/node_modules":
            items = [{"path": p} for p in body.get("paths", [])]
            ok, fail = cleaner.clean_node_modules(items)
            self._json({"ok": ok, "fail": fail})

        elif path == "/clean/docker":
            self._json(cleaner.prune_docker())

        else:
            self._json({"error": "not found"}, 404)
