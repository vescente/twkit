"""Dry run: translate sheets to SQL and execute them BEFORE handing the workbook over."""
from __future__ import annotations


import re
from dataclasses import dataclass, field

from twkit import chsafe as _chsafe
from twkit import tablecalc as _tc

UNSUPPORTED = (
    (re.compile(r"\{\s*(FIXED|INCLUDE|EXCLUDE)", re.I), "LOD expression"),
    (re.compile(r"\b(WINDOW_\w+|RUNNING_\w+|LOOKUP|INDEX|RANK\w*|TOTAL|FIRST|LAST|"
                r"PREVIOUS_VALUE)\s*\(", re.I), "table calculation"),
    (re.compile(r"\bMAKEPOINT|MAKELINE\b", re.I), "geographic function"),
)

UNTRANSLATED_FUNCS = (
    (re.compile(r"\bDATENAME\s*\(", re.I), "DATENAME (period name as a word)"),
    (re.compile(r"\bDATEPARSE\s*\(", re.I), "DATEPARSE (date parsing by mask)"),
    (re.compile(r"\b(REGEXP_\w+|FINDNTH)\s*\(", re.I), "Tableau string function"),
    (re.compile(r"\b(MODEL_QUANTILE|MODEL_PERCENTILE|SCRIPT_\w+)\s*\(", re.I),
     "external analytics"),
    (re.compile(r"\bPREVIOUS_VALUE\s*\(", re.I), "PREVIOUS_VALUE (recursive table calculation)"),
)


@dataclass
class SheetResult:
    sheet: str
    status: str
    rows: int = 0
    sql: str = ""
    sample: list = field(default_factory=list)
    note: str = ""
    base_sql: str = ""
    where_sql: str = ""
    synthetic_measure: bool = False
    relaxed: str = ""
    dim_exprs: list = field(default_factory=list)
    measure_exprs: list = field(default_factory=list)
    dim_labels: list = field(default_factory=list)
    measure_labels: list = field(default_factory=list)
    dim_refs: list = field(default_factory=list)
    measure_refs: list = field(default_factory=list)

    def as_dict(self) -> dict:
        out = {"sheet": self.sheet, "status": self.status, "rows": self.rows,
               "note": self.note, "sample": self.sample[:3], "sql": self.sql}
        if self.relaxed:
            out["relaxed"] = self.relaxed
        return out


DIALECTS = {
    "hyper": {
        "trunc": {"day": "CAST({} AS DATE)",
                  "week": "DATE_TRUNC('week', {})",
                  "month": "DATE_TRUNC('month', {})",
                  "quarter": "DATE_TRUNC('quarter', {})",
                  "year": "DATE_TRUNC('year', {})"},
        "countd": "COUNT(DISTINCT ", "ifnull": "COALESCE(", "nullif": "NULLIF(",
        "quantile": "PERCENTILE_CONT({q}) WITHIN GROUP (ORDER BY {x})",
        "today": "CURRENT_DATE", "now": "CURRENT_TIMESTAMP",
        "tostring": "CAST(", "tostring_tail": " AS TEXT)",
        "toint": "CAST({} AS INTEGER)", "tofloat": "CAST({} AS DOUBLE PRECISION)",
        "date": "DATE '{}'",
        "adddays": "({d} + {n} * INTERVAL '1 day')",
        "datediff": "(CAST({b} AS DATE) - CAST({a} AS DATE))",
        "quote": '"',
    },
    "clickhouse": {
        "trunc": {"day": "toDate({})", "week": "toMonday({})",
                  "month": "toStartOfMonth({})", "quarter": "toStartOfQuarter({})",
                  "year": "toStartOfYear({})"},
        "quantile": "quantile({q})({x})",
        "today": "today()", "now": "now()",
        "countd": "uniqExact(", "ifnull": "ifNull(", "nullif": "nullIf(",
        "tostring": "toString(", "tostring_tail": ")",
        "toint": "toInt64({})", "tofloat": "toFloat64({})",
        "date": "toDate('{}')",
        "adddays": "addDays({d}, {n})",
        "datediff": "dateDiff('day', {a}, {b})",
        "quote": "`",
    },
}


def _split_args(text: str, start: int):
    """Call arguments from the opening paren, nesting-aware."""
    if start >= len(text) or text[start] != "(":
        return None, -1
    depth, arg, args, i, quote = 0, [], [], start, ""
    while i < len(text):
        ch = text[i]
        if quote:
            arg.append(ch)
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            arg.append(ch)
        elif ch == "(":
            depth += 1
            if depth > 1:
                arg.append(ch)
        elif ch == ")":
            depth -= 1
            if depth == 0:
                args.append("".join(arg).strip())
                return args, i + 1
            arg.append(ch)
        elif ch == "," and depth == 1:
            args.append("".join(arg).strip())
            arg = []
        else:
            arg.append(ch)
        i += 1
    return None, -1


def _fill_single_arg_coalesce(text: str, head: str) -> str:
    """`COALESCE(x)` -> `COALESCE(x, 0)`, paren-aware."""
    low_head = head.lower()
    out, i = [], 0
    while True:
        j = text.lower().find(low_head, i)
        if j < 0:
            out.append(text[i:])
            return "".join(out)
        open_paren = j + len(head) - 1
        args, end = _split_args(text, open_paren)
        if args is None:
            out.append(text[i:j + len(head)])
            i = j + len(head)
            continue
        inner = ", ".join(args)
        if len(args) == 1:
            inner += ", 0"
        out.append(text[i:j])
        out.append(head + inner + ")")
        i = end


_WORD = re.compile(r"[A-Za-z0-9_]")


def _rewrite_call(text: str, name: str, build, min_args: int = 1) -> str:
    """Rewrite every `name(...)` call through `build(args)`, innermost first."""
    low = text.lower()
    target = name.lower()
    idx = low.rfind(target)
    while idx >= 0:
        after = idx + len(target)
        before_ok = idx == 0 or not _WORD.match(text[idx - 1])
        j = after
        while j < len(text) and text[j] == " ":
            j += 1
        if before_ok:
            args, end = _split_args(text, j)
            if args and len(args) >= min_args:
                text = text[:idx] + build(args) + text[end:]
                low = text.lower()
        idx = low.rfind(target, 0, idx)
    return text


def _rewrite_date_fn(text: str, name: str, build) -> str:
    """Compatibility: three-argument date functions."""
    return _rewrite_call(text, name, build, min_args=3)


def _match_paren(text: str, start: int) -> int:
    """Index just past the paren matching the one at `start`."""
    depth, i, quote = 0, start, ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def guard_division(sql: str, float_div: bool = False) -> str:
    """`a / b` -> `a / NULLIF(b, 0)`: Tableau yields NULL on division by zero, SQL raises."""
    out, i = [], 0
    quote = ""
    while i < len(sql):
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch != "/":
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        j = i + 1
        while j < len(sql) and sql[j] in " \t\r\n":
            j += 1
        out.append(sql[i + 1:j])
        if j >= len(sql):
            i = j
            continue
        if sql[j] == "(":
            end = _match_paren(sql, j)
        else:
            k = j
            while k < len(sql) and (sql[k].isalnum() or sql[k] in "_.\""):
                k += 1
            end = _match_paren(sql, k) if k < len(sql) and sql[k] == "(" else k
        if end <= j:
            i = j
            continue
        operand = sql[j:end]
        if operand.lstrip("(").upper().startswith("NULLIF"):
            out.append(operand)
        elif float_div:
            out.append(f"NULLIF(CAST({operand} AS DOUBLE PRECISION), 0)")
        else:
            out.append(f"NULLIF({operand}, 0)")
        i = end
    return "".join(out)


_TYPED_LITERAL = re.compile(r"(?i)\b(?:DATE|TIMESTAMP|TIME|INTERVAL)\s+'")
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")


def _branch_values(case_sql: str) -> list:
    """What a `CASE` returns: the parts after each THEN and ELSE (conditions are ignored)."""
    out, i, depth, quote = [], 0, 0, ""
    low = case_sql.lower()
    while i < len(case_sql):
        ch = case_sql[i]
        if quote:
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth <= 1:
            for word in ("then", "else"):
                if low.startswith(word, i) and (i == 0 or not _WORD.match(case_sql[i - 1])):
                    j = i + len(word)
                    while j < len(case_sql) and case_sql[j] == " ":
                        j += 1
                    out.append(case_sql[j:j + 40])
                    i = j
                    break
        i += 1
    return out


_NUMERIC_HEAD = re.compile(
    r"(?i)^\(*\s*(SUM|COUNT|AVG|MIN|MAX|ROUND|ABS|COALESCE|NULLIF|CAST|"
    r"DATE_TRUNC|DATE_PART|EXTRACT|DATE|toStartOf\w+|dateDiff|addDays|"
    r"STRPOS|LENGTH|position|positionUTF8|lengthUTF8|MAKE_DATE|"
    r"LOOKUP|WINDOW_\w+|RUNNING_\w+|RANK\w*|INDEX|SIZE|TOTAL|FIRST|LAST)\s*\(")
_SUBQUERY = re.compile(r"(?is)^\(*\s*SELECT\s+(.*)\s+FROM\s")


def _looks_textual(operand: str, text_idents: frozenset = frozenset()) -> bool:
    """True when the operand is text, not a number."""
    sub = _SUBQUERY.match(operand)
    if sub:
        return _looks_textual(sub.group(1).strip(), text_idents)
    if text_idents and operand.strip().strip("()").strip() in text_idents:
        return True
    up = operand.upper()
    if "AS TEXT)" in up or "TOSTRING(" in up:
        return True
    if _NUMERIC_HEAD.match(operand):
        return False
    if re.match(r"(?i)^\(*\s*CASE\b", operand):
        return any(v.lstrip("(").startswith("'") for v in _branch_values(operand))
    body = _TYPED_LITERAL.sub("", operand)
    return bool(_STRING_LITERAL.search(body))


def _operand_left(sql: str, end: int) -> str:
    """Operand to the left of position `end`."""
    i = end
    while i > 0 and sql[i - 1] == " ":
        i -= 1
    if i > 0 and sql[i - 1] == "'":
        j = i - 2
        while j >= 0 and sql[j] != "'":
            j -= 1
        j = max(j, 0)
        k = j
        while k > 0 and sql[k - 1] == " ":
            k -= 1
        w = k
        while w > 0 and sql[w - 1].isalpha():
            w -= 1
        if sql[w:k].upper() in ("DATE", "TIMESTAMP", "TIME", "INTERVAL"):
            j = w
        return sql[j:i]
    if i > 0 and sql[i - 1] == '"':
        j = i - 1
        while True:
            j = sql.rfind('"', 0, j)
            if j <= 0 or sql[j - 1] != ".":
                break
            j -= 1
            if sql[j - 1:j] != '"':
                break
            j -= 1
        return sql[max(j, 0):i]
    if i > 0 and sql[i - 1] == ")":
        depth = 0
        j = i - 1
        while j >= 0:
            if sql[j] == ")":
                depth += 1
            elif sql[j] == "(":
                depth -= 1
                if depth == 0:
                    break
            j -= 1
        while j > 0 and (sql[j - 1].isalnum() or sql[j - 1] in "_\""):
            j -= 1
        return sql[max(j, 0):i]
    j = i
    while j > 0 and (sql[j - 1].isalnum() or sql[j - 1] in "_.\"'"):
        j -= 1
    return sql[j:i]


def _operand_right(sql: str, start: int) -> str:
    """Operand to the right of position `start`."""
    j = start
    while j < len(sql) and sql[j] == " ":
        j += 1
    if j < len(sql) and sql[j] == "(":
        end = _match_paren(sql, j)
        return sql[j:end] if end > j else sql[j:]
    k = j
    while k < len(sql) and sql[k] == '"':
        e = sql.find('"', k + 1)
        k = len(sql) if e < 0 else e + 1
        if k < len(sql) and sql[k] == "." and sql[k + 1:k + 2] == '"':
            k += 1
            continue
        return sql[j:k]
    while k < len(sql) and (sql[k].isalnum() or sql[k] in "_.\"'"):
        k += 1
    if k < len(sql) and sql[k] == "(":
        end = _match_paren(sql, k)
        return sql[j:end] if end > k else sql[j:]
    return sql[j:k]


_DATE_HEAD = re.compile(r"(?i)^(DATE_TRUNC\s*\(|DATE\s*\(|CAST\(.*AS (DATE|TIMESTAMP)\)|"
                        r"CURRENT_DATE\b|TIMESTAMP '|DATE ')")


def _strip_outer_parens(s: str) -> str:
    """Strip paired outer parentheses only."""
    s = s.strip()
    while s.startswith("(") and _match_paren(s, 0) == len(s):
        s = s[1:-1].strip()
    return s


def _top_level_terms(s: str) -> list:
    """Split `a - b + c` into signed top-level terms, outside quotes."""
    out, depth, quote, start, sign = [], 0, "", 0, "+"
    for i, ch in enumerate(s):
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch in "+-" and depth == 0:
            head = s[start:i].strip()
            if head and not head.endswith(("*", "/", "+", "-", "(", "=", "<", ">")) and \
                    not re.search(r"(?i)\b(INTERVAL|AND|OR|NOT)$", head):
                out.append((sign, head))
                sign, start = ch, i + 1
    out.append((sign, s[start:].strip()))
    return out


def _is_date_operand(op: str, date_idents: set) -> bool:
    whole = _strip_outer_parens(op)
    if not re.search(r"(?i)\bCASE\b", whole):
        terms = _top_level_terms(whole)
        if len(terms) > 1:
            dates = sum(1 if sg == "+" else -1 for sg, t in terms
                        if _strip_outer_parens(t) in date_idents
                        or _DATE_HEAD.match(_strip_outer_parens(t)))
            return dates == 1
    o = op.strip().strip("()").strip()
    return o in date_idents or bool(_DATE_HEAD.match(o))


def _right_operand(sql: str, i: int) -> tuple[str, int]:
    """Operand right of position i."""
    j = i
    while j < len(sql) and sql[j] == " ":
        j += 1
    if j >= len(sql):
        return "", j
    if sql[j] in "\"'":
        k = sql.find(sql[j], j + 1)
        return (sql[j:k + 1], k + 1) if k > 0 else ("", j)
    if sql[j] == "(":
        end = _match_paren(sql, j)
        return (sql[j:end], end) if end > j else ("", j)
    k = j
    while k < len(sql) and (sql[k].isalnum() or sql[k] in "_."):
        k += 1
    if k < len(sql) and sql[k] == "(":
        end = _match_paren(sql, k)
        return (sql[j:end], end) if end > k else ("", j)
    return sql[j:k], k


