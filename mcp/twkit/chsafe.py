"""ClickHouse safety: secrets out of tracebacks; untrusted SQL only as one read statement."""
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
    "arrowflight", "ytsaurus", "prometheusquery", "prometheusqueryrange", "deltalakes3",
    "deltalakeazure", "deltalakelocal", "deltalakes3cluster", "deltalakeazurecluster",
    "icebergazurecluster", "iceberghdfscluster", "icebergcluster", "paimons3", "paimonazure",
    "paimonhdfs", "paimonlocal", "paimons3cluster", "paimonazurecluster", "paimonhdfscluster",
    "viewifpermitted", "timeseriesdata", "timeseriesmetrics", "timeseriestags",
    "timeseriesselector", "mergetreeprojection", "mergetreeanalyzeindexes",
}


def _code_only(sql: str) -> str:
    """The query with comments removed and literals and quoted names blanked.

    Read the same way by ClickHouse and Hyper (PostgreSQL), or refused: a backslash before
    a closing quote ends the string in one dialect and escapes it in the other; `$` opens a
    dollar-quoted string; `#` is a comment in one and an operator in the other. Comments
    are refused where a parser could end them elsewhere: nested `/*` and a lone `\\r`.
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
            j = sql.find("\n", i)
            j = n if j < 0 else j
            if re.search(r"\r(?!\n|$)", sql[i:j + 1]):
                raise PermissionError("refused: a carriage return ends a comment in one dialect only")
            out.append(" ")
            i = j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j < 0:
                raise PermissionError("refused: unterminated comment in the query")
            if "/*" in sql[i + 2:j]:
                raise PermissionError("refused: nested comments end in different places")
            out.append(" ")
            i = j + 2
        elif c in "$#":
            raise PermissionError(f"refused: '{c}' outside a string reads two ways")
        elif ord(c) > 127:
            raise PermissionError(f"refused: '{c}' outside a string reads two ways "
                                  f"(ClickHouse takes curly quotes as quotes)")
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
    depth = 0
    for ch in code:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth < 0:
            break
    if depth:
        raise PermissionError("refused: unbalanced brackets")
    head = re.match(r"[\s(]*([A-Za-z]+)", code)
    if not head or head.group(1).upper() not in heads:
        raise PermissionError(f"refused: only {'/'.join(heads)} queries run here")
    if re.search(r"\bINTO\s+OUTFILE\b", code, re.I):
        raise PermissionError("refused: INTO OUTFILE")
    if re.search(r"\bFORMAT\s+[A-Za-z_]", code, re.I):
        raise PermissionError("refused: a FORMAT clause; the caller chooses the output format")
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


# Keywords that precede a bracket without calling anything.
_NOT_CALLS = ("FROM", "JOIN", "IN", "AS", "SELECT", "WHERE", "AND", "OR", "ON", "NOT", "EXISTS",
              "ALL", "ANY", "UNION", "WITH", "USING", "OVER", "BY", "WHEN", "THEN", "ELSE", "CASE",
              "HAVING", "DISTINCT")

_READ_ROOTS = {"SelectWithUnionQuery", "SelectIntersectExceptQuery", "DescribeQuery"}
# One node per line: indent, node type, an optional word, then `(children N)` if it has any.
_AST_LINE = re.compile(r"( *)([A-Z][A-Za-z]*)(?= |$)(.*?)(?: \(children (\d+)\))?$")


def ast_read_only(lines: list) -> None:
    """Refuse what ClickHouse's own parse (`EXPLAIN AST` lines) shows is not a plain read.

    One root that reads; no table function off the allowed list; no function that reaches
    outside the database anywhere. The tree is the server's, so no lexer can read it otherwise.
    """
    nodes, stack, declared = [], [], []
    for line in lines:
        text = str(line).rstrip("\r")
        m = _AST_LINE.match(text)
        if not m:
            raise PermissionError("refused: the server's parse tree is not in the expected form")
        depth = len(m.group(1))
        if depth > (nodes[-1][0] + 1 if nodes else 0):
            raise PermissionError("refused: the server's parse tree is not in the expected form")
        while stack and nodes[stack[-1]][0] >= depth:
            stack.pop()
        if stack:
            declared[stack[-1]][1] += 1
        kind, rest = m.group(2), m.group(3).split()
        name = rest[0] if kind == "Function" and rest and not rest[0].startswith("(") else ""
        nodes.append((depth, kind, name, nodes[stack[-1]][1] if stack else ""))
        declared.append([int(m.group(4) or 0), 0])
        stack.append(len(nodes) - 1)
    if any(want != got for want, got in declared):
        raise PermissionError("refused: the server's parse tree is not in the expected form")
    roots = [n for n in nodes if n[0] == 0]
    if len(roots) != 1 or roots[0][1] not in _READ_ROOTS:
        raise PermissionError("refused: ClickHouse does not read this as one SELECT")
    for _, kind, name, parent in nodes:
        if kind != "Function":
            continue
        if name.lower() in _OUTSIDE:
            raise PermissionError(f"refused: {name}() reaches outside the database")
        if parent == "TableExpression" and name.lower() not in _TABLE_FUNCS_OK:
            raise PermissionError(f"refused: table function {name}() is not on the allowed list")


class ReadOnlyClient:
    """ClickHouse for untrusted SQL: the lexical guard, then the server's parse, then the query.

    A read runs as a subquery, `SELECT * FROM (<sql>)`, the way Tableau runs Custom SQL; a
    DESCRIBE runs as it is. `EXPLAIN AST` parses exactly that statement, and exactly that
    statement runs: what was checked is what executes. Only `execute` and `query_stream` exist.
    """

    HEADS = READ_HEADS + ("DESCRIBE", "DESC")

    def __init__(self, client):
        self._client = client

    def check(self, sql: str) -> str:
        """The statement that will run, or PermissionError."""
        read_only(sql, self.HEADS)
        body = sql.strip()
        while body.endswith(";"):
            body = body[:-1].rstrip()
        head = re.match(r"[\s(]*([A-Za-z]+)", _code_only(body)).group(1).upper()
        stmt = body if head in ("DESCRIBE", "DESC") else f"SELECT * FROM (\n{body}\n)"
        try:
            lines = self._client.explain_ast(stmt)
        except Exception as exc:                # noqa: BLE001 — refused, not hidden
            raise PermissionError(
                f"refused: ClickHouse could not parse the query: {scrub(exc)[:200]}") from None
        ast_read_only(lines)
        return stmt

    def execute(self, query: str) -> list:
        return self._client.execute(self.check(query))

    def query_stream(self, query: str, batch: int = 50_000):
        return self._client.query_stream(self.check(query), batch=batch)


_CLAUSE_END = {"WHERE", "PREWHERE", "GROUP", "ORDER", "LIMIT", "HAVING", "UNION", "SETTINGS",
               "FORMAT", "WINDOW", "QUALIFY", "INTERSECT", "EXCEPT", "OFFSET", "SAMPLE"}


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _table_functions(code: str) -> list:
    """Names called in a table position: after FROM, JOIN, IN, or a comma inside a FROM list.

    `EXTRACT(YEAR FROM f(x))`, `SUBSTRING(s FROM n)` and `IS DISTINCT FROM f(x)` are scalars.
    A bracket opening SELECT or WITH is a subquery wherever it stands (`view(SELECT ...)`), and a
    bracket in a table position keeps the position (`FROM (f(...))`).
    """
    # operators stay tokens: `a + (b)` is arithmetic, not a call of `a`
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[(),]|[^\sA-Za-z0-9_(),]+", code)
    calls, in_from, found = [], [False], []

    def tok(k):
        return toks[k].upper() if 0 <= k < len(toks) else ""

    def table_pos(k, bracket=False):
        prev = tok(k - 1)
        after_from = prev in ("FROM", "JOIN") and tok(k - 2) != "DISTINCT"
        in_call = bool(calls and calls[-1])
        return (prev == "IN" and not bracket) or \
            (not in_call and (after_from or (prev in (",", "(") and in_from[-1])))

    for k, t in enumerate(toks):
        prev = tok(k - 1)
        if t == "(":
            sub = tok(k + 1) in ("SELECT", "WITH")
            # the bracket's position is judged where it stands, before it opens its own level:
            # `EXTRACT(YEAR FROM (CAST(x AS DATE)))` is inside a call, not a FROM list
            pos = not sub and table_pos(k, bracket=True)
            calls.append(not sub and k > 0 and _IDENT.fullmatch(toks[k - 1]) is not None
                         and prev not in _NOT_CALLS)
            in_from.append(pos and not calls[-1])
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
        if _IDENT.fullmatch(t) is None or up in _NOT_CALLS or tok(k + 1) != "(":
            continue
        if table_pos(k):
            found.append(t)
    return found
