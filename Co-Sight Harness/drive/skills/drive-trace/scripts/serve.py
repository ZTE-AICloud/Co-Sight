#!/usr/bin/env python3
"""drive-trace serve: HTTP server rendering live drive trace.

Per PROP-20260920-001 §S5 + Q1 (A.2):
- startup skill runs this in background via Bash
- Serves on 127.0.0.1:<port>
- Each request reads latest .drive/<plan_dir>/ state and renders fresh HTML
- Browser uses meta-refresh (in render.py) to poll every 2s
- chrome-devtools (user MCP) opens the URL in a browser tab

Trigger flow:
  /drive → startup (Bash: python3 serve.py ...) → background daemon
  → chrome-devtools navigate_page("http://localhost:8080/")
  → user watches live trace in browser
"""

import argparse
import signal
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from render import load_data, render_html


class TraceHandler(BaseHTTPRequestHandler):
    plan_dir: Path = None
    mode: str = "phase"

    def do_GET(self):
        try:
            data = load_data(self.plan_dir, self.mode)
            html = render_html(data, self.mode)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            err = f"<!doctype html><html><body><h1>drive-trace error</h1><pre>{e}</pre></body></html>".encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)

    def log_message(self, fmt, *args):
        # Suppress default stderr logging; users can tail if needed
        pass


def _find_free_port(host: str, start: int, max_attempts: int = 50) -> int:
    """从 start 起探测空闲端口，最多 max_attempts 次。"""
    import socket
    for offset in range(max_attempts):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"未找到空闲端口（{start}–{start + max_attempts - 1}）")


def main():
    p = argparse.ArgumentParser(description="drive-trace HTTP server (live trace)")
    p.add_argument("--plan-dir", required=True, type=Path, help=".drive/<plan_dir> path")
    p.add_argument("--port", type=int, default=8080, help="HTTP port（default 8080；--auto-port 开启时作为探测起点）")
    p.add_argument(
        "--auto-port",
        action="store_true",
        help="从 --port 起向上探测空闲端口（默认 8080，多 plan 并行时避免冲突）",
    )
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
    p.add_argument("--mode", choices=["phase", "dag"], default="phase")
    args = p.parse_args()

    TraceHandler.plan_dir = args.plan_dir
    TraceHandler.mode = args.mode

    if args.auto_port:
        args.port = _find_free_port(args.host, args.port)

    server = HTTPServer((args.host, args.port), TraceHandler)
    print(f"drive-trace: serving {args.plan_dir} on http://{args.host}:{args.port}/", flush=True)
    print(f"drive-trace: PID={__import__('os').getpid()}", flush=True)

    def handle_term(signum, frame):
        print("drive-trace: shutting down", flush=True)
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGINT, handle_term)

    server.serve_forever()


if __name__ == "__main__":
    main()