def date_plus(sql: str, date_idents: set) -> str:
    """`date +/- n` -> `date +/- (n) * INTERVAL '1 day'` (Tableau shifts by days)."""
    out, i, quote = [], 0, ""
    while i < len(sql):
        ch = sql[i]
        if quote:
            out.append(ch)
            quote = "" if ch == quote else quote
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch in "+-":
            tail = "".join(out).rstrip()
            left = next((d for d in date_idents if tail.endswith(d)), "") or \
                _operand_left(tail, len(tail))
            right, end = _right_operand(sql, i + 1)
            if (left and right and _is_date_operand(left, date_idents)
                    and not _is_date_operand(right, date_idents)
                    and "INTERVAL" not in right.upper()
                    and not sql[end:].lstrip().startswith(("*", "/"))):
                out.append(f"{ch} ({right}) * INTERVAL '1 day'")
                i = end
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def concat_plus(sql: str, text_idents: frozenset = frozenset()) -> str:
    """`+` between text operands -> `||`."""
    out, i, quote = [], 0, ""
    while i < len(sql):
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch != "+":
            out.append(ch)
            i += 1
            continue
        done = "".join(out)
        if _looks_textual(_operand_left(done, len(done)), text_idents) or \
                _looks_textual(_operand_right(sql, i + 1), text_idents):
            out.append("||")
        else:
            out.append("+")
        i += 1
    return "".join(out)


class Translator:
    """Tableau formula -> SQL of the chosen dialect; only the declared subset."""

    def __init__(self, calcs: dict[str, str], captions: dict[str, str],
                 params: dict[str, str], columns: set[str], dialect: str = "clickhouse",
                 aliases: dict[str, str] | None = None):
        self.calcs = calcs
        self.captions = captions
        self.params = params
        self.columns = columns
        self.aliases = aliases or {}
        self.d = DIALECTS[dialect]
        self.dialect = dialect
        self.lod_table: str | None = None
        self.lod_tables: dict | None = None
        self.date_cols: set = set()
        self.allow_tc = False
        self.tc_tags: dict = {}
        self.sets: set = set()
        self.text_cols: set = set()
        self._lod_n = 0
        self.last_lod: dict = {}

    def expand(self, formula: str, depth: int = 0) -> str:
        """Expand references to other calculations and parameters, recursively."""
        if depth > 12:
            return formula
        out = formula
        def _param(m):
            val = self.params.get(m.group(1))
            if val is None:
                return m.group(0)
            return val
        out = re.sub(r"\[Parameters\]\.\[([^\]]+)\]", _param, out)
        if self.sets:
            out = re.sub(r"\[[^\]]+\]\s+IN\s+\[([^\]]+)\]",
                         lambda m: f"[{m.group(1)}]" if m.group(1) in self.sets else m.group(0),
                         out, flags=re.I)
        def _calc(m):
            name = m.group(1)
            if name in self.columns:
                return m.group(0)
            if name not in self.calcs and self.captions.get(name) in self.calcs:
                name = self.captions[name]
            if name in self.calcs:
                body = self.expand(self.strip_comments(self.calcs[name]), depth + 1)
                if name in self.tc_tags:
                    body = _tc.tag_calls(body, self.tc_tags[name])
                return "(" + body + "\n)"
            return m.group(0)
        out = re.sub(r"\[([^\]]+)\]", _calc, out)
        return out

    _PLAIN = {"hyper": re.compile(r"^[a-z_][a-z0-9_]*$"),
              "clickhouse": re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")}

    def quote_ident(self, name: str) -> str:
        """Quote an identifier unless it is simple."""
        al = self.aliases.get(name)
        if al and (al in self.columns or name not in self.columns):
            name = al
        if self._PLAIN[self.dialect].match(name):
            return name
        q = self.d["quote"]
        return q + name.replace(q, q + q) + q

    @staticmethod
    def strip_comments(formula: str) -> str:
        """Remove Tableau comments (`// ...` and `/* ..."""
        s = re.sub(r"/\*.*?\*/", " ", formula, flags=re.S)
        return re.sub(r"//[^\n]*", " ", s)

    @staticmethod
    def fold_case(sql: str, depth: int = 0) -> str:
        """Collapse `CASE 'literal' WHEN 'a' THEN x ..."""
        if depth > 30:
            return sql
        m = re.search(r"\bCASE\s+('(?:[^']|'')*')", sql, re.I)
        if not m:
            return sql
        selector = m.group(1)
        i, n = m.end(), len(sql)
        case_depth = 0
        branches: list[tuple[str, int, int]] = []
        cur_val, cur_start, end_idx = None, None, None
        while i < n:
            mc = re.match(r"\bCASE\b", sql[i:], re.I)
            if mc:
                case_depth += 1
                i += mc.end()
                continue
            mn = re.match(r"\bEND\b", sql[i:], re.I)
            if mn:
                if case_depth:
                    case_depth -= 1
                    i += mn.end()
                    continue
                if cur_val is not None:
                    branches.append((cur_val, cur_start, i))
                end_idx = i + mn.end()
                break
            if case_depth == 0:
                mw = re.match(r"\bWHEN\b\s*('(?:[^']|'')*')\s*\bTHEN\b", sql[i:], re.I)
                if mw:
                    if cur_val is not None:
                        branches.append((cur_val, cur_start, i))
                    cur_val, cur_start = mw.group(1), i + mw.end()
                    i += mw.end()
                    continue
                me = re.match(r"\bELSE\b", sql[i:], re.I)
                if me:
                    if cur_val is not None:
                        branches.append((cur_val, cur_start, i))
                    cur_val, cur_start = "", i + me.end()
                    i += me.end()
                    continue
            i += 1
        if end_idx is None:
            return sql
        chosen = None
        for val, a, b in branches:
            if val == selector:
                chosen = sql[a:b].strip()
                break
        if chosen is None:
            for val, a, b in branches:
                if val == "":
                    chosen = sql[a:b].strip()
        if chosen is None:
            chosen = "NULL"
        folded = sql[:m.start()] + "(" + chosen + ")" + sql[end_idx:]
        return Translator.fold_case(folded, depth + 1)

    def to_sql(self, formula: str) -> tuple[str, str]:
        """Returns (sql, skip_reason); an empty reason means the translation succeeded."""
        expanded = self.strip_comments(self.expand(self.strip_comments(formula)))
        expanded = re.sub(r"\[__tableau_internal_object_id__\]\.\[[^\]]+\]", "1", expanded)
        expanded, lods, why = self._extract_lods(expanded)
        if why:
            return "", why
        for rx, why in UNSUPPORTED:
            if rx.search(expanded) and not (self.allow_tc and why == "table calculation"):
                return "", why
        s = expanded

        d = self.d
        s = _dq_to_sq(s)
        s = re.sub(r"('(?:[^']|'')*')|==", lambda m: m.group(1) or "=", s)
        s = re.sub(r"#(\d{4}-\d{2}-\d{2})[^#]*#",
                   lambda m: d["date"].format(m.group(1)), s)
        s = re.sub(r"#(\d{1,2})/(\d{1,2})/(\d{4})[^#]*#",
                   lambda m: d["date"].format(_dmy(*m.groups())), s)
        s = re.sub(r"\bELSEIF\b", "WHEN_ELSE", s, flags=re.I)
        s = re.sub(r"\bIF\b", "CASE WHEN", s, flags=re.I)
        s = re.sub(r"\bWHEN_ELSE\b", "WHEN", s)
        def _trunc(a):
            unit = a[0].strip().strip("'").lower()
            return d["trunc"].get(unit, d["trunc"]["day"]).format(a[1])
        s = _rewrite_call(s, "DATETRUNC", _trunc, min_args=2)
        s = _rewrite_date_fn(s, "DATEADD",
                             lambda a: date_add_sql(self.dialect, _unit(a[0]), a[1], a[2]))
        s = _rewrite_date_fn(s, "DATEDIFF",
                             lambda a: date_diff_sql(self.dialect, _unit(a[0]), a[1], a[2]))
        hy = self.dialect == "hyper"
        s = _rewrite_call(s, "MID", lambda a: (
            (f"SUBSTRING({a[0]} FROM {a[1]} FOR {a[2]})" if len(a) > 2
             else f"SUBSTRING({a[0]} FROM {a[1]})") if hy
            else f"substringUTF8({a[0]}, {a[1]}{', ' + a[2] if len(a) > 2 else ''})"), min_args=2)
        s = _rewrite_call(s, "FIND", lambda a: (
            f"STRPOS({a[0]}, {a[1]})" if hy else f"positionUTF8({a[0]}, {a[1]})"), min_args=2)
        s = _rewrite_call(s, "STARTSWITH", lambda a: (
            f"(STRPOS({a[0]}, {a[1]}) = 1)" if hy else f"startsWith({a[0]}, {a[1]})"), min_args=2)
        s = _rewrite_call(s, "ENDSWITH", lambda a: (
            f"(RIGHT({a[0]}, LENGTH({a[1]})) = {a[1]})" if hy else f"endsWith({a[0]}, {a[1]})"),
            min_args=2)
        s = _rewrite_call(s, "LEN", lambda a: (
            f"LENGTH({a[0]})" if hy else f"lengthUTF8({a[0]})"))
        s = _rewrite_call(s, "PROPER", lambda a: (
            f"INITCAP({a[0]})" if hy else f"initcap({a[0]})"))
        for nm_, to_ in (("MIN", "LEAST"), ("MAX", "GREATEST")):
            s = _rewrite_call(s, nm_, lambda a, nm_=nm_, to_=to_: (
                f"{to_}({a[0]}, {a[1]})" if len(a) == 2 else f"{nm_}({', '.join(a)})"), min_args=2)
        s = _rewrite_call(s, "MAKEDATE", lambda a: (
            f"MAKE_DATE(CAST({a[0]} AS INTEGER), CAST({a[1]} AS INTEGER), CAST({a[2]} AS INTEGER))"
            if hy else f"makeDate({a[0]}, {a[1]}, {a[2]})"), min_args=3)
        s = _rewrite_call(s, "SPLIT", lambda a: (
            f"SPLIT_PART({a[0]}, {a[1]}, {a[2]})" if self.dialect == "hyper"
            else f"arrayElement(splitByString({a[1]}, {a[0]}), {a[2]})"), min_args=3)
        s = _rewrite_call(s, "DATEPART",
                          lambda a: date_part_sql(self.dialect, _unit(a[0]), a[1]), min_args=2)
        s = re.sub(r"\bTODAY\s*\(\s*\)", d["today"], s, flags=re.I)
        s = re.sub(r"\bNOW\s*\(\s*\)", d["now"], s, flags=re.I)
        s = _rewrite_call(s, "IIF", lambda a: (
            "CASE WHEN " + a[0] + " THEN " + a[1]
            + (" ELSE " + a[2] if len(a) > 2 else "") + " END"), min_args=2)
        s = _rewrite_call(s, "INT", lambda a: d["toint"].format(a[0]))
        s = _rewrite_call(s, "FLOAT", lambda a: d["tofloat"].format(a[0]))
        s = _rewrite_call(s, "ISNULL", lambda a: "(" + a[0] + " IS NULL)")
        s = _rewrite_call(s, "ATTR", lambda a: "MIN(" + a[0] + ")")
        def _str(a):
            t = d["tostring"] + a[0] + d["tostring_tail"]
            if self.dialect != "hyper":
                return t
            return f"(CASE WHEN STRPOS({t}, '.') > 0 THEN RTRIM(RTRIM({t}, '0'), '.') ELSE {t} END)"
        s = _rewrite_call(s, "STR", _str)
        for rx, to in ((r"\bCOUNTD\s*\(", d["countd"]),
                       (r"\bIFNULL\s*\(", d["ifnull"]),
                       (r"\bNULLIF\s*\(", d["nullif"]),
                       (r"\bZN\s*\(", d["ifnull"]),
                       (r"\bABS\s*\(", "abs(")):
            s = re.sub(rx, to, s, flags=re.I)
        s = _fill_single_arg_coalesce(s, d["ifnull"])
        s = re.sub(r"\bDATE\s*\(\s*([^()]+?)\s*\)",
                   lambda m: (f"CAST({m.group(1)} AS DATE)" if self.dialect == "hyper"
                              else f"toDate({m.group(1)})"), s, flags=re.I)
        s = re.sub(r"\[([^\]]+)\]", lambda m: self.quote_ident(m.group(1)), s)
        s = _concat_literals(s)
        if self.dialect == "hyper" and self.date_cols:
            s = date_plus(s, {self.quote_ident(c) for c in self.date_cols})
        s = self.fold_case(s)
        s = concat_plus(s, frozenset(self.quote_ident(c) for c in self.text_cols))
        s = guard_division(s, float_div=self.dialect == "hyper")
        for rx, why in UNTRANSLATED_FUNCS:
            if rx.search(s):
                return "", why
        self.last_lod = {"masked": s, **lods["info"]} if lods["subs"] else {}
        for key, sub in reversed(list(lods["subs"].items())):
            s = s.replace(key, sub)
            if self.last_lod.get("dim_sql"):
                self.last_lod["dim_sql"] = [d.replace(key, sub) for d in self.last_lod["dim_sql"]]
        return s, ""

    def param_only(self, formula: str, depth: int = 0) -> bool:
        """True when the formula depends only on parameters (directly or via other calcs), with no source fields."""
        if depth > 12:
            return False
        body = re.sub(r"\[Parameters\]\.\[[^\]]+\]", " __param__ ", self.strip_comments(formula))
        seen_param = "__param__" in body
        for ref in re.findall(r"\[([^\]]+)\]", body):
            if ref in self.calcs:
                if not self.param_only(self.calcs[ref], depth + 1):
                    return False
                seen_param = True
            elif ref in self.params:
                seen_param = True
            else:
                return False
        return seen_param

    def _qualify(self, sql: str, table: str) -> str:
        """Qualify source columns in a SQL expression as `table.column` (outer side of the LOD correlation)."""
        forms = {self.quote_ident(c) for c in self.columns}
        out, i = [], 0
        tok = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")+\"|[A-Za-z_]\w*")
        while i < len(sql):
            m = tok.match(sql, i)
            if not m:
                out.append(sql[i])
                i += 1
                continue
            t = m.group(0)
            before = "".join(out).rstrip()[-1:]
            after = sql[m.end():].lstrip()[:1]
            if t in forms and before != "." and after != "(" and not t.startswith("'"):
                t = f"{table}.{t}"
            out.append(t)
            i = m.end()
        return "".join(out)

    def _lod_table_for(self, fragment: str) -> str:
        """LOD table for a multi-table extract: the one whose columns are mentioned."""
        if not self.lod_tables or len(self.lod_tables) < 2:
            return self.lod_table
        best, hits = self.lod_table, -1
        for name, cols in self.lod_tables.items():
            h = sum(1 for c in cols if c in fragment)
            if h > hits:
                best, hits = name, h
        return best

    def _extract_lods(self, text: str):
        """`{ AGG }`, `{FIXED : AGG}`, `{FIXED d1, d2 : AGG}` -> `__lodN__` markers plus subqueries."""
        subs, dims_all, dim_of, tbl = {}, set(), {}, {}
        out = text
        while True:
            m = re.search(r"\{([^{}]*)\}", out)
            if not m:
                break
            body = m.group(1).strip()
            kw = re.match(r"(FIXED|INCLUDE|EXCLUDE)\b", body, re.I)
            if kw and kw.group(1).upper() != "FIXED":
                return text, {"subs": {}, "info": {}}, "LOD expression INCLUDE/EXCLUDE"
            dims_txt, agg_txt = "", body
            if kw:
                rest = body[kw.end():]
                if ":" not in rest:
                    return text, {"subs": {}, "info": {}}, "LOD expression"
                dims_txt, agg_txt = rest.split(":", 1)
            if not self.lod_table:
                return text, {"subs": {}, "info": {}}, "LOD expression"
            saved = self.last_lod
            inner_sql, why = self.to_sql(agg_txt)
            self.last_lod = saved
            if why:
                return text, {"subs": {}, "info": {}}, why
            self._lod_n += 1
            al = f"_lod{self._lod_n}"
            idents, exprs = [], []
            for part in _lod_dim_parts(dims_txt):
                refs = re.findall(r"\[[^\]]+\]", part)
                dims_all.update(r.strip("[]") for r in refs)
                if re.fullmatch(r"\[[^\]]+\]", part):
                    ident = self.quote_ident(part.strip("[]"))
                    if not re.fullmatch(r'"[^"]+"|\w+', ident):
                        return text, {"subs": {}, "info": {}}, "LOD over a calculated field"
                    idents.append(ident)
                    continue
                saved = self.last_lod
                dsql, why = self.to_sql(part)
                self.last_lod = saved
                if why:
                    return text, {"subs": {}, "info": {}}, why
                exprs.append(dsql.strip())
            table = self._lod_table_for(inner_sql + " " + " ".join(idents + exprs))
            conds = [f"{al}.{i} IS NOT DISTINCT FROM {table}.{i}" for i in idents]
            conds += [f"({e}) IS NOT DISTINCT FROM ({self._qualify(e, table)})" for e in exprs]
            where = (" WHERE " + " AND ".join(conds)) if conds else ""
            key = f"__lod{self._lod_n}__"
            subs[key] = f"(SELECT {inner_sql} FROM {table} AS {al}{where})"
            dim_of[key], tbl[key] = idents + exprs, table
            out = out[:m.start()] + key + out[m.end():]
        if not subs:
            return text, {"subs": {}, "info": {}}, ""
        pure = not re.search(r"\[[^\]]+\]", re.sub(r"__lod\d+__", "", out))
        top = [k for k in subs if k in out]
        dim_sql = []
        for k in top:
            dim_sql += [d for d in dim_of[k] if d not in dim_sql]
        info = {"pure": pure, "dims": dims_all, "dim_sql": dim_sql,
                "table": tbl[top[0]] if top else ""}
        return out, {"subs": subs, "info": info}, ""


