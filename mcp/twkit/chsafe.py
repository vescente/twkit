"""Keep the password out of tracebacks."""
from __future__ import annotations

import functools
import re

_MASKS = (
    re.compile(r"(password=)[^&\s'\"]+", re.I),
    re.compile(r"(key=)[^&\s'\"]+", re.I),
    re.compile(r"(://[^:/\s]+:)[^@/\s]+(@)"),
)


def scrub(text: str) -> str:
    """Replace secrets in text with ***."""
    out = str(text)
    for rx in _MASKS:
        out = rx.sub(lambda m: "".join(m.groups()[:-1]) + "***" + (m.groups()[-1]
                     if len(m.groups()) > 1 else ""), out)
    return out


class ScrubbedError(RuntimeError):
    """ClickHouse error with the server address removed."""


def guard(fn):
    """Wrap a function that queries ClickHouse."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            raise ScrubbedError(f"{type(exc).__name__}: {scrub(exc)}") from None
    return wrapper


READ_HEADS = ("SELECT", "WITH")
# A read head may still carry a write: `WITH t AS (...) INSERT INTO ...` is valid in Hyper.
_WRITES = re.compile(r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|COPY|MERGE)\b", re.I)

# Table functions allowed right after FROM / JOIN: they generate rows and touch nothing.
_TABLE_FUNCS_OK = {"numbers", "numbers_mt", "zeros", "zeros_mt", "values",
                   "generate_series", "generateseries", "view"}

# Table functions reach outside the database: files, URLs, other servers, processes.
_OUTSIDE = {
    "azureblobstorage", "azureblobstoragecluster", "cluster", "clusterallreplicas",
    "deltalake", "executable", "external", "file", "filecluster", "gcs", "hdfs",
    "hdfscluster", "hudi", "iceberg", "icebergs3", "input", "jdbc", "mongodb", "mysql",
    "odbc", "postgresql", "redis", "remote", "remotesecure", "s3", "s3cluster",
    "sqlite", "url", "urlcluster", "cosn", "oss", "gcs", "icebergazure", "iceberghdfs",
    "iceberglocal", "icebergs3cluster", "deltalakecluster", "hudicluster", "paimon",
    "dictionary", "loop", "merge", "mergetreeindex", "fuzzjson", "fuzzquery",
}


def _code_only(sql: str) -> str:
    """The query with comments removed and literals and quoted names blanked.

    Read the same way by ClickHouse and Hyper (PostgreSQL), or refused: a backslash before
    a closing quote ends the string in one dialect and escapes it in the other; `$` opens a
    dollar-quoted string; `#` is a comment in one and an operator in the other.
    """
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c in "'\"`":
            j = i + 1
            while j < n:
                if sql[j] == "\\":
                    if j + 1 < n and sql[j + 1] == c:
                        raise PermissionError("refused: backslash before a quote reads two ways")
                    j += 2
                    continue
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                raise PermissionError("refused: unterminated quote in the query")
            name = sql[i + 1:j]
            if c == "'":
                out.append(" '' ")
            elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                out.append(f" {name} ")
            else:
                out.append(" _q ")
            i = j + 1
        elif sql.startswith("--", i):
            m = re.compile(r"[\r\n]").search(sql, i)
            i = m.start() if m else n
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j < 0:
                raise PermissionError("refused: unterminated comment in the query")
            out.append(" ")
            i = j + 2
        elif c in "$#":
            raise PermissionError(f"refused: '{c}' outside a string reads two ways")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def read_only(sql: str, heads: tuple = READ_HEADS) -> str:
    """`sql` unchanged if it is one read statement; PermissionError otherwise.

    SQL from a workbook or a tool argument is untrusted: one statement, a read head,
    no file output, no table function that reaches outside the database.
    """
    code = _code_only(sql or "").strip()
    while code.endswith(";"):
        code = code[:-1].rstrip()
    if not code:
        raise PermissionError("refused: empty query")
    if ";" in code:
        raise PermissionError("refused: more than one statement")
    head = re.match(r"[\s(]*([A-Za-z]+)", code)
    if not head or head.group(1).upper() not in heads:
        raise PermissionError(f"refused: only {'/'.join(heads)} queries run here")
    if re.search(r"\bINTO\s+OUTFILE\b", code, re.I):
        raise PermissionError("refused: INTO OUTFILE")
    write = _WRITES.search(code)
    if write:
        raise PermissionError(f"refused: {write.group(1).upper()} inside a read query")
    for name in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", code):
        if name.lower() in _OUTSIDE:
            raise PermissionError(f"refused: table function {name}() reaches outside the database")
    for name in _table_functions(code):
        if name.lower() not in _TABLE_FUNCS_OK:
            raise PermissionError(f"refused: table function {name}() is not on the allowed list")
    return sql


_CLAUSE_END = {"WHERE", "PREWHERE", "GROUP", "ORDER", "LIMIT", "HAVING", "UNION", "SETTINGS",
               "FORMAT", "WINDOW", "QUALIFY", "INTERSECT", "EXCEPT", "OFFSET", "SAMPLE"}


def _table_functions(code: str) -> list:
    """Names called in a table position: after FROM, JOIN, IN, or a comma inside a FROM list.

    `EXTRACT(YEAR FROM f(x))`, `SUBSTRING(s FROM n)` and `IS DISTINCT FROM f(x)` are scalars.
    """
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[(),]", code)
    calls, in_from, found = [], [False], []
    for k, t in enumerate(toks):
        prev = toks[k - 1].upper() if k else ""
        if t == "(":
            calls.append(k > 0 and toks[k - 1] not in "()," and prev not in
                         ("FROM", "JOIN", "IN", "AS", "SELECT", "WHERE", "AND", "OR", "ON",
                          "NOT", "EXISTS", "ALL", "ANY", "UNION", "WITH"))
            in_from.append(False)
            continue
        if t == ")":
            calls and calls.pop()
            len(in_from) > 1 and in_from.pop()
            continue
        up = t.upper()
        in_call = bool(calls and calls[-1])
        if up in ("FROM", "JOIN") and not in_call and prev != "DISTINCT":
            in_from[-1] = True
        elif up in _CLAUSE_END:
            in_from[-1] = False
        if t in "()," or (toks[k + 1] if k + 1 < len(toks) else "") != "(":
            continue
        after_from = prev in ("FROM", "JOIN") and (k < 2 or toks[k - 2].upper() != "DISTINCT")
        if prev == "IN" or (not in_call and (after_from or (prev == "," and in_from[-1]))):
            found.append(t)
    return found
