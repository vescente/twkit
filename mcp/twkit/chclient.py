"""A minimal ClickHouse HTTP client: the only way twkit reaches ClickHouse."""
from __future__ import annotations

import re

DATA_HEADS = ("SELECT", "SHOW", "DESCRIBE", "DESC", "EXISTS", "WITH")
# memory per untrusted query: the server itself has no cap (max_memory_usage = 0)
READ_MEMORY = 3_000_000_000


_TSV_ESCAPES = {"b": "\b", "f": "\f", "r": "\r", "n": "\n", "t": "\t", "0": "\0",
                "'": "'", "\\": "\\"}


def _unescape(value: str):
    """TSV escaping, as ClickHouse writes it: one pass, so `\\\\n` stays a backslash and an `n`."""
    if value == "\\N":
        return None
    if "\\" not in value:
        return value
    return re.sub(r"\\(.)", lambda m: _TSV_ESCAPES.get(m.group(1), m.group(1)), value)


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

    def _request(self, body: bytes, stream: bool = False, params: dict | None = None):
        """One network round trip."""
        import requests                       # noqa: PLC0415 — optional dependency
        import urllib.parse                   # noqa: PLC0415 — local by design

        params = dict(params or {})
        if self._read_only and not self._account_read_only():
            # untrusted SQL also gets server limits; they must precede readonly=1 in the URL
            for k, v in (("max_execution_time", self._timeout), ("max_memory_usage", READ_MEMORY),
                         ("max_bytes_before_external_group_by", READ_MEMORY // 3),
                         ("cancel_http_readonly_queries_on_client_close", 1)):
                params.setdefault(k, v)
            qs = "&".join(x for x in (self._qs, urllib.parse.urlencode(params), "readonly=1") if x)
        else:
            qs = "&".join(x for x in (self._qs, urllib.parse.urlencode(params)) if x)
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
        body = (text + "\nFORMAT JSONCompact") if returns_data else text
        resp = self._request(body.encode())
        if resp.status_code >= 400:
            self._fail(resp)
        if not resp.content or not returns_data:
            return []
        return resp.json().get("data", [])

    def explain_ast(self, query: str) -> list:
        """ClickHouse's parse tree of `query`, one line per node; nothing runs.

        Sent on its own (one statement per request), never inside another query. The output
        format is pinned twice, by a FORMAT clause of our own and by `default_format`; a query
        that brings its own FORMAT fails to parse and is refused.
        """
        text = query.strip()
        while text.endswith(";"):
            text = text[:-1].rstrip()
        resp = self._request(f"EXPLAIN AST {text}\nFORMAT TabSeparated".encode(),
                             params={"default_format": "TabSeparated"})
        if resp.status_code >= 400:
            self._fail(resp)
        return [_unescape(x) for x in resp.text.split("\n") if x]

    def query_stream(self, query: str, batch: int = 50_000):
        """`(names, types, generator of row batches)` — the memory-safe path."""
        text = query.strip().rstrip(";")
        resp = self._request((text + "\nFORMAT TSVWithNamesAndTypes").encode(),
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
