"""A minimal ClickHouse HTTP client used when no settings module provides one."""
from __future__ import annotations

import re

DATA_HEADS = ("SELECT", "SHOW", "DESCRIBE", "DESC", "EXISTS", "WITH")


def _unescape(value: str):
    """TSV escaping, as ClickHouse writes it."""
    if value == "\\N":
        return None
    if "\\" not in value:
        return value
    return (value.replace("\\t", "\t").replace("\\n", "\n")
                 .replace("\\r", "\r").replace("\\\\", "\\"))


class HttpClickhouse:
    """ClickHouse over HTTPS."""

    _read_only = False
    _account_ro = None

    def __init__(self, host: str, port: str, user: str, password: str,
                 db: str = "", cert: str = "", timeout: int = 300, read_only: bool = False):
        import requests                       # noqa: PLC0415 — optional dependency

        if not host:
            raise RuntimeError("ClickHouse host is not configured")
        self._session = requests.Session()
        self._url = f"https://{host}:{port or 8443}/"
        self._headers = {"X-ClickHouse-User": user, "X-ClickHouse-Key": password}
        self._verify = cert or True
        self._timeout = timeout
        import urllib.parse                   # noqa: PLC0415 — local by design
        self._qs = urllib.parse.urlencode({"database": db}) if db else ""
        self._read_only = read_only

    @staticmethod
    def scrub(text: str) -> str:
        """Strip the server address from an error text."""
        text = re.sub(r"host='[^']*'", "host='<hidden>'", text)
        text = re.sub(r"https?://[^\s/'\"]+", "<address hidden>", text)
        return re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<address hidden>", text)

    def _request(self, body: bytes, stream: bool = False):
        """One network round trip."""
        import requests                       # noqa: PLC0415 — optional dependency

        qs = self._qs
        if self._read_only and not self._account_read_only():
            qs = "&".join(x for x in (qs, "readonly=1") if x)
        try:
            return self._session.post(f"{self._url}?{qs}", data=body,
                                      headers=self._headers, verify=self._verify,
                                      timeout=self._timeout, stream=stream)
        except requests.RequestException as exc:
            raise RuntimeError(
                f"ClickHouse unavailable: {type(exc).__name__}: "
                f"{self.scrub(str(exc))[:300]}") from None

    def _account_read_only(self) -> bool:
        """Is the account itself at readonly=1? Asked once, by a fixed query.

        Such an account may not set `readonly` again; any other answer, or no answer,
        keeps `readonly=1` on every query.
        """
        if self._account_ro is None:
            self._account_ro = False
            try:
                resp = self._session.post(
                    f"{self._url}?{self._qs}",
                    data=b"SELECT getSetting('readonly') FORMAT JSONCompact",
                    headers=self._headers, verify=self._verify, timeout=self._timeout)
                if resp.status_code < 400:
                    self._account_ro = str(resp.json()["data"][0][0]) == "1"
            except Exception:                 # noqa: BLE001 — unknown means protect
                pass
        return self._account_ro

    def _fail(self, resp) -> None:
        """Raise the SERVER's words, never `raise_for_status()`."""
        raise RuntimeError(f"ClickHouse {resp.status_code}: "
                           f"{self.scrub((resp.text or '').strip())[:500] or 'empty answer'}")

    def execute(self, query: str, params: dict = None) -> list:
        """Run a query and return rows as lists."""
        text = (query % params if params else query).strip()
        head = text.split(None, 1)[0].upper() if text else ""
        returns_data = head in DATA_HEADS
        body = (text + " FORMAT JSONCompact") if returns_data else text
        resp = self._request(body.encode())
        if resp.status_code >= 400:
            self._fail(resp)
        if not resp.content or not returns_data:
            return []
        return resp.json().get("data", [])

    def query_stream(self, query: str, batch: int = 50_000):
        """`(names, types, generator of row batches)` — the memory-safe path."""
        text = query.strip().rstrip(";")
        resp = self._request((text + " FORMAT TSVWithNamesAndTypes").encode(),
                             stream=True)
        if resp.status_code >= 400:
            self._fail(resp)
        lines = resp.iter_lines(decode_unicode=True)
        names = next(lines, "").split("\t")
        types = next(lines, "").split("\t")

        def batches():
            buf = []
            for line in lines:
                if line == "":
                    continue
                buf.append([_unescape(x) for x in line.split("\t")])
                if len(buf) >= batch:
                    yield buf
                    buf = []
            if buf:
                yield buf
            resp.close()

        return names, types, batches()