KNOWN_DERIVATIONS = frozenset((
    "none", "usr", "sum", "attr", "avg", "yr", "tmn", "mn", "tdy", "ctd", "cnt",
    "tqr", "max", "pcto", "min", "clct", "my", "qr", "dy", "hr", "io", "md",
    "win", "wd", "rank", "cum", "thr", "tyr", "twk", "pcdf",
))


_TYPED_TAIL = re.compile(r"\b(?:DATE|TIMESTAMP|TIME|INTERVAL)\s*$", re.I)


def _lod_dim_parts(dims_txt: str) -> list:
    """Top-level comma-separated FIXED dimensions; `[...]` is an atom."""
    parts, cur, depth, i = [], [], 0, 0
    while i < len(dims_txt):
        ch = dims_txt[i]
        if ch == "[":
            j = dims_txt.find("]", i)
            j = len(dims_txt) if j < 0 else j + 1
            cur.append(dims_txt[i:j])
            i = j
            continue
        if ch in "'\"":
            j = dims_txt.find(ch, i + 1)
            j = len(dims_txt) if j < 0 else j + 1
            cur.append(dims_txt[i:j])
            i = j
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    parts.append("".join(cur).strip())
    out = []
    for p in parts:
        while re.fullmatch(r"\((.*)\)", p, re.S) and _match_paren(p, 0) == len(p):
            p = p[1:-1].strip()
        if p:
            out.append(p)
    return out


def _concat_literals(s: str) -> str:
    """`+` next to a string literal -> `||`, except typed literals (`DATE '...' + n` is date arithmetic)."""
    parts = re.split(r"('(?:[^']|'')*')", s)
    for i in range(0, len(parts), 2):
        seg = parts[i]
        if i > 0:
            typed = i >= 2 and _TYPED_TAIL.search(parts[i - 2])
            seg = re.sub(r"^\s*\+\s*", " + " if typed else " || ", seg)
        if i + 1 < len(parts):
            if not _TYPED_TAIL.search(seg):
                seg = re.sub(r"\s*\+\s*$", " || ", seg)
        parts[i] = seg
    return "".join(parts)


def _dmy(a: str, b: str, y: str) -> str:
    a_, b_ = int(a), int(b)
    day, mon = (a_, b_) if a_ > 12 else (b_, a_)
    return f"{y}-{mon:02d}-{day:02d}"


def _unit(arg: str) -> str:
    return arg.strip().strip("'\"").lower()


def date_add_sql(dialect: str, unit: str, n: str, d: str) -> str:
    """DATEADD(unit, n, d)."""
    if dialect == "clickhouse":
        if unit == "day":
            return f"addDays({d}, {n})"
        u = {"week": "week", "month": "month", "quarter": "quarter", "year": "year",
             "hour": "hour", "minute": "minute", "second": "second"}.get(unit, "day")
        return f"dateAdd({u}, {n}, {d})"
    step = {"week": "7 day", "quarter": "3 month"}.get(
        unit, f"1 {unit}" if unit in ("day", "month", "year", "hour", "minute", "second")
        else "1 day")
    return f"({d} + {n} * INTERVAL '{step}')"


def date_diff_sql(dialect: str, unit: str, a: str, b: str) -> str:
    """DATEDIFF(unit, a, b): number of period boundaries between the dates, as in Tableau."""
    if dialect == "clickhouse":
        return f"dateDiff('{unit if unit in ('week', 'month', 'quarter', 'year', 'hour', 'minute', 'second') else 'day'}', {a}, {b})"
    y = f"(EXTRACT(YEAR FROM {b}) - EXTRACT(YEAR FROM {a}))"
    if unit == "year":
        return y
    if unit == "quarter":
        return f"({y} * 4 + EXTRACT(QUARTER FROM {b}) - EXTRACT(QUARTER FROM {a}))"
    if unit == "month":
        return f"({y} * 12 + EXTRACT(MONTH FROM {b}) - EXTRACT(MONTH FROM {a}))"
    if unit == "week":
        wk = "CAST(DATE_TRUNC('week', {} + INTERVAL '1 day') AS DATE)"
        return f"(({wk.format(b)} - {wk.format(a)}) / 7)"
    if unit in ("hour", "minute", "second"):
        sec = {"hour": 3600, "minute": 60, "second": 1}[unit]
        return (f"FLOOR(EXTRACT(EPOCH FROM DATE_TRUNC('{unit}', {b}) - "
                f"DATE_TRUNC('{unit}', {a})) / {sec})")
    return f"(CAST({b} AS DATE) - CAST({a} AS DATE))"


def date_part_sql(dialect: str, unit: str, x: str) -> str:
    """DATEPART(unit, x) as an integer."""
    if dialect == "clickhouse":
        fn = {"year": "toYear", "quarter": "toQuarter", "month": "toMonth",
              "day": "toDayOfMonth", "hour": "toHour", "minute": "toMinute",
              "week": "toWeek", "dayofyear": "toDayOfYear"}.get(unit)
        if unit == "weekday":
            return f"(toDayOfWeek({x}) % 7 + 1)"
        return f"{fn or 'toDayOfMonth'}({x})"
    if unit == "weekday":
        return f"(EXTRACT(DOW FROM {x}) + 1)"
    field = {"dayofyear": "DOY"}.get(unit, unit.upper() if unit in (
        "year", "quarter", "month", "day", "hour", "minute", "second", "week") else "DAY")
    return f"CAST(EXTRACT({field} FROM {x}) AS BIGINT)"


class _TcUnsupported(Exception):
    pass


_QUICK = {"pcto": "PctTotal", "rank": "Rank", "cum": "RunningTotal", "pcdf": "PctDiff",
          "diff": "Difference"}


def _ref_field(ref: str) -> str:
    """'[ds].[none:Agent:nk]' / '[ds].[Agent]' / '[none:Agent:nk]' → 'Agent'."""
    last = re.findall(r"\[([^\]]+)\]", ref or "")
    if not last:
        return ""
    inner = last[-1]
    parts = _unescape_ref(inner).split(":")
    return _instance_parts("[" + inner + "]")[1] if len(parts) >= 3 else _unescape_ref(inner)


def _tc_spec(ws, ref: str, field_name: str) -> dict:
    """Table-calc direction: the sheet instance's `<table-calc>` overrides the calc; no node means Table (across)..."""
    node = None
    for ci in ws.iter("column-instance"):
        if ref and (ci.get("name") or "").replace(_OBJ_PREFIX, "") == ref:
            node = next((t for t in ci.findall("table-calc") if not t.get("field")), None)
            break
    if node is None:
        for c in ws.iter("column"):
            if (c.get("name") or "").strip("[]") == field_name:
                calc = c.find("calculation")
                node = calc.find("table-calc") if calc is not None else None
                break
    return _tc_node_spec(node)


def _tc_node_spec(node) -> dict:
    ot = (node.get("ordering-type") if node is not None else None) or "Rows"
    fields = [_ref_field(o.get("field")) for o in (node.findall("order") if node is not None else [])]
    if not fields and node is not None and node.get("ordering-field"):
        fields = [_ref_field(node.get("ordering-field"))]
    out = {"ordering": ot, "type": node.get("type") if node is not None else "",
           "fields": fields, "ok": ot in ("Rows", "Columns", "Field")}
    if node is not None and node.get("type") in ("WindowTotal", "Percentile", "MovingCalc"):
        out.update(ok=False, why=f"quick table calculation {node.get('type')}")
    if not out["ok"]:
        out.setdefault("why", f"table calculation direction '{ot}' not translated")
    return out


def _tc_nested(ws, ref: str, tr) -> dict:
    """Directions of nested calcs of an instance."""
    out = {}
    for ci in ws.iter("column-instance"):
        if ref and (ci.get("name") or "").replace(_OBJ_PREFIX, "") == ref:
            for t in ci.findall("table-calc"):
                fname = _ref_field(t.get("field")) if t.get("field") else ""
                if fname:
                    tr._tc_n = getattr(tr, "_tc_n", 0) + 1
                    tag = f"__tc{tr._tc_n}__"
                    tr.tc_tags[fname] = tag
                    out[tag] = _tc_node_spec(t)
            break
    return out


def _quick_formula(ref: str, spec: dict, tr) -> str:
    """Quick table calc `[pcto:sum:Sales:qk]` -> a Tableau formula the regular translator handles."""
    parts = _unescape_ref(ref.strip("[]")).split(":")
    while len(parts) > 4 and parts[-1].isdigit():
        parts.pop()
    if len(parts) < 4:
        return ""
    outer, inner, fld = parts[0].lower(), parts[1].lower(), ":".join(parts[2:-1])
    fn = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX", "cnt": "COUNT",
          "ctd": "COUNTD", "cntd": "COUNTD", "attr": "ATTR"}.get(inner)
    if inner in ("cnt", "ctd", "cntd") and _OBJECT_ID.search(fld):
        x = "SUM(1)"
    elif inner == "usr":
        x = f"[{fld}]"
    elif fn:
        x = f"{fn}([{fld}])"
    else:
        return ""
    kind = spec.get("type") or _QUICK.get(outer, "")
    return {"PctTotal": f"({x}) / TOTAL({x})", "Rank": f"RANK({x})",
            "RunningTotal": f"RUNNING_SUM({x})",
            "Difference": f"ZN({x}) - LOOKUP(ZN({x}), -1)",
            "PctDiff": f"(ZN({x}) - LOOKUP(ZN({x}), -1)) / ABS(LOOKUP(ZN({x}), -1))"}.get(kind, "")


def _tc_query(ws, dims, measures, dref, tc_out, tc_filters, wheres, target,
              havings=None) -> str:
    """Two-level sheet query with table calculations (see `tablecalc`)."""
    rows_refs = [r for el in ws.iter("rows") if el.text
                 for r in inst_refs(el.text)]
    cols_refs = [r for el in ws.iter("cols") if el.text
                 for r in inst_refs(el.text)]
    tc_dims = {i for k, i, _ in tc_out if k == "d"}
    inner_dims = [i for i in range(len(dims)) if i not in tc_dims]
    dname = {i: f"_d{n}" for n, i in enumerate(inner_dims)}

    def tg(spec):
        return {t: ap(sp) for t, sp in (spec or {}).get("tagged", {}).items()}

    def ap(spec):
        def role(i):
            r = dref[i] if i < len(dref) else ""
            return "R" if r in rows_refs else "C" if r in cols_refs else "M"
        ordered = lambda xs, shelf: sorted(xs, key=lambda i: shelf.index(dref[i])
                                           if dref[i] in shelf else 99)
        R = ordered([i for i in inner_dims if role(i) == "R"], rows_refs)
        C = ordered([i for i in inner_dims if role(i) == "C"], cols_refs)
        M = [i for i in inner_dims if role(i) == "M"]
        if spec["ordering"] == "Columns":
            A, P = R + M, C
        elif spec["ordering"] == "Field":
            want = spec["fields"]
            A = sorted([i for i in inner_dims if _ref_field(dref[i]) in want],
                       key=lambda i: want.index(_ref_field(dref[i])))
            P = [i for i in inner_dims if i not in A]
        else:
            A, P = C + M, R
        return ([dname[i] for i in P], [f"{dname[i]} ASC NULLS FIRST" for i in A])

    aggs, wcols, outs = [], [], []
    spec_of = {(k, i): sp for k, i, sp in tc_out}
    dim_alias = sorted(((dims[i].strip(), dname[i]) for i in inner_dims if dims[i].strip()),
                       key=lambda x: -len(x[0]))

    def outer(e: str) -> str:
        """A view dimension outside an aggregate is visible from outside as `_dN`."""
        mask = _tc._strip_subqueries(e)
        for d, al in dim_alias:
            pos = 0
            while True:
                k = mask.find(d, pos)
                if k < 0:
                    break
                prev = mask[k - 1:k]
                nxt = mask[k + len(d):k + len(d) + 1]
                if prev not in (".", '"') and not (prev.isalnum() or prev == "_") and \
                        not (nxt.isalnum() or nxt == "_"):
                    e = e[:k] + al + e[k + len(d):]
                    mask = mask[:k] + al + mask[k + len(d):]
                    pos = k + len(al)
                else:
                    pos = k + len(d)
        return e
    for i in range(len(dims)):
        if i in tc_dims:
            part, order = ap(spec_of[("d", i)])
            outs.append(_tc.compile_measure(outer(_tc.split_aggregates(dims[i], aggs)), part, order,
                                            aggs, wcols, tg(spec_of[("d", i)])))
        else:
            outs.append(dname[i])
    for j, m in enumerate(measures):
        sp = spec_of.get(("m", j))
        part, order = ap(sp) if sp else ([], [])
        outs.append(_tc.compile_measure(outer(_tc.split_aggregates(m, aggs)), part, order, aggs,
                                        wcols, tg(sp)))
    conds = []
    for expr, sp in tc_filters:
        if not sp.get("ok"):
            raise _TcUnsupported(sp.get("why") or "table-calc filter")
        part, order = ap(sp)
        conds.append(_tc.compile_measure(outer(_tc.split_aggregates(expr, aggs)), part, order, aggs,
                                         wcols))
    sel = [f"{dims[i]} AS {dname[i]}" for i in inner_dims] + \
          [f"{a} AS _a{k}" for k, a in enumerate(aggs)]
    if not sel:
        sel = ["COUNT(*) AS _a0"]
    frm = _table_for(target, " ".join(sel) + " " + " ".join(wheres))
    inner = f"SELECT {', '.join(sel)} FROM {frm}"
    if wheres:
        inner += " WHERE " + " AND ".join(wheres)
    if inner_dims:
        inner += " GROUP BY " + ", ".join(str(n + 1) for n in range(len(inner_dims)))
    if havings:
        inner += " HAVING " + " AND ".join(havings)
    return _tc.build_query(inner, outs[:len(dims)], outs[len(dims):], wcols, where=conds)


