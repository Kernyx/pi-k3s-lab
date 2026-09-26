#!/usr/bin/env python3
"""A small, private homelab portal using only the Python standard library."""

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import threading
import time
from urllib.parse import urlsplit

ASSETS = Path(__file__).parent


def load_config(path):
    if path.stat().st_size > 16384:
        raise ValueError("Configuration exceeds 16 KiB")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Configuration must be an object")
    title = data.get("title")
    links = data.get("links")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 80:
        raise ValueError("Title must contain 1 to 80 characters")
    if not isinstance(links, list) or not 1 <= len(links) <= 20:
        raise ValueError("Expected 1 to 20 links")
    validated = []
    for link in links:
        if not isinstance(link, dict):
            raise ValueError("Each link must be an object")
        name, url, description = link.get("name"), link.get("url"), link.get("description", "")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 64:
            raise ValueError("Link name must contain 1 to 64 characters")
        if not isinstance(description, str) or len(description) > 160:
            raise ValueError("Link description must be at most 160 characters")
        if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() or ord(c) < 32 for c in url):
            raise ValueError("Invalid link URL")
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError("Links must use HTTP(S) without embedded credentials")
        _ = parsed.port  # Also reject malformed or out-of-range port numbers.
        validated.append({"name": name.strip(), "url": url, "description": description})
    return {"title": title.strip(), "links": validated}


class PortalServer(ThreadingHTTPServer):
    # Wait for existing requests on shutdown; each connection has a finite timeout.
    daemon_threads = False

    def __init__(self, address, config_path, version="dev", instance="local"):
        self.version = version
        self.instance = instance
        self.started = time.monotonic()
        try:
            self.config = load_config(config_path)
        except (OSError, ValueError):
            self.config = None
            print("Configuration unavailable or invalid; readiness will fail", flush=True)
        super().__init__(address, PortalHandler)


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "HomePortal"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def do_GET(self):
        self.respond()

    def do_HEAD(self):
        self.respond(head=True)

    def respond(self, head=False):
        path = urlsplit(self.path).path
        status, content_type = 200, "application/json; charset=utf-8"
        if path == "/healthz":
            body = {"status": "alive"}
        elif path == "/readyz":
            status = 200 if self.server.config is not None else 503
            body = {"status": "ready" if status == 200 else "configuration unavailable"}
        elif path == "/api/config":
            status = 200 if self.server.config is not None else 503
            body = self.server.config if status == 200 else {"error": "configuration unavailable"}
        elif path == "/api/info":
            body = {"version": self.server.version, "instance": self.server.instance,
                    "uptime_seconds": int(time.monotonic() - self.server.started)}
        elif path in ("/", "/style.css", "/app.js"):
            filename, content_type = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            }[path]
            body = (ASSETS / filename).read_bytes()
        else:
            status, body = 404, {"error": "not found"}
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def log_request(self, code="-", size="-"):
        path = urlsplit(self.path).path
        if path not in ("/healthz", "/readyz"):
            print(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "path": path,
                              "method": self.command, "status": code}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-config", type=Path)
    args = parser.parse_args()
    if args.check_config:
        load_config(args.check_config)
        print("Configuration valid")
        return
    config = Path(os.environ.get("PORTAL_CONFIG", str(ASSETS / "links.example.json")))
    server = PortalServer(("0.0.0.0", 8080), config, os.environ.get("APP_VERSION", "dev"),
                          os.environ.get("POD_NAME", "local"))
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(f"Home portal listening on :8080, version={server.version}", flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
