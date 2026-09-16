#!/usr/bin/env python3
"""Rate-limited public trigger for an immediate VidBot cron run."""
from __future__ import annotations

import json
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

ALLOWED_ORIGIN = "https://inspiretelapps.github.io"
COOLDOWN_SECONDS = 900
JOB_ID = "36d715897acd"
HERMES = "/opt/homebrew/bin/hermes"
STATE_FILE = Path.home() / ".hermes" / "state" / "vidbot-manual-refresh.json"


class RefreshGate:
    def __init__(self, allowed_origin: str, cooldown_seconds: int, state_file: Path | None = None):
        self.allowed_origin = allowed_origin
        self.cooldown_seconds = cooldown_seconds
        self.state_file = state_file
        self.lock = Lock()
        self.last_triggered = self._load()

    def _load(self) -> float:
        if not self.state_file:
            return 0
        try:
            return float(json.loads(self.state_file.read_text())["last_triggered"])
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return 0

    def _save(self) -> None:
        if not self.state_file:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({"last_triggered": self.last_triggered}) + "\n")

    def allow(self, origin: str | None, now: float | None = None) -> tuple[bool, int]:
        now = time.time() if now is None else now
        with self.lock:
            if origin != self.allowed_origin:
                return False, 403
            if now - self.last_triggered < self.cooldown_seconds:
                return False, 429
            self.last_triggered = now
            self._save()
            return True, 202


def make_handler(token: str, gate: RefreshGate):
    expected_path = f"/refresh/{token}"

    class Handler(BaseHTTPRequestHandler):
        def _cors(self) -> None:
            if self.headers.get("Origin") == gate.allowed_origin:
                self.send_header("Access-Control-Allow-Origin", gate.allowed_origin)
                self.send_header("Vary", "Origin")

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            if self.path != expected_path or self.headers.get("Origin") != gate.allowed_origin:
                self._json(403, {"ok": False, "message": "Not allowed"})
                return
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "3600")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path == "/health":
                self._json(200, {"ok": True, "service": "vidbot-manual-refresh"})
            else:
                self._json(404, {"ok": False, "message": "Not found"})

        def do_POST(self) -> None:
            if self.path != expected_path:
                self._json(404, {"ok": False, "message": "Not found"})
                return
            allowed, status = gate.allow(self.headers.get("Origin"))
            if not allowed:
                message = "Refresh was recently requested. Please wait a few minutes." if status == 429 else "Not allowed"
                self._json(status, {"ok": False, "message": message})
                return
            try:
                proc = subprocess.run(
                    [HERMES, "cron", "run", JOB_ID],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if proc.returncode:
                    raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "Could not start refresh")
            except Exception as exc:
                with gate.lock:
                    gate.last_triggered = 0
                    gate._save()
                self._json(500, {"ok": False, "message": str(exc)})
                return
            self._json(202, {
                "ok": True,
                "message": "Playlist refresh started. New summaries will be sent to WhatsApp.",
            })

        def log_message(self, fmt: str, *args) -> None:
            print(f"{self.address_string()} - {fmt % args}", flush=True)

    return Handler


def main() -> None:
    token = os.environ.get("VIDBOT_REFRESH_TOKEN", "").strip()
    if len(token) < 32:
        raise SystemExit("VIDBOT_REFRESH_TOKEN must contain at least 32 characters")
    port = int(os.environ.get("VIDBOT_REFRESH_PORT", "8787"))
    gate = RefreshGate(ALLOWED_ORIGIN, COOLDOWN_SECONDS, STATE_FILE)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(token, gate))
    print(f"VidBot manual refresh listening on 127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
