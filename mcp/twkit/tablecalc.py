"""Tableau table calculations -> two-level SQL with window functions."""
from __future__ import annotations

import re

_AGG = re.compile(r"(?i)\b(SUM|AVG|MIN|MAX|COUNT|MEDIAN|uniqExact|PERCENTILE_CONT)\s*\(")
TABLE_FUNCS = re.compile(
    r"(?i)\b(WINDOW_(?:SUM|AVG|MIN|MAX|COUNT|MEDIAN|STDEV|VAR)|RUNNING_(?:SUM|AVG|MIN|MAX|COUNT)"
    r"|LOOKUP|INDEX|SIZE|FIRST|LAST|RANK(?:_DENSE|_UNIQUE|_MODIFIED|_PERCENTILE)?|TOTAL)\s*\(")


def _close(s: str, i: int) -> int:
    """Index after the paren closing the one at s[i]; quoted strings are skipped."""
    depth, q = 0, ""
    for j in range(i, len(s)):
        ch = s[j]
        if q:
            if ch == q:
                q = ""
            continue
        if ch in "'\"":
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    return len(s)


def _args(s: str) -> list:
    """Top-level call arguments: 'f(a, g(b, c), d)' -> ['a', 'g(b, c)', 'd']."""
    i = s.index("(")
    body = s[i + 1:_close(s, i) - 1]
    out, depth, q, cur = [], 0, "", []
    for ch in body:
        if q:
            cur.append(ch)
            if ch == q:
                q = ""
            continue
        if ch in "'\"":
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def has_table_calc(expr: str) -> bool:
    return bool(TABLE_FUNCS.search(_strip_subqueries(expr)))


_SUBQ = re.compile(r"\(\s*SELECT\b", re.I)


def _strip_subqueries(expr: str) -> str:
    """Same-length mask hiding LOD subqueries, quoted strings and identifiers."""
    out, i = [], 0
    while i < len(expr):
        ch = expr[i]
        if ch in "'\"":
            j = expr.find(ch, i + 1)
            j = len(expr) if j < 0 else j + 1
            out.append(ch + "_" * (j - i - 2) + ch if j - i >= 2 else ch)
            i = j
            continue
        if _SUBQ.match(expr, i):
            j = _close(expr, i)
            out.append(" " * (j - i))
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def split_aggregates(expr: str, aggs: list) -> str:
    """Outer aggregates -> `_aN` references; aggregates are appended to `aggs`."""
    mask = _strip_subqueries(expr)
    out, i = [], 0
    while i < len(expr):
        m = _AGG.match(mask, i) if (i == 0 or not (mask[i - 1].isalnum() or mask[i - 1] == "_")) else None
        if m:
            j = _close(expr, m.end() - 1)
            sql = expr[i:j]
            if sql not in aggs:
                aggs.append(sql)
            out.append(f"_a{aggs.index(sql)}")
            i = j
            continue
        out.append(expr[i])
        i += 1
    return "".join(out)


def _over(part: list, order: list, frame: str = "") -> str:
    p = f"PARTITION BY {', '.join(part)}" if part else ""
    o = f"ORDER BY {', '.join(order)}" if order else ""
    return f"OVER ({' '.join(x for x in (p, o, frame) if x)})"


_WIN = {"SUM": "SUM", "AVG": "AVG", "MIN": "MIN", "MAX": "MAX", "COUNT": "COUNT",
        "MEDIAN": "MEDIAN", "STDEV": "STDDEV_SAMP", "VAR": "VAR_SAMP"}


def compile_measure(expr: str, part: list, order: list, aggs: list, wcols: list,
                    tagged: dict | None = None) -> str:
    """Tableau functions (after `split_aggregates`) -> window columns `_wN` by layer; `wcols` collects (name,..."""
    layer_of = {w[0]: w[2] for w in wcols}
    while True:
        m = _innermost(expr)
        if m is None:
            return expr
        st, en, name = m
        call = expr[st:en]
        a = _args(call)
        p, o = part, order
        if a and _TAG.fullmatch(a[0]):
            p, o = (tagged or {}).get(a.pop(0), (part, order))
        lay = 1 + max([layer_of.get(r, 0) for r in re.findall(r"_w\d+", call)] or [0])
        sql = _one(name, a, p, o, aggs)
        nm = f"_w{len(wcols)}"
        wcols.append((nm, sql, lay))
        layer_of[nm] = lay
        expr = expr[:st] + nm + expr[en:]


_TAG = re.compile(r"__tc\d+__")


def tag_calls(formula: str, tag: str) -> str:
    """Tag table-function calls with a direction marker: `RANK(x)` -> `RANK(__tc1__, x)`."""
    mask = _strip_subqueries(re.sub(r"\[[^\]]*\]", lambda m: "_" * len(m.group(0)), formula))
    out, last = [], 0
    for m in TABLE_FUNCS.finditer(mask):
        rest = formula[m.end():].lstrip()
        if rest.startswith("__tc"):
            continue
        out.append(formula[last:m.end()] + tag + ("" if rest.startswith(")") else ", "))
        last = m.end()
    out.append(formula[last:])
    return "".join(out)