def _dq_to_sq(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch in "'\"":
            j, buf = i + 1, []
            while j < len(s):
                if s[j] == ch and j + 1 < len(s) and s[j + 1] == ch:
                    buf.append(ch)
                    j += 2
                    continue
                if s[j] == ch:
                    break
                buf.append(s[j])
                j += 1
            body = "".join(buf)
            out.append("'" + body.replace("'", "''") + "'")
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def set_formula(g) -> str:
    """Set -> boolean Tableau formula `[field] IN (members)`; enumerated members of one level only."""
    if g.get("hidden") == "true" or g.get("{http://www.tableausoftware.com/xml/user}auto-column"):
        return ""
    if g.get("{http://www.tableausoftware.com/xml/user}ui-builder") == "nest-group":
        lv = [x.get("level") for x in g.iter("groupfilter") if x.get("function") == "level-members"]
        return " + \", \" + ".join(f"STR({x})" for x in lv) if len(lv) >= 2 else ""
    gfs = list(g.iter("groupfilter"))
    if not gfs or {x.get("function") for x in gfs} - {"member", "union"}:
        return ""
    levels = {x.get("level") for x in gfs if x.get("function") == "member"}
    mems = [x.get("member") for x in gfs if x.get("function") == "member" and x.get("member")]
    if len(levels) != 1 or not mems:
        return ""
    lvl = next(iter(levels))
    parts = _unescape_ref(lvl.strip("[]")).split(":")
    field = ":".join(parts[1:-1]) if len(parts) >= 3 else _unescape_ref(lvl.strip("[]"))
    lits = []
    for m in mems:
        v = m.strip()
        if not (re.fullmatch(r'"(?:[^"]|"")*"', v) or re.fullmatch(r"#[^#]+#", v)
                or re.fullmatch(r"-?\d+(\.\d+)?", v)):
            return ""
        lits.append(v)
    return f"[{field}] IN ({', '.join(lits)})"


def _member_list(members: list, tr) -> str:
    """Categorical filter members -> SQL list; unparsed members yield '' (filter not translated)."""
    out = []
    for mem in members:
        v = (mem or "").strip()
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            out.append("'" + v[1:-1].replace("'", "''") + "'")
        elif re.fullmatch(r"#[\d\- :.]+#", v):
            out.append(f"TIMESTAMP '{v[1:-1]}'" if tr.dialect == "hyper" else f"toDateTime('{v[1:-1]}')")
        elif re.fullmatch(r"-?\d+(\.\d+)?", v):
            out.append(v)
        else:
            return ""
    return ", ".join(out)


def _lit(v: str) -> str:
    """XML group member -> Tableau formula literal."""
    v = (v or "").strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return "'" + v[1:-1].replace('""', '"').replace("'", "''") + "'"
    return v


def group_formula(calc) -> str:
    """Group (`categorical-bin`) or numeric bin (`bin`) as a Tableau formula."""
    col = calc.get("column") or ""
    if not col:
        return ""
    if calc.get("class") == "categorical-bin":
        whens = []
        for b in calc.findall("bin"):
            vals = [_lit(v.text) for v in b.findall("value") if v.text is not None]
            if vals and b.get("value") is not None:
                whens.append(f"WHEN {col} IN ({', '.join(vals)}) THEN {_lit(b.get('value'))}")
        if not whens:
            return ""
        return "CASE " + " ".join(whens) + f" ELSE {col} END"
    if calc.get("class") == "bin":
        size = calc.get("size") or ""
        if re.fullmatch(r"-?\d+(\.\d+)?", size):
            return f"FLOOR({col} / {size}) * {size}"
    return ""


def _lod_measures(measures: list, pending: list, dim_fields: set, fine: list | None = None) -> str:
    """Measure aggregation built from a pure LOD or only from parameters; a single value per label."""
    for i, fn, expr, lod_dims, _name, *rest in pending:
        lod = rest[0] if rest else {}
        if not lod_dims <= dim_fields:
            if fine is not None and lod.get("dim_sql") and lod.get("table") and \
                    fn in ("SUM", "AVG", "MIN", "MAX"):
                fine.append((i, fn, expr, lod))
                continue
            return "LOD finer than the view"
        if fn in ("SUM", "AVG", "MIN", "MAX"):
            measures[i] = f"MIN({expr})"
        else:
            return "count over LOD"
    return ""


def _fine_lod(fn: str, expr: str, lod: dict, dims: list, wheres: list, tr) -> str:
    """FIXED finer than the view: Tableau joins the LOD at view + LOD dimensions and aggregates by the view."""
    table, x = lod["table"], "_fx"
    to_x = lambda e: e.replace(table + ".", f"{x}.")
    conds = [f"({to_x(w)})" for w in wheres]
    conds += [f"({to_x(d)}) IS NOT DISTINCT FROM ({tr._qualify(d, table)})" for d in dims]
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    return (f"MIN((SELECT {fn}(_fy._v) FROM (SELECT MIN({to_x(expr)}) AS _v FROM {table} AS {x}"
            f"{where} GROUP BY {', '.join(lod['dim_sql'])}) AS _fy))")


def is_table_calc_ref(ref: str) -> bool:
    """True when the reference is a table calc over another field (derivation outside, derivation inside)."""
    parts = _unescape_ref(ref.strip("[]")).split(":")
    return (len(parts) >= 4 and parts[0].lower() in KNOWN_DERIVATIONS
            and parts[1].lower() in KNOWN_DERIVATIONS)


def _instance_parts(ref: str) -> tuple[str, str]:
    """`[sum:ngr:qk]` -> ('sum', 'ngr'); `[none:x:nk]` has no aggregate."""
    inner = _unescape_ref(ref.strip("[]"))
    parts = inner.split(":")
    while len(parts) > 3 and parts[-1].isdigit():
        parts.pop()
    while len(parts) > 3 and re.fullmatch(r"vt\w+", parts[-2]):
        parts.pop(-2)
    if len(parts) > 3 and parts[0] in ("fVal", "fIdx", "fTrend", "fUpper", "fLower"):
        parts.pop(0)
    if len(parts) >= 3:
        return parts[0].lower(), ":".join(parts[1:-1])
    return "", inner


_REF_ESCAPE = re.compile(r"\\(?=[^A-Za-z0-9_])")


def _unescape_ref(inner: str) -> str:
    """Remove the escaping Tableau applies inside square brackets (`\%` -> `%`)."""
    return _REF_ESCAPE.sub("", inner)


_OBJECT_ID = re.compile(r"_[0-9A-F]{32}$")
_OBJ_PREFIX = "[__tableau_internal_object_id__]."


def inst_refs(text: str) -> list:
    """Instance references `[ds].[inst]` from shelf/encoding text; the relationship-model record counter uses..."""
    return re.findall(r"\[[^\]]+\]\.(\[[^\]]+\])", (text or "").replace(_OBJ_PREFIX, ""))

_PART_SQL = {"yr": "year", "qr": "quarter", "mn": "month", "dy": "day", "wd": "weekday",
             "hr": "hour", "wk": "week", "day": "day"}

_AGG_SQL = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX",
            "cnt": "COUNT", "cntd": "COUNT_DISTINCT", "ctd": "COUNT_DISTINCT",
            "usr": "", "none": "",
            "attr": "MIN", "median": "MEDIAN"}

_HAS_AGG = re.compile(r"\b(SUM|AVG|MIN|MAX|COUNT|MEDIAN|uniqExact|any)\s*\(", re.I)


def _except_conditions(fl, tr) -> str:
    """Translate an exception (`function="except"`) into `NOT (...)`."""
    exc = next((g for g in fl.iter("groupfilter") if g.get("function") == "except"), None)
    if exc is None:
        return ""
    reorder = next((g for g in exc.iter("groupfilter")
                    if g.get("function") == "reorder-dimensionality"), None)
    if reorder is None:
        return ""
    by_level: dict[str, list[str]] = {}
    for mem in reorder.iter("groupfilter"):
        if mem.get("function") != "member" or not mem.get("level"):
            continue
        raw = (mem.get("member") or "").strip()
        if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
            raw = raw[1:-1]
        by_level.setdefault(mem.get("level"), []).append(raw.replace("'", "''"))
    if not by_level:
        return ""
    parts = []
    for level, vals in by_level.items():
        cond = _member_in(level, list(dict.fromkeys(vals)), tr)
        if not cond:
            return ""
        parts.append(cond)
    return "(NOT (" + " AND ".join(parts) + "))"


def _member_in(level: str, vals: list, tr) -> str:
    """`level IN (members)` in a level view: date part, calculation, or boolean members."""
    agg, name = _instance_parts(level)
    if name in tr.calcs:
        expr, why = tr.to_sql(tr.calcs[name])
        if why or not expr:
            return ""
    elif not tr.columns or name in tr.columns:
        expr = tr.quote_ident(name)
    else:
        return ""
    if not re.fullmatch(r'"[^"]+"|\w+', expr):
        expr = f"({expr})"
    if agg in _PART_SQL:
        expr = date_part_sql(tr.dialect, _PART_SQL[agg], expr)
        if not all(re.fullmatch(r"-?\d+", v) for v in vals):
            return ""
        return f"{expr} IN ({', '.join(vals)})"
    discrete = _discrete_date_in(expr, agg, vals, tr.dialect)
    if discrete:
        return discrete
    if agg in _TRUNC_SQL or agg in _DISCRETE_TRUNC:
        unit = _TRUNC_SQL.get(agg) or _DISCRETE_TRUNC[agg]
        expr = tr.d["trunc"].get(unit, tr.d["trunc"]["day"]).format(expr)
    if vals and all(v.lower() in ("true", "false") for v in vals):
        return f"{expr} IN ({', '.join(v.upper() for v in vals)})"
    listed = ", ".join((f"TIMESTAMP '{v[1:-1]}'" if tr.dialect == "hyper" else f"toDateTime('{v[1:-1]}')")
                       if re.fullmatch(r"#[\d\- :.]+#", v) else f"'{v}'" for v in vals)
    return f"{expr} IN ({listed})"


def _is_aggregated(expr: str) -> bool:
    return bool(_HAS_AGG.search(expr))
_DISCRETE_TRUNC = {"my": "month", "mdy": "day", "md": "day"}


def _discrete_date_in(expr: str, agg: str, vals: list, dialect: str) -> str:
    """Discrete date members as numbers: `my` = YYYYMM, `md` = YYYYMMDD."""
    unit = _DISCRETE_TRUNC.get(agg)
    width = {"month": 6, "day": 8}.get(unit or "")
    if not width or not vals or not all(re.fullmatch(rf"\d{{{width}}}", v) for v in vals):
        return ""
    y, m = date_part_sql(dialect, "year", expr), date_part_sql(dialect, "month", expr)
    key = f"({y} * 100 + {m})" if width == 6 else \
        f"({y} * 10000 + {m} * 100 + {date_part_sql(dialect, 'day', expr)})"
    return f"{key} IN ({', '.join(vals)})"


_TRUNC_SQL = {"tdy": "day", "twk": "week", "tmn": "month",
              "tqr": "quarter", "tyr": "year"}


class _HyperTarget:
    """Run SQL inside the .hyper itself, the exact source Tableau reads."""

    def __init__(self, hyper_path: str):
        self.path = hyper_path
        self.dialect = "hyper"
        from tableauhyperapi import Connection, HyperProcess, Telemetry

        from .extract import HYPER_QUIET
        self._hp = HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                                parameters=HYPER_QUIET)
        self._conn = None
        try:
            self._conn = Connection(endpoint=self._hp.endpoint, database=hyper_path)
            names = []
            for schema in self._conn.catalog.get_schema_names():
                names += list(self._conn.catalog.get_table_names(schema))
            if not names:
                raise RuntimeError("the extract has no tables")
            best = next((n for n in names if str(n).lower().count("extract") >= 2),
                        names[0])
            self.table = str(best)
            tdef = self._conn.catalog.get_table_definition(best)
            self.columns = {c.name.unescaped for c in tdef.columns}
            self.tables = {}
            self.date_cols = set()
            self.text_cols = set()
            for n in names:
                td = self._conn.catalog.get_table_definition(n)
                self.tables[str(n)] = {c.name.unescaped for c in td.columns}
                self.date_cols |= {c.name.unescaped for c in td.columns
                                   if str(c.type).upper().startswith(("DATE", "TIMESTAMP"))}
                self.text_cols |= {(str(n), c.name.unescaped) for c in td.columns
                                   if str(c.type).upper().startswith(("TEXT", "VARCHAR", "CHAR"))}
            for cols in self.tables.values():
                self.columns |= cols
        except Exception:
            self.close()
            raise

    def execute(self, sql: str):
        return self._conn.execute_list_query(_chsafe.read_only(sql))

    def close(self):
        try:
            if self._conn is not None:
                self._conn.close()
        finally:
            self._hp.close()


class _ClickhouseTarget:
    @_chsafe.guard
    def __init__(self, db: str, table: str):
        from . import config
        from .schema import fetch_schema
        self.dialect = "clickhouse"
        self._ch = config.clickhouse(read_only=True)
        self.table = f"{db}.{table}"
        self.columns = {f["name"] for f in fetch_schema(db, table)}

    @_chsafe.guard
    def execute(self, sql: str):
        return self._ch.execute(_chsafe.read_only(sql))

    def close(self):
        pass


class _CustomSqlTarget:
    """Workbook on live Custom SQL: the run uses its own query."""

    @_chsafe.guard
    def __init__(self, sql: str):
        from . import config
        self.dialect = "clickhouse"
        self._ch = config.clickhouse(read_only=True)
        _chsafe.read_only(sql)
        self.table = f"(\n{sql}\n) AS q"
        self.columns = {r[0] for r in self._ch.execute(f"DESCRIBE ({sql})")}

    @_chsafe.guard
    def execute(self, sql: str):
        return self._ch.execute(_chsafe.read_only(sql))

    def close(self):
        pass


def unescape_sql(text: str) -> str:
    """Unescape comparison operators in Custom SQL read from the workbook (Tableau doubles `>` and `<` on save)."""
    for bad, good in ((">>=", ">="), ("<<=", "<="), (">>", ">"), ("<<", "<")):
        text = text.replace(bad, good)
    return text


def custom_sql_of(book) -> str:
    """The workbook's Custom SQL if it targets our ClickHouse (host check required)."""
    from . import config

    host = config.get("host")
    ours = set()
    for nc in book.root.iter("named-connection"):
        c = nc.find("connection")
        if c is not None and host and (c.get("server") or "") == host:
            ours.add(nc.get("name"))
    for rel in book.root.iter("relation"):
        if (rel.get("type") == "text" and rel.get("connection") in ours
                and (rel.text or "").strip()):
            return unescape_sql(rel.text.strip())
    return ""


