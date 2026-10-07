import json

import pytest

from twkit import chclient


class _Resp:
    def __init__(self, status=200, payload=None, text="", lines=()):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.content = b"x" if (payload is not None or text) else b""
        self._lines = list(lines)

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def close(self):
        pass


class _Session:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def post(self, url, data=None, headers=None, verify=None, timeout=None, stream=False):
        self.calls.append({"url": url, "body": data.decode(), "headers": headers})
        return self.resp


def _client(resp):
    c = chclient.HttpClickhouse.__new__(chclient.HttpClickhouse)
    c._session = _Session(resp)
    c._url = "https://example/"
    c._headers = {"X-ClickHouse-User": "bob", "X-ClickHouse-Key": "s3cret"}
    c._verify = True
    c._timeout = 5
    c._qs = "database=marts"
    return c


def test_password_in_headers_not_url():
    c = _client(_Resp(payload={"data": [[1]]}))

    c.execute("SELECT 1")

    call = c._session.calls[0]
    assert "s3cret" not in call["url"] and "bob" not in call["url"]
    assert call["headers"]["X-ClickHouse-Key"] == "s3cret"


@pytest.mark.parametrize("sql,expect_format", [
    ("SELECT 1", True), ("WITH a AS (SELECT 1) SELECT * FROM a", True),
    ("DESCRIBE t", True), ("SHOW TABLES", True),
    ("INSERT INTO t VALUES (1)", False), ("CREATE VIEW v AS SELECT 1", False),
])
def test_format_added_only_to_data_queries(sql, expect_format):
    c = _client(_Resp(payload={"data": []}))

    c.execute(sql)

    assert ("FORMAT JSONCompact" in c._session.calls[0]["body"]) is expect_format


def test_error_returns_server_words_not_url():
    c = _client(_Resp(status=403, text="Not enough privileges"))

    with pytest.raises(RuntimeError) as err:
        c.execute("SELECT 1")

    assert "Not enough privileges" in str(err.value)
    assert "https://" not in str(err.value)


def test_stream_takes_server_types_and_parses_null():
    resp = _Resp(lines=["a\tb", "String\tNullable(Int64)",
                        "x\t1", "y\t\\N", "", "with\\ttab\t2"])
    c = _client(resp)

    names, types, batches = c.query_stream("SELECT a, b FROM t", batch=2)
    rows = [r for b in batches for r in b]

    assert names == ["a", "b"] and types == ["String", "Nullable(Int64)"]
    assert rows[1] == ["y", None]
    assert rows[2][0] == "with\ttab"


def test_empty_stream_line_no_phantom_row():
    c = _client(_Resp(lines=["a", "String", "x", "", "y"]))

    _, _, batches = c.query_stream("SELECT a FROM t")

    assert [r[0] for b in batches for r in b] == ["x", "y"]


def test_without_host_refuses_loudly():
    with pytest.raises(RuntimeError, match="host"):
        chclient.HttpClickhouse(host="", port="8443", user="u", password="p")


def test_network_failure_does_not_print_server_address():
    import requests

    class _Dead:
        def post(self, *a, **k):
            raise requests.ConnectionError(
                "HTTPSConnectionPool(host='10.20.30.40', port=8443): Max retries "
                "exceeded with url: https://10.20.30.40:8443/?database=marts")

    c = _client(_Resp())
    c._session = _Dead()

    with pytest.raises(RuntimeError) as err:
        c.execute("SELECT 1")

    text = str(err.value)
    assert "10.20.30.40" not in text
    assert "unavailable" in text and "ConnectionError" in text


def test_address_stripped_from_server_response():
    c = _client(_Resp(status=500, text="cannot reach https://10.20.30.40:9000 replica"))

    with pytest.raises(RuntimeError) as err:
        c.execute("SELECT 1")

    assert "10.20.30.40" not in str(err.value)
