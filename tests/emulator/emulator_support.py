"""Helpers for the emulator tests: the emulator, a calendar feed, a running subprocess."""

from __future__ import annotations

import json
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest


def wait_for(condition: Callable[[], object], what: str, timeout: float = 20.0) -> object:
    """Poll until `condition` returns something truthy, and return it."""
    deadline = time.monotonic() + timeout
    while True:
        value = condition()
        if value:
            return value
        if time.monotonic() > deadline:
            pytest.fail(f"gave up after {timeout:g}s waiting for {what}", pytrace=False)
        time.sleep(0.1)


class Emulator:
    """A running emulator, and the ways a test looks at what is on its display."""

    def __init__(self, port: int, log: Path) -> None:
        self.host = f"127.0.0.1:{port}"
        self.log = log
        self._url = f"http://{self.host}"

    def snapshot(self) -> dict:
        """The state the emulator's own web page gets: the frame, the API log, ..."""
        with httpx.stream("GET", f"{self._url}/events", timeout=5) as stream:
            event = None
            for line in stream.iter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:") and event == "state":
                    return json.loads(line[5:])
        raise AssertionError("the emulator's event stream ended without a state")

    def frame(self) -> dict:
        """What is on the front display: {application_name, priority, elements, ...}."""
        return self.snapshot()["frame"]

    def element_ids(self) -> list[str]:
        return [element["id"] for element in self.frame()["elements"]]

    def calls(self, since: float = 0.0) -> list[tuple[str, str, str]]:
        """(method, path, note) of the API calls since `since` (time.time()), oldest first."""
        log = [entry for entry in self.snapshot()["log"] if entry["t"] / 1000 >= since]
        return [(e["method"], e["path"], e["note"]) for e in reversed(log)]

    def get(self, path: str):
        return httpx.get(f"{self._url}{path}", timeout=5).json()

    def post(self, path: str, **body) -> httpx.Response:
        response = httpx.post(f"{self._url}{path}", json=body, timeout=5)
        response.raise_for_status()
        return response

    def reset(self) -> None:
        httpx.delete(f"{self._url}/api/display/draw", timeout=5).raise_for_status()
        self.post("/api/_scenario/reset")


class Feed:
    """A calendar feed on loopback: an ICS file `set` to whatever the test needs."""

    def __init__(self) -> None:
        self.body = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
        feed = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/calendar")
                self.send_header("Content-Length", str(len(feed.body)))
                self.end_headers()
                self.wfile.write(feed.body)

            def log_message(self, *args) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}/calendar.ics"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def set(self, *events: str) -> None:
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//busybar-calendar tests//EN"]
        lines += [*events, "END:VCALENDAR"]
        self.body = ("\r\n".join(lines) + "\r\n").encode()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def vevent(uid: str, title: str, start: datetime, end: datetime, status: str | None = None) -> str:
    """One VEVENT; STATUS:TENTATIVE is how a feed says "maybe"."""

    def utc(moment: datetime) -> str:
        return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

    lines = ["BEGIN:VEVENT", f"UID:{uid}@tests", f"DTSTAMP:{utc(datetime.now(UTC))}"]
    lines += [f"DTSTART:{utc(start)}", f"DTEND:{utc(end)}", f"SUMMARY:{title}"]
    if status:
        lines.append(f"STATUS:{status}")
    return "\r\n".join([*lines, "END:VEVENT"])


class Running:
    """A subprocess of the app, with its output kept for the failure message."""

    def __init__(self, process: subprocess.Popen, output: Path) -> None:
        self.process = process
        self.output = output

    def text(self) -> str:
        return self.output.read_text()

    def wait(self, timeout: float = 30) -> int:
        """Let a command that ends by itself finish, and return its exit code."""
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            pytest.fail(f"still running after {timeout:g}s:\n{self.text()}", pytrace=False)

    def stop(self, sig: int = signal.SIGTERM, timeout: float = 15) -> int:
        """Signal it, as `launchctl` or Ctrl-C would, and wait for it to finish."""
        if self.process.poll() is None:
            self.process.send_signal(sig)
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            pytest.fail(f"did not stop on signal {sig}:\n{self.text()}", pytrace=False)