def _innermost(expr: str):
    """First table-function call with no other such calls in its arguments."""
    mask = _strip_subqueries(expr)
    for m in TABLE_FUNCS.finditer(mask):
        en = _close(expr, m.end() - 1)
        if not TABLE_FUNCS.search(mask[m.end():en - 1]):
            return m.start(), en, m.group(1).upper()
    return None


def build_query(inner_sql: str, dims: list, measures: list, wcols: list,
                where: list | None = None) -> str:
    """Build the levels: inner aggregate, window layers, final measure SELECT."""
    q, depth = inner_sql, max([w[2] for w in wcols] or [0])
    for lay in range(1, depth + 1):
        cols = [f"{sql} AS {nm}" for nm, sql, l in wcols if l == lay]
        q = f"SELECT _t{lay - 1}.*, {', '.join(cols)} FROM ({q}) AS _t{lay - 1}"
    w = (" WHERE " + " AND ".join(f"({c})" for c in where)) if where else ""
    return f"SELECT {', '.join(dims + measures)} FROM ({q}) AS _tc{w}"


def _bound(x: str, side: str) -> str:
    x = (x or "").strip()
    if re.fullmatch(r"(?i)-?\s*FIRST\s*\(\s*\)", x) or re.fullmatch(r"(?i)FIRST\(\)", x):
        return "UNBOUNDED PRECEDING"
    if re.fullmatch(r"(?i)LAST\s*\(\s*\)", x):
        return "UNBOUNDED FOLLOWING"
    n = int(x) if re.fullmatch(r"-?\d+", x) else 0
    return "CURRENT ROW" if n == 0 else (f"{-n} PRECEDING" if n < 0 else f"{n} FOLLOWING")


def _one(name: str, a: list, part: list, order: list, aggs: list) -> str:
    if name.startswith("WINDOW_"):
        fn = _WIN.get(name[7:], "SUM")
        fr = ""
        if len(a) >= 3:
            fr = f"ROWS BETWEEN {_bound(a[1], 'lo')} AND {_bound(a[2], 'hi')}"
            return f"{fn}({a[0]}) {_over(part, order, fr)}"
        return f"{fn}({a[0]}) {_over(part, [])}"
    if name.startswith("RUNNING_"):
        fn = _WIN.get(name[8:], "SUM")
        return f"{fn}({a[0]}) {_over(part, order, 'ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW')}"
    if name == "LOOKUP":
        k = int(a[1]) if len(a) > 1 and re.fullmatch(r"-?\d+", a[1].strip()) else 0
        if k == 0:
            return f"({a[0]})"
        fn = "LAG" if k < 0 else "LEAD"
        return f"{fn}({a[0]}, {abs(k)}) {_over(part, order)}"
    if name == "INDEX":
        return f"ROW_NUMBER() {_over(part, order)}"
    if name == "SIZE":
        return f"COUNT(*) {_over(part, [])}"
    if name == "FIRST":
        return f"(1 - ROW_NUMBER() {_over(part, order)})"
    if name == "LAST":
        return f"(COUNT(*) {_over(part, [])} - ROW_NUMBER() {_over(part, order)})"
    if name.startswith("RANK"):
        desc = not (len(a) > 1 and "asc" in a[1].lower())
        o = [f"{a[0]} {'DESC' if desc else 'ASC'} NULLS LAST"]
        fn = {"RANK": "RANK()", "RANK_DENSE": "DENSE_RANK()", "RANK_UNIQUE": "ROW_NUMBER()",
              "RANK_PERCENTILE": "PERCENT_RANK()"}.get(name)
        if name == "RANK_MODIFIED":
            return (f"(RANK() {_over(part, o)} + COUNT(*) OVER (PARTITION BY "
                    f"{', '.join(part + [a[0]])}) - 1)")
        if name == "RANK_PERCENTILE":
            return f"(1 - {fn} {_over(part, o)})" if desc else f"{fn} {_over(part, o)}"
        return f"{fn} {_over(part, o)}"
    if name == "TOTAL":
        return _total(a[0], part, aggs)
    return f"({a[0] if a else 'NULL'})"


def _total(arg: str, part: list, aggs: list) -> str:
    """TOTAL(aggregate): re-aggregation over the partition source rows; AVG is sum/count."""
    m = re.fullmatch(r"_a(\d+)", arg.strip())
    if not m:
        return f"SUM({arg}) {_over(part, [])}"
    src = aggs[int(m.group(1))]
    head = re.match(r"(?i)\s*(SUM|COUNT|MIN|MAX|AVG)\s*\(", src)
    fn = head.group(1).upper() if head else "SUM"
    if fn in ("SUM", "COUNT"):
        return f"SUM({arg}) {_over(part, [])}"
    if fn in ("MIN", "MAX"):
        return f"{fn}({arg}) {_over(part, [])}"
    inner = src[head.end():_close(src, head.end() - 1) - 1]
    s_, c_ = f"SUM({inner})", f"COUNT({inner})"
    for x in (s_, c_):
        if x not in aggs:
            aggs.append(x)
    return (f"(SUM(_a{aggs.index(s_)}) {_over(part, [])} / "
            f"NULLIF(SUM(_a{aggs.index(c_)}) {_over(part, [])}, 0))")
