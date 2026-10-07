import pytest

from twkit.dryrun import (Translator, concat_plus, guard_division,
                          is_table_calc_ref, _rewrite_call, _unescape_ref)


def tr(dialect="hyper"):
    return Translator({}, {}, {}, {"a", "b", "d"}, dialect=dialect)


@pytest.mark.parametrize("formula,expect", [
    ("TODAY()", "CURRENT_DATE"),
    ("IIF([a] > 0, 1, 0)", "CASE WHEN a > 0 THEN 1 ELSE 0 END"),
    ("IIF([a] > 0, 1)", "CASE WHEN a > 0 THEN 1 END"),
    ("INT(AVG([a]))", "CAST(AVG(a) AS INTEGER)"),
    ("FLOAT([a])", "CAST(a AS DOUBLE PRECISION)"),
    ("ISNULL(SUM([a]))", "(SUM(a) IS NULL)"),
    ("ATTR([a])", "MIN(a)"),
    ("STR(SUM([a]))", "(CASE WHEN STRPOS(CAST(SUM(a) AS TEXT), '.') > 0 THEN "
     "RTRIM(RTRIM(CAST(SUM(a) AS TEXT), '0'), '.') ELSE CAST(SUM(a) AS TEXT) END)"),
])
def test_functions_that_did_not_exist(formula, expect):
    assert tr().to_sql(formula)[0] == expect


def test_clickhouse_has_own_templates():
    assert tr("clickhouse").to_sql("INT([a])")[0] == "toInt64(a)"
    assert tr("clickhouse").to_sql("TODAY()")[0] == "today()"


@pytest.mark.parametrize("sql,expect", [
    ("SUM(a)/SUM(b)", "SUM(a)/NULLIF(SUM(b), 0)"),
    ("a / (b + c)", "a / NULLIF((b + c), 0)"),
    ("SUM(a)/NULLIF(SUM(b),0)", "SUM(a)/NULLIF(SUM(b),0)"),
    ("'ppc/cpa' + a/b", "'ppc/cpa' + a/NULLIF(b, 0)"),
])
def test_division_by_zero_gives_null(sql, expect):
    assert guard_division(sql) == expect


@pytest.mark.parametrize("sql,expect", [
    ("CAST(a AS TEXT) + b", "CAST(a AS TEXT) || b"),
    ("'W ' + x", "'W ' || x"),
    ("a + 'b'", "a || 'b'"),
    ("(CASE WHEN a<0 THEN '-' ELSE '' END) + (CASE WHEN b THEN 'x' END)",
     "(CASE WHEN a<0 THEN '-' ELSE '' END) || (CASE WHEN b THEN 'x' END)"),
    ("SUM(a) + SUM(b)", "SUM(a) + SUM(b)"),
    ("COALESCE(COUNT(DISTINCT CASE WHEN m = 'A' THEN u END), 0) + COALESCE(SUM(x), 0)",
     "COALESCE(COUNT(DISTINCT CASE WHEN m = 'A' THEN u END), 0) + COALESCE(SUM(x), 0)"),
    ("(CASE WHEN m='A' THEN 1 ELSE 0 END) + 5", "(CASE WHEN m='A' THEN 1 ELSE 0 END) + 5"),
    ("DATE '2026-01-01' + 3 * INTERVAL '1 day'",
     "DATE '2026-01-01' + 3 * INTERVAL '1 day'"),
])
def test_string_concat_detected_by_operands(sql, expect):
    assert concat_plus(sql) == expect


@pytest.mark.parametrize("ref,expect", [
    ("[rank:sum:GGR:qk]", True),
    ("[pcto:usr:FTD count (copy)_1:qk]", True),
    ("[win:avg:Score:qk]", True),
    ("[sum:GGR:qk]", False),
    ("[none:User ID:ok]", False),
    ("[usr:Calculation_1:qk]", False),
])
def test_nested_reference_is_table_calculation(ref, expect):
    assert is_table_calc_ref(ref) is expect


def test_reference_escaping_removed():
    assert _unescape_ref(r"usr:SRC, \% (copy)_5176:qk") == "usr:SRC, % (copy)_5176:qk"


def test_call_rewriter_respects_word_boundary():
    got = _rewrite_call("SUBSTR(x,1,2)", "STR", lambda a: "CAST(" + a[0] + " AS TEXT)")

    assert got == "SUBSTR(x,1,2)"


def test_untranslatable_checked_after_folding():
    t = Translator({}, {}, {"p": "'b'"}, {"a"}, dialect="hyper")

    sql, why = t.to_sql("CASE [Parameters].[p] WHEN 'a' THEN DATENAME('month',[a]) "
                        "WHEN 'b' THEN [a] END")

    assert not why
    assert "DATENAME" not in sql.upper()