def custom_sql_map(book) -> dict:
    """`datasource name -> its Custom SQL` for workbooks with several sources."""
    from . import config

    host = config.get("host")
    ours = set()
    for nc in book.root.iter("named-connection"):
        c = nc.find("connection")
        if c is not None and host and (c.get("server") or "") == host:
            ours.add(nc.get("name"))
    out = {}
    for ds in book.root.findall("./datasources/datasource"):
        for rel in ds.iter("relation"):
            if (rel.get("type") == "text" and rel.get("connection") in ours
                    and (rel.text or "").strip()):
                out[ds.get("name")] = unescape_sql(rel.text.strip())
                break
    return out


def sheet_datasource(ws) -> str:
    """Datasource the sheet sits on (`Parameters` is ignored)."""
    for ds in ws.iter("datasource"):
        nm = ds.get("name") or ""
        if nm and nm != "Parameters":
            return nm
    return ""


def hyper_map(book) -> dict:
    """Datasource -> name of its `.hyper` inside the package (a workbook may carry several extracts)."""
    out = {}
    dss = book.root.find("datasources")
    if dss is None:
        return out
    for ds in dss.findall("datasource"):
        nm = ds.get("name") or ""
        if not nm or nm == "Parameters":
            continue
        for con in ds.iter("connection"):
            if con.get("class") == "hyper" and con.get("dbname"):
                out[nm] = con.get("dbname")
                break
    return out


_HYPER_CACHE: dict = {}


def _open_hyper(book_path: str, arcname: str):
    """Target on an extract from the package; repeated calls reuse the unpacked cached file."""
    try:
        return _HyperTarget(_unpack_member(book_path, arcname))
    except Exception:
        return _HyperTarget(_unpack_member(book_path, arcname, fresh=True))


def _unpack_member(book_path: str, arcname: str, fresh: bool = False) -> str:
    """Extract a package entry to a temp file; repeated calls reuse the cache."""
    import os
    import tempfile
    import zipfile
    try:
        st = os.stat(book_path)
        key = (os.path.abspath(book_path), int(st.st_mtime), st.st_size, arcname)
    except OSError:
        key = (os.path.abspath(book_path), 0, 0, arcname)
    hit = None if fresh else _HYPER_CACHE.get(key)
    if hit and os.path.exists(hit):
        return hit
    with zipfile.ZipFile(book_path) as z:
        names = {n.lower(): n for n in z.namelist()}
        real = names.get(arcname.lower())
        if real is None:
            tail = arcname.rsplit("/", 1)[-1].lower()
            real = next((n for n in z.namelist() if n.lower().endswith(tail)), None)
        if real is None:
            raise RuntimeError(f"{arcname} not found in the package")
        tmp = os.path.join(tempfile.mkdtemp(), os.path.basename(real))
        with open(tmp, "wb") as f:
            f.write(z.read(real))
    if not fresh:
        _HYPER_CACHE[key] = tmp
    return tmp


def _hyper_from_zip(book, arcname: str):
    """Extract one extract from the package to a temp file and open the target on it."""
    return _open_hyper(book.path, arcname)


def _packaged_csv(book) -> str | None:
    """The packaged CSV the text connection reads (by its filename), else the first one."""
    import os
    csvs = [n for n in (book.archive or []) if n.lower().endswith(".csv")]
    want = {(c.get("filename") or "").lower() for c in book.root.iter("connection")
            if c.get("class") == "textscan"}
    return next((n for n in csvs if os.path.basename(n).lower() in want), csvs[0] if csvs else None)


def _pick_target(book, db: str, table: str):
    """The extract inside the workbook takes priority over the mart: Tableau reads it."""
    hyper_in_zip = [n for n in (book.archive or []) if n.lower().endswith(".hyper")]
    if hyper_in_zip:
        return _open_hyper(book.path, hyper_in_zip[0])
    csv_arc = _packaged_csv(book)
    if csv_arc:
        import os
        import tempfile
        import zipfile
        from .extract import build_hyper_from_csv, declared_column_types
        tmpdir = tempfile.mkdtemp()
        with zipfile.ZipFile(book.path) as z:
            csv_tmp = os.path.join(tmpdir, os.path.basename(csv_arc))
            with open(csv_tmp, "wb") as f:
                f.write(z.read(csv_arc))
        hyper_tmp = os.path.join(tmpdir, "from_csv.hyper")
        build_hyper_from_csv(csv_tmp, hyper_tmp,
                             types=declared_column_types(book.root))
        return _HyperTarget(hyper_tmp)
    sql = custom_sql_of(book)
    if sql:
        return _CustomSqlTarget(sql)
    if not db or not table:
        raise RuntimeError("workbook has no extract, Custom SQL or packaged CSV; "
                           "pass db/table of a live mart")
    return _ClickhouseTarget(db, table)


class _RelTarget:
    """Source with a relationship model (Tableau 2020.2+): extract tables are not joined, yet the workbook sees..."""

    def __init__(self, base, spec: dict, columns: set, date_cols: set):
        self.base, self.spec = base, spec
        self.dialect = base.dialect
        self.table = "_rel"
        self.tables = None
        self.columns = columns
        self.date_cols = date_cols

    def view_for(self, sql: str) -> str:
        """View with only the tables whose fields are used in the query (plus the path to the root)."""
        sp = self.spec
        need = {"r0"}
        for key, (al, _col) in sp["fields"].items():
            if f'"{key}"' in sql or (re.fullmatch(r"[A-Za-z_]\w*", key)
                                     and re.search(rf"(?<![\w\"]){re.escape(key)}(?![\w\"])", sql)):
                need.add(al)
        for al in list(need):
            while al in sp["parent"]:
                al = sp["parent"][al]
                need.add(al)
        sel = [f'{al}."{col}" AS "{key}"' for key, (al, col) in sp["fields"].items() if al in need]
        joins = [j for al, j in sp["joins"] if al in need]
        return f"SELECT {', '.join(sel)} FROM {sp['root']} AS r0 " + " ".join(joins)

    def execute(self, sql: str):
        return self.base.execute(f"WITH _rel AS ({self.view_for(sql)}) {sql}")

    def close(self):
        self.base.close()


def _rel_side(op: str, fields: dict):
    """Relationship condition side -> (object, column, SQL template | None); a bare field or DATEPART/DATETRUNC..."""
    op = (op or "").strip()
    if re.fullmatch(r"-?\d+(\.\d+)?|'[^']*'", op):
        return "", "", op
    if op.strip("[]") in fields and re.fullmatch(r"\[[^\]]+\]|[^\[\]()]+", op):
        oid, col = fields[op.strip("[]")]
        return oid, col, None
    m = re.fullmatch(r"(?i)(DATEPART|DATETRUNC)\(\s*'(\w+)'\s*,\s*\[([^\]]+)\]\s*\)", op)
    if m and m.group(3) in fields:
        oid, col = fields[m.group(3)]
        unit = m.group(2).lower()
        tpl = (date_part_sql("hyper", unit, "{}") if m.group(1).upper() == "DATEPART"
               else f"DATE_TRUNC('{unit}', {{}})")
        return oid, col, tpl
    return None


def relation_view(root, target):
    """`_rel` view from the first datasource's `<object-graph>` with relationships -> (spec, columns, dates) or None."""
    tables = getattr(target, "tables", None) or {}
    if len(tables) < 2:
        return None
    for ds in root.iter("datasource"):
        og = ds.find(".//object-graph")
        if og is None or og.find(".//relationship") is None:
            continue
        objs = [o for o in og.iter("object") if o.get("id")]
        hyper_of = {}
        for o in objs:
            tbl = next((t for t in tables if t.endswith(f'"{o.get("id")}"')), None)
            if tbl:
                hyper_of[o.get("id")] = tbl
        if len(hyper_of) < 2:
            continue
        cap2id = {o.get("caption"): o.get("id") for o in objs}
        fields = {}
        for m in ds.iter("map"):
            key = (m.get("key") or "").strip("[]")
            mm = re.fullmatch(r"\[(.+?)\]\.\[(.+)\]", m.get("value") or "")
            if not key or not mm:
                continue
            oid = mm.group(1) if mm.group(1) in hyper_of else cap2id.get(mm.group(1))
            if oid in hyper_of:
                fields.setdefault(key, (oid, mm.group(2)))
        for o in objs:
            if o.get("id") in hyper_of:
                for c in o.iter("column"):
                    if c.get("name") and c.getparent().tag == "columns":
                        fields.setdefault(c.get("name"), (o.get("id"), c.get("name")))
        root_id = next((o.get("id") for o in objs if o.get("id") in hyper_of), None)
        alias = {root_id: "r0"}
        joins, parent = [], {}
        rels = list(og.iter("relationship"))
        for _ in range(len(rels)):
            for rel in rels:
                a = rel.find("first-end-point")
                b = rel.find("second-end-point")
                if a is None or b is None:
                    continue
                ia, ib = a.get("object-id"), b.get("object-id")
                if (ia in alias) == (ib in alias) or ia not in hyper_of or ib not in hyper_of:
                    continue
                new = ib if ia in alias else ia
                pairs = []
                for e in rel.iter("expression"):
                    if e.get("op") == "=":
                        sides = [_rel_side(x.get("op", ""), fields) for x in e.findall("expression")]
                        if len(sides) == 2 and all(sides):
                            pairs.append(sides)
                if not pairs:
                    continue
                alias[new] = f"r{len(alias)}"
                parent[alias[new]] = alias[ib if new == ia else ia]
                conds = []
                txt = getattr(target, "text_cols", set()) or set()
                for (ol, cl, fl_), (or_, cr, fr_) in pairs:
                    col_ = (' COLLATE "binary"' if fl_ is None and fr_ is None and
                            (hyper_of[ol], cl) in txt and (hyper_of[or_], cr) in txt else "")
                    lhs = fl_ if not ol else (fl_ or "{}").format(f'{alias[ol]}."{cl}"')
                    rhs = fr_ if not or_ else (fr_ or "{}").format(f'{alias[or_]}."{cr}"')
                    conds.append(f'{lhs}{col_} IS NOT DISTINCT FROM {rhs}{col_}')
                joins.append((alias[new], f"LEFT JOIN {hyper_of[new]} AS {alias[new]} ON "
                              + " AND ".join(conds)))
        if len(alias) < 2:
            continue
        flds, cols, dates = {}, set(), set()
        tdates = getattr(target, "date_cols", set()) or set()
        for key, (oid, col) in fields.items():
            if oid in alias and col in tables[hyper_of[oid]]:
                flds[key] = (alias[oid], col)
                cols.add(key)
                if col in tdates:
                    dates.add(key)
        if not flds:
            continue
        spec = {"root": hyper_of[root_id], "fields": flds, "joins": joins, "parent": parent}
        return spec, cols, dates
    return None


def column_aliases(root) -> dict:
    """Workbook field name -> physical column, from the datasource `<cols>`."""
    out = {}
    for m in root.iter("map"):
        key = (m.get("key") or "").strip("[]")
        value = (m.get("value") or "")
        if not key or "." not in value:
            continue
        physical = value.rsplit(".", 1)[1].strip("[]")
        if physical and physical != key:
            out[key] = physical
    return out


def _book_dicts(root, dynamic: bool = True) -> tuple:
    """Workbook dictionaries: calculations, captions, parameters, set names."""
    calcs: dict[str, str] = {}
    captions: dict[str, str] = {}
    params: dict[str, str] = {}
    dyn: dict[str, str] = {}
    for c in root.iter("column"):
        name = (c.get("name") or "").strip("[]")
        cap = c.get("caption") or ""
        if cap:
            captions[cap] = name
        calc = c.find("calculation")
        if c.get("param-domain-type"):
            params[name] = (c.get("value") or "").strip()
            if c.get("default-value-field"):
                dyn[name] = (re.findall(r"\[([^\]]+)\]", c.get("default-value-field")) or [""])[-1]
            continue
        if calc is not None and calc.get("formula"):
            calcs[name] = calc.get("formula")
        elif calc is not None and name not in calcs:
            f = group_formula(calc)
            if f:
                calcs[name] = f
    for name, fld in (dyn.items() if dynamic else ()):
        if fld in calcs:
            params[name] = "(" + Translator.strip_comments(calcs[fld]) + "\n)"
    set_names = set()
    for g in root.iter("group"):
        nm = (g.get("name") or "").strip("[]")
        f = set_formula(g)
        if nm and f and nm not in calcs:
            calcs[nm] = f
            set_names.add(nm)
            if g.get("caption"):
                captions.setdefault(g.get("caption"), nm)
                set_names.add(g.get("caption"))
    return calcs, captions, params, set_names


def dynamic_param_values(path: str) -> dict:
    """Values of dynamic parameters at workbook open."""
    from .lint import load
    book = load(path)
    root = book.root
    dyn = [(c.get("name") or "").strip("[]") for c in root.iter("column")
           if c.get("param-domain-type") and c.get("default-value-field")]
    if not dyn:
        return {}
    calcs, captions, params, _sets = _book_dicts(root)
    out = {}
    try:
        t = _pick_target(book, "", "")
    except Exception:
        return {}
    try:
        tr = Translator(calcs, captions, params, t.columns, dialect=t.dialect,
                        aliases=column_aliases(root))
        tr.lod_table = getattr(t, "table", None)
        for name in dyn:
            if params.get(name, "").startswith("("):
                sql, why = tr.to_sql(params[name])
                if why or not sql:
                    continue
                try:
                    rows = t.execute(f"SELECT {sql} FROM {t.table} LIMIT 1")
                except Exception:
                    continue
                if rows:
                    out[name] = re.sub(r" 00:00:00$", "", str(rows[0][0]))
    finally:
        t.close()
    return out


