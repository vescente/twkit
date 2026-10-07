"""One persistent headless Chrome for the frame, driven over CDP (stdlib only)."""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = int(os.environ.get("TWKIT_FRAME_CDP_PORT", "9455"))
PROFILE = os.path.join(tempfile.gettempdir(), "twkit_frame_cdp_profile")


def _http(path: str, method: str = "GET", timeout: float = 2.0):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "null")


def _alive() -> bool:
    try:
        return "Browser" in (_http("/json/version") or {})
    except OSError:
        return False


def ensure_browser(timeout: float = 20.0) -> None:
    """Start the frame Chrome if it is not running (detached session, survives the caller)."""
    if _alive():
        return
    os.makedirs(PROFILE, exist_ok=True)
    subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={PROFILE}", "--no-first-run",
                      "--no-default-browser-check", "--hide-scrollbars", "--disable-gpu",
                      "--disable-extensions", "--mute-audio", "about:blank"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _alive():
            return
        time.sleep(0.2)
    raise RuntimeError(f"frame Chrome did not start on port {PORT}")


class _WS:
    """Minimal RFC 6455 websocket client: text frames, client mask, long frames, ping/close."""

    def __init__(self, url: str, timeout: float):
        rest = url.split("://", 1)[1]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.s = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                        f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError("websocket: no handshake response")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("websocket: handshake rejected")
        self.buf = head.split(b"\r\n\r\n", 1)[1]

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.s.recv(1 << 20)
            if not chunk:
                raise ConnectionError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text: str) -> None:
        data = text.encode()
        head = bytearray([0x81])
        n = len(data)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.s.sendall(bytes(head) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self) -> str:
        parts = []
        while True:
            b1, b2 = self._read(2)
            op, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            if op == 0x8:
                raise ConnectionError("websocket closed by server")
            if op == 0x9:
                self.s.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            parts.append(payload)
            if b1 & 0x80:
                return b"".join(parts).decode()

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


class Tab:
    """A tab in the frame Chrome; closes itself (`with Tab() as t:`)."""

    def __init__(self, timeout: float = 30.0):
        ensure_browser()
        self.timeout = timeout
        self.info = _http("/json/new?about:blank", method="PUT")
        self.ws = _WS(self.info["webSocketDebuggerUrl"], timeout)
        self._id = 0

    def call(self, method: str, **params):
        self._id += 1
        my = self._id
        self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        t0 = time.time()
        while time.time() - t0 < self.timeout:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == my:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method}: {msg['error'].get('message')}")
                return msg.get("result", {})
        raise TimeoutError(f"CDP {method}: no response within {self.timeout}s")

    def eval(self, expr: str):
        """Runtime.evaluate of the frame's own fixed JS on the frame's own page."""
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    def open(self, url: str, w: int, h: int, ready_js: str, wait: float = 15.0) -> None:
        """Open `url` in a w x h viewport and wait until `ready_js` is truthy."""
        self.call("Emulation.setDeviceMetricsOverride", width=w, height=h,
                  deviceScaleFactor=1, mobile=False)
        self.call("Page.navigate", url=url)
        t0 = time.time()
        while time.time() - t0 < wait:
            try:
                if self.eval(ready_js):
                    return
            except RuntimeError:
                pass
            time.sleep(0.15)
        raise TimeoutError(f"page not ready within {wait}s: {url[-80:]}")

    def screenshot(self, path: str) -> None:
        data = self.call("Page.captureScreenshot", format="png")["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))

    def close(self):
        self.ws.close()
        try:
            _http(f"/json/close/{self.info['id']}")
        except (OSError, ValueError):
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def shutdown() -> None:
    """Stop the frame Chrome (matched by its own profile dir)."""
    try:
        _http("/json/version")
    except OSError:
        return
    subprocess.run(["pkill", "-f", "--", f"--user-data-dir={PROFILE}"], capture_output=True)
