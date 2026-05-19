#!/usr/bin/env python3
"""Local browser GUI server for the VCMI battle estimator."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
STATIC_DIR = Path(__file__).with_name("battle_estimator_gui")
STATIC_ROUTES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/style.css": "style.css",
}
CONTENT_TYPES = {
    "html": "text/html; charset=utf-8",
    "js": "application/javascript; charset=utf-8",
    "css": "text/css; charset=utf-8",
}


class BattleEstimatorGuiHandler(BaseHTTPRequestHandler):
    """HTTP handler for the local read-only GUI."""

    server_version = "VCMIBattleEstimatorGUI/0.1"

    def do_GET(self):
        self._handle_get(send_body=True)

    def do_HEAD(self):
        self._handle_get(send_body=False)

    def _handle_get(self, send_body: bool):
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._send_json({"ok": True}, send_body=send_body)
            return

        static_name = STATIC_ROUTES.get(path)
        if static_name is not None:
            self._send_static(static_name, send_body=send_body)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _send_json(self, payload, send_body: bool):
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def _send_static(self, static_name: str, send_body: bool):
        path = STATIC_DIR / static_name
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Static asset not found")
            return

        body = path.read_bytes()
        suffix = path.suffix.lstrip(".")
        content_type = CONTENT_TYPES.get(suffix, "application/octet-stream")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def log_message(self, format, *args):  # pragma: no cover - log noise only.
        return


def create_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> ThreadingHTTPServer:
    """Create a local GUI HTTP server without starting its serve loop."""

    return ThreadingHTTPServer((host, port), BattleEstimatorGuiHandler)


def server_url(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="VCMI Battle Estimator GUI")
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="host interface to bind; defaults to localhost only",
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_PORT,
        type=int,
        help=f"TCP port to bind; defaults to {DEFAULT_PORT}",
    )
    args = parser.parse_args(argv)

    server = create_server(args.host, args.port)
    print(server_url(server), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping GUI server.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
