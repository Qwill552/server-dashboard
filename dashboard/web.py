"""Small HTTP server for the dashboard and its metrics API."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .metrics import MetricsSampler


STATIC_DIR = Path(__file__).resolve().parent / "static"


def make_handler(sampler: MetricsSampler) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler API
            path = urlsplit(self.path).path
            if path == "/api/health":
                snapshot, _ = sampler.read()
                self._json({"status": "ok" if snapshot else "starting"}, 200 if snapshot else 503)
                return
            if path == "/api/metrics":
                snapshot, history = sampler.read()
                if snapshot is None:
                    self._json({"error": "Metrics are starting"}, 503)
                else:
                    self._json({"current": snapshot, "history": history})
                return

            files = {
                "/": "index.html",
                "/index.html": "index.html",
                "/app.css": "app.css",
                "/app.js": "app.js",
                "/favicon.svg": "favicon.svg",
            }
            filename = files.get(path)
            if filename is None:
                self.send_error(404)
                return
            content = (STATIC_DIR / filename).read_bytes()
            mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") or mime == "image/svg+xml" else mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def _json(self, payload: dict, status: int = 200) -> None:
            content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format: str, *args: object) -> None:
            if not self.path.startswith("/api/metrics"):
                super().log_message(format, *args)

    return DashboardHandler


def serve(sampler: MetricsSampler, host: str = "127.0.0.1", port: int = 5100) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(sampler))
    server.serve_forever()