def dry_run(path: str, db: str = "", table: str = "", limit: int = 5,
            sample_rows: int = 3, relax: bool = False,
            root=None, dynamic: bool = False) -> list[SheetResult]:
    """Run every sheet of the workbook on its real source (extract -> .hyper, otherwise live)."""
    from .lint import load
    book = load(path)
    if root is not None:
        book.root = root
    root = book.root

    calcs, captions, params, set_names = _book_dicts(root, dynamic=dynamic)

    try:
        target = _pick_target(book, db, table)
    except Exception as exc:
        return [SheetResult("(source)", "skipped",
                            note=f"source unavailable ({type(exc).__name__}: {str(exc)[:120]}); "
                                 f"the whole run is skipped rather than passed off as a partial check")]

    shared = root.find(".//shared-views")
    shared_filters = []
    if shared is not None:
        for c in shared.iter("column"):
            calc = c.find("calculation")
            nm = (c.get("name") or "").strip("[]")
            if c.get("caption"):
                captions.setdefault(c.get("caption"), nm)
            if calc is not None and calc.get("formula") and nm not in calcs:
                calcs[nm] = calc.get("formula")
        shared_filters = list(shared.iter("filter"))

    aliases = column_aliases(root)
    if isinstance(target, _HyperTarget):
        try:
            rv = relation_view(root, target)
        except Exception:
            rv = None
        if rv:
            target = _RelTarget(target, *rv)
            aliases = {}

    def _tr(t):
        tr_ = Translator(calcs, captions, params, t.columns, dialect=t.dialect,
                         aliases={} if isinstance(t, _RelTarget) else aliases)
        tr_.lod_table = getattr(t, "table", None)
        tr_.lod_tables = getattr(t, "tables", None)
        tr_.date_cols = getattr(t, "date_cols", set()) or set()
        tr_.allow_tc = True
        tr_.sets = set_names
        tc_ = getattr(t, "text_cols", None) or getattr(getattr(t, "base", None), "text_cols", None)
        tr_.text_cols = {c for _t, c in (tc_ or set())}
        return tr_

    try:
        sql_map = custom_sql_map(book)
    except Exception:
        sql_map = {}
    hyper_ds = hyper_map(book) if isinstance(target, (_HyperTarget, _RelTarget)) else {}

    per_ds, kinds = {}, set()
    for ds in set(sql_map) | set(hyper_ds):
        per_ds[ds] = ("hyper", hyper_ds[ds]) if ds in hyper_ds else ("sql", sql_map[ds])
        kinds.add(per_ds[ds])
    if len(kinds) < 2:
        per_ds = {}

    if not per_ds:
        tr = _tr(target)
        try:
            return [_run_sheet(ws, tr, target, limit, shared_filters, sample_rows,
                               relax, dynamic)
                    for ws in root.iter("worksheet")]
        finally:
            target.close()

    extra, out = {}, []
    try:
        for ws in root.iter("worksheet"):
            ds = sheet_datasource(ws)
            if ds in per_ds:
                if ds not in extra:
                    kind, val = per_ds[ds]
                    t = (_CustomSqlTarget(val) if kind == "sql"
                         else _hyper_from_zip(book, val))
                    if kind == "hyper":
                        try:
                            rv_ = relation_view(root, t)
                        except Exception:
                            rv_ = None
                        if rv_:
                            t = _RelTarget(t, *rv_)
                    extra[ds] = (t, _tr(t))
                t, tr = extra[ds]
            else:
                t, tr = target, _tr(target)
            out.append(_run_sheet(ws, tr, t, limit, shared_filters, sample_rows,
                                  relax, dynamic))
        return out
    finally:
        target.close()
        for t, _ in extra.values():
            t.close()


def _measure_names_refs(ws) -> list:
    """Measures of a measures-by-measure-names table: they are listed in the filter, not on the shelf."""
    out = []
    for fl in ws.iter("filter"):
        if ":Measure Names" not in (fl.get("column") or ""):
            continue
        for mem in fl.iter("groupfilter"):
            raw = (mem.get("member") or "").strip('"')
            if not raw:
                continue
            found = inst_refs(raw)
            out += found
    seen = set()
    return [r for r in out if not (r in seen or seen.add(r))]


_UNKNOWN_COLUMN = re.compile(r"unknown column '([^']+)'")


def _explain_failure(exc: Exception, target) -> str:
    """Explain what is wrong in task terms rather than engine terms."""
    text = str(exc)
    m = _UNKNOWN_COLUMN.search(text)
    if m:
        col = m.group(1)
        known = getattr(target, "columns", set()) or set()
        if col not in known:
            near = sorted(k for k in known if k.lower()[:4] == col.lower()[:4])[:3]
            hint = f"; similar in the source: {', '.join(near)}" if near else ""
            return (f"workbook references column '{col}' that is NOT in the source; "
                    f"Tableau will drop the whole datasource and draw no sheets"
                    f"{hint}")
    return f"{type(exc).__name__}: {text[:200]}"


def _outer_ok(expr: str, tr) -> bool:
    """A condition on an aggregate goes to HAVING."""
    rest = _tc.split_aggregates(expr, [])
    forms = {tr.quote_ident(c) for c in tr.columns}
    return not any(t in forms for t in re.findall(r'"[^"]+"|\b[A-Za-z_]\w*\b',
                                                  _tc._strip_subqueries(rest)))


def _filter_field_sql(f_agg: str, name: str, tr) -> str:
    """Row-level filter field: column or calculation (by name, then caption) plus a date derivation from the..."""
    formula = tr.calcs.get(name)
    if formula is None and name not in tr.columns and tr.captions.get(name) in tr.calcs:
        formula = tr.calcs[tr.captions[name]]
    if formula is not None:
        expr, why = tr.to_sql(formula)
        if why or not expr:
            return ""
    elif not tr.columns or name in tr.columns or name in tr.aliases:
        expr = tr.quote_ident(name)
    else:
        return ""
    if not re.fullmatch(r'"[^"]+"|\w+', expr):
        expr = f"({expr})"
    if f_agg in _TRUNC_SQL or f_agg in _DISCRETE_TRUNC:
        unit = _TRUNC_SQL.get(f_agg) or _DISCRETE_TRUNC[f_agg]
        expr = tr.d["trunc"].get(unit, tr.d["trunc"]["day"]).format(expr)
    elif f_agg in _PART_SQL:
        expr = date_part_sql(tr.dialect, _PART_SQL[f_agg], expr)
    return expr


def _filter_lit(v: str, dialect: str) -> str:
    """Filter value (`<min>`, `<max>`, `period-anchor`) -> SQL literal."""
    v = (v or "").strip()
    m = re.fullmatch(r"#(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}:\d{2})(?:\.\d+)?)?#", v)
    if m:
        if m.group(2):
            ts = f"{m.group(1)} {m.group(2)}"
            return f"TIMESTAMP '{ts}'" if dialect == "hyper" else f"toDateTime('{ts}')"
        return DIALECTS[dialect]["date"].format(m.group(1))
    if re.fullmatch(r"-?\d+(\.\d+)?([eE][-+]?\d+)?", v):
        return v
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return "'" + v[1:-1].replace("'", "''") + "'"
    return ""


def _range_filter(fl, f_agg: str, name: str, tr) -> tuple:
    """Filter `class="quantitative"` -> (condition, level); `row` is WHERE, `agg` is HAVING."""
    iv = fl.get("included-values") or "in-range"
    if iv == "all":
        return "", ""
    fn = _AGG_SQL.get(f_agg) if f_agg else ""
    if fn is None and f_agg not in _TRUNC_SQL and f_agg not in _DISCRETE_TRUNC \
            and f_agg not in _PART_SQL:
        return "", ""
    expr = _filter_field_sql("" if fn else f_agg, name, tr)
    if not expr:
        return "", ""
    if fn:
        expr = f"COUNT(DISTINCT {expr})" if fn == "COUNT_DISTINCT" else f"{fn}({expr})"
    if _tc.has_table_calc(expr):
        return "", ""
    level = "agg" if _is_aggregated(_tc._strip_subqueries(expr)) else "row"
    if iv == "non-null":
        return f"({expr} IS NOT NULL)", level
    if iv == "null":
        return f"({expr} IS NULL)", level
    parts = []
    for tag, op in (("min", ">="), ("max", "<=")):
        raw = fl.findtext(tag)
        if raw is None or not raw.strip():
            continue
        lit = _filter_lit(raw, tr.dialect)
        if not lit:
            return "", ""
        parts.append(f"{expr} {op} {lit}")
    if not parts:
        return "", ""
    cond = " AND ".join(parts)
    if iv == "in-range-or-null":
        cond = f"({cond}) OR {expr} IS NULL"
    return f"({cond})", level


_PERIOD_MONTHS = {"year": 12, "quarter": 3, "month": 1}


