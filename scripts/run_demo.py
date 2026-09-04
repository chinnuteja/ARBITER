#!/usr/bin/env python3
"""Serve the local ARBITER claim-review demonstration."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "src"))

from arbiter.demo.service import (  # noqa: E402
    benchmark_payload,
    case_payload,
    case_summaries,
    load_demo_data,
)


STATIC_ROOT = ROOT / "src/arbiter/demo/static"


def build_handler(data):
    class DemoHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            print(f"[arbiter-demo] {format % args}")

        def _send_json(self, status: HTTPStatus, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path) -> None:
            body = path.read_bytes()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/cases":
                self._send_json(HTTPStatus.OK, {"cases": case_summaries(data)})
                return
            if path == "/api/benchmark":
                self._send_json(HTTPStatus.OK, benchmark_payload(data))
                return
            if path.startswith("/api/case/"):
                try:
                    self._send_json(HTTPStatus.OK, case_payload(data, path.rsplit("/", 1)[-1]))
                except KeyError:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown case"})
                return
            if path in {"/", "/index.html"}:
                self._send_file(STATIC_ROOT / "index.html")
                return
            candidate = (STATIC_ROOT / path.lstrip("/")).resolve()
            if STATIC_ROOT.resolve() in candidate.parents and candidate.is_file():
                self._send_file(candidate)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    return DemoHandler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    data = load_demo_data(ROOT)
    server = ThreadingHTTPServer((args.host, args.port), build_handler(data))
    print(f"ARBITER demo: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
