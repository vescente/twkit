import pytest

from twkit import tablecalc as T

hp = pytest.importorskip("tableauhyperapi")


def _run(measures, part=(), order=("_d0",)):
    aggs, w, outs = [], [], []
    for m in measures:
        outs.append(T.compile_measure(T.split_aggregates(m, aggs), list(part), list(order), aggs, w))
    inner = ("SELECT g AS _d0, " + ", ".join(f"{a} AS _a{i}" for i, a in enumerate(aggs)) +
             " FROM (VALUES ('a', 1.0), ('b', 5.0), ('c', 3.0), ('c', 1.0)) AS v(g, x) GROUP BY 1")
    q = T.build_query(inner, ["_d0"], outs, w)
    with hp.HyperProcess(hp.Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as p, \
            hp.Connection(p.endpoint) as c:
        conv = lambda v: float(v) if v is not None and not isinstance(v, (bool, int)) else v
        return {r[0]: tuple(conv(v) for v in r[1:]) for r in c.execute_list_query(q)}


def test_nested_window_is_layered():
    r = _run(["SUM(x) / TOTAL(SUM(x)) = WINDOW_MAX(SUM(x) / TOTAL(SUM(x)))"])
    assert r == {"a": (False,), "b": (True,), "c": (False,)}


def test_rank_lookup_running_index_size():
    r = _run(["RANK(SUM(x))", "LOOKUP(SUM(x), -1)", "RUNNING_SUM(SUM(x))", "INDEX()", "SIZE()"])
    assert r["a"] == (3, None, 1.0, 1, 3)
    assert r["b"] == (1, 1.0, 6.0, 2, 3)
    assert r["c"] == (2, 5.0, 10.0, 3, 3)


def test_total_of_avg_reaggregates_rows():
    r = _run(["TOTAL(AVG(x))"])
    assert abs(r["a"][0] - 2.5) < 1e-9


def test_lod_subquery_is_atom():
    aggs = []
    e = T.split_aggregates("SUM(x) / (SELECT SUM(x) FROM t AS _lod1)", aggs)
    assert aggs == ["SUM(x)"] and "(SELECT SUM(x) FROM t AS _lod1)" in e


def test_tag_calls_marks_table_functions_only():
    f = "RANK([Score]) + INDEX() + [Unemployment, total (% of x)] + LOOKUP(__tc9__, [a], -1)"
    t = T.tag_calls(f, "__tc1__")
    assert "RANK(__tc1__, [Score])" in t and "INDEX(__tc1__)" in t
    assert "[Unemployment, total (% of x)]" in t
    assert "LOOKUP(__tc9__, [a], -1)" in t


def test_tagged_call_uses_its_own_direction():
    aggs, w = [], []
    sql = T.compile_measure(T.split_aggregates("RANK(__tc1__, SUM(x))", aggs), [], ["_d0"],
                            aggs, w, {"__tc1__": (["_d1"], ["_d0 ASC"])})
    assert sql == "_w0" and "PARTITION BY _d1" in w[0][1]