def relative_window(anchor, unit: str, first: int, last: int, include_future: bool = True):
    """Tableau relative-date window: periods `first...last` from the anchor period (0 is current)."""
    import datetime as _dt
    a = anchor if isinstance(anchor, _dt.datetime) else \
        _dt.datetime(anchor.year, anchor.month, anchor.day)
    day0 = a.replace(hour=0, minute=0, second=0, microsecond=0)
    if unit in _PERIOD_MONTHS:
        step = _PERIOD_MONTHS[unit]
        base = a.year * 12 + (a.month - 1) // step * step

        def at(k):
            mm = base + k * step
            return _dt.datetime(mm // 12, mm % 12 + 1, 1)
    elif unit in ("week", "iso-week"):
        start = day0 - _dt.timedelta(days=a.weekday() if unit == "iso-week"
                                     else (a.weekday() + 1) % 7)

        def at(k):
            return start + _dt.timedelta(weeks=k)
    elif unit in ("day", "hour", "minute", "second"):
        span = {"day": _dt.timedelta(days=1), "hour": _dt.timedelta(hours=1),
                "minute": _dt.timedelta(minutes=1), "second": _dt.timedelta(seconds=1)}[unit]
        start = {"day": day0, "hour": a.replace(minute=0, second=0, microsecond=0),
                 "minute": a.replace(second=0, microsecond=0),
                 "second": a.replace(microsecond=0)}[unit]

        def at(k):
            return start + k * span
    else:
        return None
    lo, hi = at(first), at(last + 1)
    if not include_future:
        hi = min(hi, a if unit in ("hour", "minute", "second") else day0 + _dt.timedelta(days=1))
    return (lo, hi) if lo < hi else None


def _now_of(dialect: str):
    """The run's 'now': the frozen snapshot date when `framecmp` freezes `today`/`now`."""
    import datetime as _dt
    d = DIALECTS.get(dialect, {})
    for key in ("now", "today"):
        m = re.search(r"'(\d{4}-\d{2}-\d{2})(?: (\d{2}:\d{2}:\d{2}))?'", d.get(key, ""))
        if m:
            return _dt.datetime.fromisoformat(m.group(1) + ("T" + m.group(2) if m.group(2) else ""))
    return _dt.datetime.now()


def _parse_dt(text: str):
    import datetime as _dt
    m = re.match(r"#?(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}:\d{2}))?", (text or "").strip())
    if not m:
        return None
    return _dt.datetime.fromisoformat(m.group(1) + ("T" + m.group(2) if m.group(2) else ""))


def _relative_where(fl, f_agg: str, name: str, tr, target, dynamic: bool) -> str:
    """Filter `class="relative-date"` -> half-open date interval, anchored at `period-anchor` or the run's today."""
    expr = _filter_field_sql(f_agg, name, tr)
    if not expr or _tc.has_table_calc(expr) or _is_aggregated(_tc._strip_subqueries(expr)):
        return ""
    unit = (fl.get("period-type-v2") or fl.get("period-type") or "").lower()
    try:
        first, last = int(fl.get("first-period") or 0), int(fl.get("last-period") or 0)
    except ValueError:
        return ""
    future = (fl.get("include-future") or "true") != "false"
    if fl.get("period-anchor"):
        anchor = _parse_dt(fl.get("period-anchor"))
        if anchor is None:
            return ""
    else:
        anchor = _now_of(tr.dialect)
    win = relative_window(anchor, unit, first, last, future)
    if win and not dynamic and not fl.get("period-anchor") and tr.dialect == "hyper":
        try:
            rows = target.execute(f"SELECT MAX({expr}) FROM {_table_for(target, expr)}")
            newest = _parse_dt(str(rows[0][0])) if rows and rows[0][0] is not None else None
        except Exception:
            newest = None
        if newest is not None and newest < win[0]:
            win = relative_window(newest, unit, first, last, future)
    if not win:
        return ""
    lo, hi = (_filter_lit(f"#{x.isoformat(sep=' ')}#", tr.dialect) for x in win)
    cond = f"{expr} >= {lo} AND {expr} < {hi}"
    if fl.get("include-null") == "true":
        cond = f"({cond}) OR {expr} IS NULL"
    return f"({cond})"


def _top_count(raw: str, tr):
    """Top-N depth: a number or a `[Parameters].[Name]` parameter (by name)."""
    raw = (raw or "").strip()
    if re.fullmatch(r"\d+", raw):
        return int(raw)
    m = re.fullmatch(r"\[Parameters\]\.\[([^\]]+)\]", raw)
    if not m:
        return None
    try:
        n = int(float((tr.params.get(m.group(1)) or "").strip().strip('"')))
    except ValueError:
        return None
    return n if n >= 0 else None


def _top_n_where(fl, tr, target, ctx_wheres: list) -> str:
    """Top-N (`end -> order -> level-members`) -> `dimension IN (top N by measure)`, ranked within the context..."""
    col = fl.get("column") or ""
    m = re.search(r"\]\.(\[[^\]]+\])$", col)
    if not m or fl.get("class") != "categorical":
        return ""
    end = next((g for g in fl.iter("groupfilter")
                if g.get("function") == "end" and g.get("count")), None)
    if end is None or (end.get("units") or "records") != "records":
        return ""
    order = next((g for g in end.iter("groupfilter") if g.get("function") == "order"), None)
    n = _top_count(end.get("count"), tr)
    if order is None or n is None:
        return ""
    f_agg, dim_name = _instance_parts(m.group(1))
    if dim_name.startswith(":"):
        return ""
    dim_sql = _filter_field_sql(f_agg, dim_name, tr)
    if not dim_sql or _tc.has_table_calc(dim_sql) or \
            _is_aggregated(_tc._strip_subqueries(dim_sql)):
        return ""
    expr_raw = (order.get("expression") or "").strip()
    wrap = re.fullmatch(r"(?i)(USER|NONE)\((\[[^\]]+\])\)", expr_raw)
    if wrap:
        expr_raw = wrap.group(2)
    if not expr_raw:
        return ""
    tr.last_lod = {}
    rank_sql, why = tr.to_sql(expr_raw)
    if why or not rank_sql or _tc.has_table_calc(rank_sql):
        return ""
    if not _is_aggregated(tr.last_lod.get("masked", rank_sql)):
        rank_sql = f"SUM({rank_sql})"
    desc = (order.get("direction") or "DESC").upper() != "ASC"
    if (end.get("end") or "top") == "bottom":
        desc = not desc
    where = (" WHERE " + " AND ".join(ctx_wheres)) if ctx_wheres else ""
    sub = (f"SELECT {dim_sql} FROM {_table_for(target, dim_sql + ' ' + rank_sql + where)}"
           f"{where} GROUP BY {dim_sql} "
           f"ORDER BY {rank_sql} {'DESC' if desc else 'ASC'} NULLS LAST, {dim_sql} LIMIT {n}")
    return f"({dim_sql} IN ({sub}))"


def _run_sheet(ws, tr: Translator, target, limit: int, shared_filters=None,
               sample_rows: int = 3, relax: bool = False, dynamic: bool = False) -> SheetResult:
    """`relax=True` runs the sheet without the untranslatable part instead of refusing."""
    name = ws.get("name") or "?"
    dropped: list[str] = []
    refs: list[str] = []
    for tag in ("rows", "cols"):
        for el in ws.iter(tag):
            if el.text:
                refs += inst_refs(el.text)
    shelf_refs = set(refs)
    for enc in ("wedge-size", "color", "text", "size", "shape", "lod"):
        for el in ws.iter(enc):
            col = el.get("column")
            if col:
                refs += inst_refs(col)
    refs += _measure_names_refs(ws)
    seen: set = set()
    refs = [r for r in refs if not (r in seen or seen.add(r))]
    if not refs:
        return SheetResult(name, "skipped", note="no fields on shelves or encodings")
    optional = {r for r in refs if r not in shelf_refs}

    dims, measures, skipped = [], [], ""
    dlab, mlab = [], []
    dref: list = []
    mref: list = []
    _caps = {(c.get("name") or "").strip("[]"): c.get("caption")
             for c in ws.iter("column") if c.get("caption")}

    def _lab(fn: str) -> str:
        return _caps.get(fn) or fn
    lod_pending: list = []
    dim_fields: set = set()
    tc_out: list = []
    for ref in refs:
        agg, field_name = _instance_parts(ref)
        if field_name == ":Measure Names" or field_name.startswith(":"):
            continue
        if field_name in ("Latitude (generated)", "Longitude (generated)"):
            continue
        if is_table_calc_ref(ref):
            spec = _tc_spec(ws, ref, field_name)
            formula = _quick_formula(ref, spec, tr)
            expr, why = (tr.to_sql(formula) if formula else ("", "table calculation"))
            if why or not spec.get("ok"):
                if ref in optional:
                    continue
                if relax:
                    dropped.append(field_name + ("*" if ref in shelf_refs else ""))
                    continue
                skipped = why or spec.get("why") or "table calculation"
                break
            tc_out.append(("m", len(measures), spec))
            measures.append(expr)
            mlab.append(_lab(field_name)); mref.append(ref)
            continue
        if field_name in ("Multiple Values", "Measure Values"):
            if ref in optional:
                continue
            if relax:
                dropped.append("[Measure Values]")
                continue
            skipped = "[Measure Values] on the shelf"
            break
        if field_name in tr.params:
            expr, why = tr.to_sql(tr.params[field_name])
            if why or not expr:
                if ref in optional:
                    continue
                skipped = why or "parameter value not parsed"
                break
            dims.append(expr)
            dlab.append(_lab(field_name)); dref.append(ref)
            continue
        if agg in ("cnt", "ctd", "cntd") and _OBJECT_ID.search(field_name):
            measures.append("COUNT(*)")
            mlab.append(_lab(field_name)); mref.append(ref)
            continue
        expr = tr.quote_ident(field_name)
        if field_name == "Forecast Indicator" and field_name not in tr.columns:
            expr = "'Actual'"
        tr.last_lod = {}
        tr.tc_tags = {}
        nested = _tc_nested(ws, ref, tr)
        if field_name in tr.calcs:
            expr, why = tr.to_sql(tr.calcs[field_name])
            if why:
                if ref in optional:
                    continue
                if relax:
                    dropped.append(field_name + ("*" if ref in shelf_refs else ""))
                    continue
                skipped = why
                break
        elif field_name in tr.captions and tr.captions[field_name] in tr.calcs \
                and field_name not in tr.columns and field_name not in tr.aliases:
            expr, why = tr.to_sql(tr.calcs[tr.captions[field_name]])
            if why:
                if ref in optional:
                    continue
                if relax:
                    dropped.append(field_name + ("*" if ref in shelf_refs else ""))
                    continue
                skipped = why
                break
        lod = dict(tr.last_lod)
        tr.tc_tags = {}
        if _tc.has_table_calc(expr):
            spec = dict(_tc_spec(ws, ref, field_name), tagged=nested)
            bad = next((sp for sp in nested.values() if not sp.get("ok")), None)
            if bad:
                spec.update(ok=False, why=bad.get("why"))
            if not spec.get("ok"):
                if ref in optional:
                    continue
                if relax:
                    dropped.append(field_name + ("*" if ref in shelf_refs else ""))
                    continue
                skipped = spec.get("why") or "table calculation"
                break
            if ref in shelf_refs and re.search(r":(ok|nk)(:\d+)?\]$", ref):
                tc_out.append(("d", len(dims), spec))
                dims.append(expr)
                dlab.append(_lab(field_name)); dref.append(ref)
            else:
                tc_out.append(("m", len(measures), spec))
                measures.append(expr)
                mlab.append(_lab(field_name)); mref.append(ref)
            continue
        if agg in _TRUNC_SQL or agg in _DISCRETE_TRUNC:
            unit = _TRUNC_SQL.get(agg) or _DISCRETE_TRUNC[agg]
            tpl = tr.d["trunc"].get(unit, tr.d["trunc"]["day"])
            dims.append(tpl.format(expr))
            dlab.append(_lab(field_name)); dref.append(ref); dim_fields.add(field_name)
        elif agg in _PART_SQL:
            dims.append(date_part_sql(tr.dialect, _PART_SQL[agg], expr))
            dlab.append(_lab(field_name)); dref.append(ref); dim_fields.add(field_name)
        elif _is_aggregated(lod.get("masked", expr)):
            measures.append(expr)
            mlab.append(_lab(field_name)); mref.append(ref)
        elif agg in _AGG_SQL and _AGG_SQL[agg]:
            fn = _AGG_SQL[agg]
            if lod.get("pure"):
                lod_pending.append((len(measures), fn, expr, lod["dims"], field_name, lod))
            elif field_name in tr.calcs and tr.param_only(tr.calcs[field_name]):
                lod_pending.append((len(measures), fn, expr, set(), field_name, {}))
            measures.append(f"COUNT(DISTINCT {expr})" if fn == "COUNT_DISTINCT"
                            else f"{fn}({expr})")
            mlab.append(_lab(field_name)); mref.append(ref)
        else:
            dims.append(expr)
            dlab.append(_lab(field_name)); dref.append(ref); dim_fields.add(field_name)
    fine_lod: list = []
    if not skipped:
        why_lod = _lod_measures(measures, lod_pending, dim_fields, fine_lod)
        if why_lod:
            if relax:
                dropped.extend(p[4] for p in lod_pending)
            else:
                skipped = why_lod
    if skipped:
        return SheetResult(name, "skipped", note=f"{skipped}: cannot be translated to SQL")
    if not dims and not measures:
        return SheetResult(name, "skipped", note="only service fields on the shelves")

    wheres: list[str] = []
    ctx_wheres: list[str] = []
    top_wheres: list[str] = []
    tc_filters: list = []
    havings: list[str] = []
    filter_sources = list(ws.iter("filter")) + list(shared_filters or [])

    def _dim_filter(fl) -> None:
        col = fl.get("column") or ""
        m = re.search(r"\]\.(\[[^\]]+\])$", col)
        if not m:
            return
        f_agg, field_name = _instance_parts(m.group(1))
        if field_name.startswith((":", "Action ", "Tooltip ")):
            return
        if fl.get("class") == "quantitative":
            cond, level = _range_filter(fl, f_agg, field_name, tr)
            if level == "row":
                wheres.append(cond)
            elif level == "agg" and _outer_ok(cond, tr):
                havings.append(cond)
            return
        if fl.get("class") == "relative-date":
            cond = _relative_where(fl, f_agg, field_name, tr, target, dynamic)
            if cond:
                wheres.append(cond)
            return
        members = [g.get("member") for g in fl.iter("groupfilter") if g.get("member")]
        if field_name in tr.calcs:
            boolean = any((mem or "").strip('"').lower() == "true" for mem in members)
            funcs = {g.get("function") for g in fl.iter("groupfilter")}
            listed = _member_list(members, tr) if not boolean and members and \
                fl.get("class") == "categorical" and not funcs - {"member", "union", None} else ""
            if not boolean and not listed:
                return
            expr, why = tr.to_sql(tr.calcs[field_name])
            if not why and expr:
                cond = f"({expr})" if boolean else f"(({expr}) IN ({listed}))"
                if _tc.has_table_calc(expr):
                    tc_filters.append((cond if not boolean else expr,
                                       _tc_spec(ws, m.group(1), field_name)))
                elif _is_aggregated(_tc._strip_subqueries(expr)):
                    if _outer_ok(expr, tr):
                        havings.append(expr if boolean else cond)
                else:
                    wheres.append(cond)
            return
        if fl.get("class") != "categorical" or not members:
            return
        excluded = _except_conditions(fl, tr)
        if excluded:
            wheres.append(excluded)
            return
        funcs = {g.get("function") for g in fl.iter("groupfilter")}
        if funcs - {"member", "union", "level-members", None}:
            return
        vals = []
        for mem in members:
            v = (mem or "").strip()
            if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
                v = v[1:-1]
            vals.append(v.replace("'", "''"))
        if not vals:
            return
        expr = tr.quote_ident(field_name)
        discrete = _discrete_date_in(expr, f_agg, vals, tr.dialect)
        if discrete:
            wheres.append(f"({discrete})")
            return
        if f_agg in _PART_SQL:
            expr = date_part_sql(tr.dialect, _PART_SQL[f_agg], expr)
            if not all(re.fullmatch(r"-?\d+", v) for v in vals):
                return
            listed = ", ".join(vals)
        else:
            if f_agg in _TRUNC_SQL or f_agg in _DISCRETE_TRUNC:
                unit = _TRUNC_SQL.get(f_agg) or _DISCRETE_TRUNC[f_agg]
                expr = tr.d["trunc"].get(unit, tr.d["trunc"]["day"]).format(expr)
            listed = ", ".join(
                (f"TIMESTAMP '{v[1:-1]}'" if tr.dialect == "hyper" else f"toDateTime('{v[1:-1]}')")
                if re.fullmatch(r"#[\d\- :.]+#", v) else f"'{v}'" for v in vals)
        wheres.append(f"({expr} IN ({listed}))")

    for fl in filter_sources:
        k = len(wheres)
        _dim_filter(fl)
        if fl.get("context") == "true":
            ctx_wheres += wheres[k:]

    for fl in filter_sources:
        cond = _top_n_where(fl, tr, target, ctx_wheres)
        if cond:
            top_wheres.append(cond)
    wheres += top_wheres
    if fine_lod:
        tc_dims = {i for k, i, _ in tc_out if k == "d"}
        if tc_dims:
            return SheetResult(name, "skipped",
                               note="LOD finer than the view with a table-calc dimension: cannot be translated to SQL")
        for i, fn, expr, lod in fine_lod:
            measures[i] = _fine_lod(fn, expr, lod, dims, wheres, tr)

    synthetic = not measures
    select = ", ".join((dims or []) + (measures or ["count(*)"]))
    base = f"SELECT {select} FROM {_table_for(target, select + ' ' + ' '.join(wheres))}"
    if wheres:
        base += " WHERE " + " AND ".join(wheres)
    if dims:
        base += " GROUP BY " + ", ".join(str(i + 1) for i in range(len(dims)))
    if havings:
        base += " HAVING " + " AND ".join(havings)
    if tc_out or tc_filters:
        try:
            base = _tc_query(ws, dims, measures, dref, tc_out, tc_filters, wheres, target,
                             havings)
        except _TcUnsupported as exc:
            return SheetResult(name, "skipped", note=f"{exc}: cannot be translated to SQL")
    sql = f"{base} LIMIT {int(limit)}"
    extra = {"base_sql": base, "dim_exprs": dims, "measure_exprs": measures,
             "dim_labels": dlab, "measure_labels": mlab, "dim_refs": dref, "measure_refs": mref,
             "where_sql": (" WHERE " + " AND ".join(wheres)) if wheres else "",
             "synthetic_measure": synthetic,
             "relaxed": ("not computed: " + ", ".join(dropped[:6]) +
                         ("; marked * - a dimension was dropped, the grid differs from the real one"
                          if any(d.endswith("*") for d in dropped) else "")
                         ) if dropped else ""}

    try:
        rows = target.execute(sql)
    except Exception as exc:
        dss = [d.get("name") for d in ws.findall(".//view/datasources/datasource")
               if d.get("name") != "Parameters"]
        m_ = _UNKNOWN_COLUMN.search(str(exc))
        if len(dss) > 1 and m_ and m_.group(1) not in (getattr(target, "columns", set()) or set()):
            return SheetResult(name, "skipped", sql=sql,
                               note=f"data blending ({len(dss)} datasources): "
                                    f"'{m_.group(1)}' from the second one cannot be translated to SQL", **extra)
        return SheetResult(name, "error", sql=sql,
                           note=_explain_failure(exc, target), **extra)
    if not rows:
        return SheetResult(name, "empty", sql=sql,
                           note="the sheet returns ZERO rows and will open empty", **extra)
    return SheetResult(name, "ok", rows=len(rows), sql=sql,
                       sample=[list(map(str, r)) for r in rows[:sample_rows]], **extra)


def format_report(results: list[SheetResult]) -> str:
    if not results:
        return "the run produced no results"
    order = {"empty": 0, "error": 1, "ok": 2, "skipped": 3}
    lines = []
    counts = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    head = " · ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    lines.append(f"dry run: {head}")
    for r in sorted(results, key=lambda x: order.get(x.status, 9)):
        mark = {"ok": "✓", "empty": "✗", "error": "!", "skipped": "–"}.get(r.status, "?")
        tail = f" · {r.note}" if r.note else ""
        lines.append(f"  {mark} {r.sheet:24s} {r.status:8s} rows {r.rows}{tail}")
        if r.status in ("empty", "error") and r.sql:
            lines.append(f"      SQL: {r.sql[:220]}")
    return "\n".join(lines)


def _user_visible_fields(root) -> set:
    """Fields the user actually sees: dashboard filters, shelf fields and dimension-switcher items."""
    shown: set = set()

    def _add(ref: str):
        for part in re.findall(r"\[([^\]]+)\]", ref or ""):
            bits = part.split(":")
            shown.add(bits[1] if len(bits) >= 3 else part)

    for dash in root.iter("dashboard"):
        zones = dash.find("zones")
        for zone in (zones.iter("zone") if zones is not None else []):
            if zone.get("type-v2") in ("filter", "paramctrl"):
                _add(zone.get("param") or "")
    wsn = root.find("worksheets")
    for ws in (list(wsn) if wsn is not None else []):
        for shelf in ("rows", "cols"):
            for el in ws.iter(shelf):
                _add(el.text or "")
        for fl in ws.iter("filter"):
            _add(fl.get("column") or "")
    for col in root.iter("column"):
        if not col.get("param-domain-type"):
            continue
        for m in col.iter("member"):
            v = (m.get("value") or "").strip('"')
            if v:
                shown.add(v)
    return shown


def top_n_cap(root, sheet: str):
    """Rows a sheet's top-N filter keeps, or None if there is none."""
    ws = next((w for w in root.iter("worksheet") if w.get("name") == sheet), None)
    if ws is None:
        return None
    caps = []
    for gf in ws.iter("groupfilter"):
        if gf.get("function") != "end" or not gf.get("count"):
            continue
        c = gf.get("count").strip()
        if c.isdigit():
            caps.append(int(c))
            continue
        name = c.split("].[")[-1].strip("[]")
        for col in root.iter("column"):
            if name in (col.get("name", "").strip("[]"), col.get("caption", "")):
                v = (col.get("value") or "").strip('"')
                if v.lstrip("-").isdigit():
                    caps.append(int(v))
                break
    return min(caps) if caps else None


def visual_stats(path: str, db: str = "", table: str = "", cap: int = 200_000,
                 labels: int = 300) -> dict:
    """Category count, value spread and label length of a sheet."""
    from .lint import load
    book = load(path)
    results = dry_run(path, db, table, limit=1)
    ok = [r for r in results if r.base_sql and r.status in ("ok", "empty")]
    if not ok:
        return {"verdict": "no sheet could be executed; stats not collected",
                "sheets": []}

    try:
        target = _pick_target(book, db, table)
    except Exception as exc:
        return {"verdict": f"source unavailable ({str(exc)[:100]})", "sheets": []}

    out = []
    try:
        for r in ok:
            sub = f"({r.base_sql} LIMIT {int(cap)}) AS t"
            item = {"sheet": r.sheet, "categories": None, "max_label": None,
                    "spread": None, "labels": [], "dimensions": []}
            try:
                n = target.execute(f"SELECT COUNT(*) FROM {sub}")
                item["categories"] = int(list(n)[0][0])
                top = top_n_cap(book.root, r.sheet)
                if top is not None and item["categories"] > top:
                    item["categories"], item["top"] = top, top
            except Exception as exc:
                item["why"] = str(exc)[:90]
                out.append(item)
                continue
            for idx, dim in enumerate(r.dim_exprs):
                try:
                    inner = (f"SELECT {dim} AS c1 "
                             f"FROM {_table_for(target, dim + ' ' + r.where_sql)}"
                             f"{r.where_sql} GROUP BY 1 LIMIT {int(cap)}")
                    ln = ("MAX(LENGTH(CAST(c1 AS VARCHAR(1000))))" if target.dialect == "hyper"
                          else "max(length(toString(c1)))")
                    v = list(target.execute(f"SELECT {ln} FROM ({inner}) AS s"))[0][0]
                    vals = target.execute(f"SELECT c1 FROM ({inner}) AS s "
                                          f"ORDER BY 1 LIMIT {int(labels)}")
                    got = [str(x[0]) for x in vals if x[0] is not None]
                except Exception:
                    continue
                item["dimensions"].append({"field": dim, "position": idx,
                                        "max_length": int(v) if v is not None else None,
                                        "labels": got})
                if idx == 0:
                    item["max_label"] = int(v) if v is not None else None
                    item["labels"] = got
            if r.measure_exprs:
                try:
                    m = r.measure_exprs[0]
                    grp = (" GROUP BY " + ", ".join(r.dim_exprs)) if r.dim_exprs else ""
                    quant = DIALECTS[target.dialect]["quantile"].format(
                        q=SPREAD_QUANTILE, x="ABS(v)")
                    q = (f"SELECT MAX(ABS(v)), {quant} FROM "
                         f"(SELECT {m} AS v "
                         f"FROM {_table_for(target, m + ' ' + r.where_sql + ' ' + grp)}"
                         f"{r.where_sql}{grp} "
                         f"LIMIT {int(cap)}) AS s "
                         f"WHERE v IS NOT NULL AND ABS(v) > {DUST_FLOOR}")
                    hi, lo = list(target.execute(q))[0]
                    if hi and lo:
                        item["spread"] = round(float(hi) / float(lo), 1)
                except Exception:
                    pass
            out.append(item)
    finally:
        target.close()

    skipped = [r.sheet for r in results if r.status == "skipped"]
    return {"verdict": f"collected for {len(out)} sheets"
                       + (f", {len(skipped)} skipped (not translatable to SQL)" if skipped else ""),
            "sheets": out, "skipped": skipped}


def dead_dimensions(path: str, db: str = "", table: str = "") -> dict:
    """Dimensions with no values in the source: a dashboard filter exists with nothing to select."""
    from .lint import load
    book = load(path)
    xml = book.xml if isinstance(getattr(book, "xml", None), str) else ""
    if not xml:
        from lxml import etree as _LET
        xml = _LET.tostring(book.root, encoding="unicode")

    try:
        target = _pick_target(book, db, table)
    except Exception as exc:
        return {"verdict": f"source unavailable ({str(exc)[:120]}); not checked",
                "fields": []}

    roles = {}
    for c in book.root.iter("column"):
        nm = (c.get("name") or "").strip("[]")
        if nm:
            roles[nm] = c.get("role") or ""

    shown = _user_visible_fields(book.root)

    out = []
    try:
        for col in sorted(target.columns):
            if f"[{col}]" not in xml:
                continue
            if col not in shown:
                continue
            q = f'"{col}"' if target.dialect == "hyper" else f"`{col}`"
            try:
                rows = target.execute(
                    f"SELECT COUNT(DISTINCT {q}) FROM {target.table}")
                cnt = int(list(rows)[0][0])
            except Exception as exc:
                out.append({"field": col, "verdict": "not_checked",
                            "why": str(exc)[:100]})
                continue
            role = roles.get(col, "")
            verdict = ("dead" if cnt == 0 else
                       "degenerate" if cnt == 1 and role != "measure" else
                       "constant" if cnt == 1 else "ok")
            if verdict != "ok":
                out.append({"field": col, "role": role or "?",
                            "distinct_values": cnt, "verdict": verdict})
    finally:
        target.close()

    dead = [o for o in out if o.get("verdict") == "dead"]
    degen = [o for o in out if o.get("verdict") == "degenerate"]
    const = [o for o in out if o.get("verdict") == "constant"]
    return {
        "verdict": ("OK: all displayed dimensions are populated" if not dead and not degen else
                    f"{len(dead)} dead, {len(degen)} degenerate"),
        "dead": dead, "degenerate": degen, "constant_metrics": const,
        "why_it_matters": "an empty filter is visible to the reader and makes the workbook look unfinished",
    }


def assert_data_arrives(path: str, db: str = "", table: str = "", strict: bool = False) -> list[SheetResult]:
    """End-of-builder check: prints the report, fails on empty sheets."""
    res = dry_run(path, db, table)
    print(format_report(res))
    empty = [r for r in res if r.status == "empty"]
    errors = [r for r in res if r.status == "error"]
    if empty or (strict and errors):
        raise SystemExit(f"DRY RUN: {len(empty)} empty sheets, {len(errors)} errors; "
                         f"do not hand the workbook over")
    return res


SPREAD_LIMIT = 1_000.0
DUST_FLOOR = 1e-6
SPREAD_QUANTILE = 0.05
CELL_PADDING_PX = 12.0
LABEL_RATIO = 3.0


def truncate_to_px(text: str, px: float, pt: float, family: str) -> str:
    """How Tableau truncates a label to a width: visible part plus ellipsis, measured with the real font."""
    from . import layoutmodel as LM
    if LM.text_width(text, pt, family) <= px:
        return text
    ell = LM.text_width("…", pt, family)
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if LM.text_width(text[:mid], pt, family) + ell <= px:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…"


_LOOKS_DATE = re.compile(r"^\s*\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?\s*$")
_LOOKS_NUM = re.compile(r"^\s*-?\d+([.,]\d+)?\s*$")


def _is_textual(labels: list) -> bool:
    """Only text labels are truncated with an ellipsis; dates and numbers are formatted to fit."""
    vals = [str(v) for v in labels if v is not None and str(v).strip()]
    if not vals:
        return False
    typed = sum(1 for v in vals if _LOOKS_DATE.match(v) or _LOOKS_NUM.match(v))
    return typed < len(vals) * 0.5


def indistinct_after_truncation(labels: list, px: float, pt: float,
                                family: str) -> list[tuple]:
    """Label pairs that look identical after truncation."""
    if not _is_textual(labels):
        return []
    seen: dict[str, str] = {}
    clashes = []
    for full in labels:
        short = truncate_to_px(str(full), px, pt, family)
        if short == str(full):
            continue
        prev = seen.get(short)
        if prev is not None and prev != full:
            clashes.append((prev, full, short))
        else:
            seen[short] = full
    return clashes


def _visible_columns(ws) -> int:
    """Number of columns the sheet actually draws."""
    from . import layoutmodel as LM
    n = 0
    for c in LM.shelf_fields(ws, "cols"):
        if ":Measure Names" not in c:
            n += 1
            continue
        for f in ws.iter("filter"):
            if "Measure Names" in (f.get("column") or ""):
                n += sum(1 for g in f.iter("groupfilter") if g.get("member"))
                break
    n += len(LM.shelf_fields(ws, "rows"))
    return n or 1


def _is_text_table(ws) -> bool:
    """True when the sheet is a text table (no bars)."""
    from . import layoutmodel as LM
    cls = LM.mark_class(ws) or ""
    if cls == "Text":
        return True
    if cls not in ("Automatic", ""):
        return False
    for tag in ("cols", "rows"):
        el = ws.find(f"table/{tag}")
        if el is not None and ":Measure Names" in (el.text or ""):
            return True
    return False


def visual_check(path: str, db: str = "", table: str = "",
                 stats: dict | None = None) -> dict:
    """Check the view against data: do labels fit, are small values visible."""
    import zipfile

    from . import layoutmodel as LM

    raw = stats if stats is not None else visual_stats(path, db, table)
    stats = {s["sheet"]: s for s in raw.get("sheets", [])}
    if not stats:
        return {"verdict": "stats could not be collected; view not checked",
                "findings": []}

    from . import safexml
    root = safexml.from_twbx(path)

    wsn = root.find("worksheets")
    sheets = {w.get("name"): w for w in (list(wsn) if wsn is not None else [])}

    found = []
    for dash in root.iter("dashboard"):
        model = LM.build(dash)
        for zone in model.sheets():
            st, ws = stats.get(zone.name), sheets.get(zone.name)
            if not st or ws is None:
                continue
            pt, family, _ = LM.sheet_font(ws)

            spread = st.get("spread")
            if spread and spread > SPREAD_LIMIT and not _is_text_table(ws):
                found.append({
                    "rule": "R24", "level": "warn", "sheet": zone.name,
                    "dashboard": model.name,
                    "what": f"value spread x{spread:,.0f}: small bars "
                           f"will collapse into a line at the axis",
                    "how_to_fix": "use a log scale, split into two sheets "
                                  "or filter out the outlier"})

            rows_refs = LM.shelf_fields(ws, "rows")
            cuts = st.get("dimensions") or []
            if not cuts and st.get("labels"):
                cuts = [{"position": 0, "labels": st["labels"],
                         "max_length": st.get("max_label")}]
            for cut in cuts:
                idx = cut.get("position", 0)
                ref = rows_refs[idx] if idx < len(rows_refs) else ""
                col_px = (LM.declared_width(ws, ref) if ref else 0.0) \
                    or zone.w / max(1, _visible_columns(ws))
                if col_px <= 5:
                    continue
                clashes = indistinct_after_truncation(
                    cut.get("labels") or [],
                    max(1.0, col_px - CELL_PADDING_PX), pt, family)
                where = f" (dimension {idx + 1})" if len(cuts) > 1 else ""
                if clashes:
                    a, b, short = clashes[0]
                    found.append({
                        "rule": "R27", "level": "warn", "sheet": zone.name,
                        "dashboard": model.name,
                        "what": f"after truncation to a {col_px:.0f} px column{where} labels "
                               f"become indistinguishable: '{a[:40]}' and '{b[:40]}' both "
                               f"show as '{short}'"
                               + (f" ({len(clashes)} such pairs in total)"
                                  if len(clashes) > 1 else ""),
                        "how_to_fix": "widen the column, shorten labels or "
                                      "move the distinguishing part to the start"})
                    continue
                chars = cut.get("max_length")
                if chars and chars * LM.avg_char_width(pt, family) > col_px * LABEL_RATIO:
                    found.append({
                        "rule": "R26", "level": "warn", "sheet": zone.name,
                        "dashboard": model.name,
                        "what": f"label up to {chars} characters{where} in a "
                               f"{col_px:.0f} px column: Tableau will truncate it with an ellipsis",
                        "how_to_fix": "widen the zone, shorten labels "
                                      "or rotate the table"})

    return {
        "verdict": "OK: the data view raises no issues" if not found
                   else f"{len(found)} findings",
        "findings": found,
        "sheets_checked": len(stats),
        "limits": "sheets with LOD or table calculations are not checked; "
                   "Tableau wraps and rotates labels itself, so the rules "
                   "fire only on clear overflow",
    }


def why_empty(path: str, db: str = "", table: str = "") -> dict:
    """Why a sheet is empty: broken workbook or data ending before the period."""
    from .lint import load
    book = load(path)
    results = dry_run(path, db, table)
    empty = [r for r in results if r.status == "empty"]
    if not empty:
        return {"empty_sheets": 0, "sheets": []}

    try:
        target = _pick_target(book, db, table)
    except Exception as exc:
        return {"empty_sheets": len(empty),
                "sheets": [{"sheet": r.sheet, "reason": f"source unavailable: {exc}"}
                          for r in empty]}

    out = []
    try:
        for r in empty:
            item = {"sheet": r.sheet}
            try:
                bare = r.base_sql.replace(r.where_sql, "") if r.where_sql else r.base_sql
                rows = target.execute(f"SELECT COUNT(*) FROM ({bare} LIMIT 100000) AS s")
                n = int(list(rows)[0][0])
            except Exception as exc:
                item["reason"] = f"not installed: {str(exc)[:80]}"
                out.append(item)
                continue
            if n == 0:
                item["reason"] = "no data even without filters: workbook defect"
                item["blocker"] = True
            else:
                item["reason"] = (f"{n} rows without filters: empty due to the default period; "
                                   f"the extract is probably older than the period")
                item["blocker"] = False
            out.append(item)
    finally:
        target.close()
    return {"empty_sheets": len(empty), "sheets": out,
            "blocker_count": sum(1 for x in out if x.get("blocker"))}


def _table_for(target, sql_fragment: str) -> str:
    """Which extract table to read for this query."""
    tables = getattr(target, "tables", None)
    if not tables or len(tables) < 2:
        return target.table
    best, best_hits = target.table, -1
    for name, cols in tables.items():
        hits = sum(1 for c in cols if c in sql_fragment)
        if hits > best_hits:
            best, best_hits = name, hits
    return best


def dry_run_states(path: str, param: str = "", db: str = "", table: str = "",
                   limit: int = 5) -> dict:
    """Run the workbook across all switcher values; a sheet empty everywhere is a refusal."""
    import os
    import tempfile

    from twkit import edit as ED
    from twkit import safexml

    root = safexml.from_twbx(path)
    params = [param] if param else _switch_params(root)
    if not params:
        return {"ok": True, "states": 0, "why": "the workbook has no switchers"}

    seen: dict = {}
    checked = 0
    for pname in params:
        for value in ED.parameter_members(root, pname):
            state = safexml.from_twbx(path)
            if not ED.set_parameter_value(state, pname, value):
                continue
            try:
                results = dry_run(path, db, table, limit=limit, root=state)
            except Exception as exc:
                return {"ok": False, "why": f"{pname}={value}: {str(exc)[:160]}"}
            checked += 1
            for r in results:
                cur = seen.setdefault(r.sheet, {"ok": 0, "empty": [], "other": 0})
                if r.status == "ok":
                    cur["ok"] += 1
                elif r.status == "empty":
                    cur["empty"].append(f"{pname}={value}")
                else:
                    cur["other"] += 1

    dead = sorted(s for s, v in seen.items()
                  if s != "(source)" and v["ok"] == 0 and v["empty"])
    return {"ok": not dead, "states": checked,
            "sheets": {s: {"with_data": v["ok"], "empty_in": v["empty"]}
                      for s, v in seen.items()},
            "empty_in_all_states": dead}


def _switch_params(root) -> list:
    """List parameters only; dates and ranges do not define states."""
    out = []
    for col in root.iter("column"):
        if col.get("param-domain-type") != "list":
            continue
        name = col.get("caption") or (col.get("name") or "").strip("[]")
        if name and name not in out and col.find("members") is not None:
            out.append(name)
    return out
