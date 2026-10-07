import csv
import datetime as dt
import os
import sys

import pytest
from lxml import etree

from twkit import dryrun as D
from twkit.lint import load

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

DS = "[federated.0ahyg8e1xelf3914bag3r0yukuro]"
USER_NS = "http://www.tableausoftware.com/xml/user"

ROWS = [
    ("A", "X", "2026-01-05", 100), ("A", "Y", "2026-02-05", 1),
    ("B", "X", "2026-02-10", 10), ("B", "Y", "2026-03-10", 50),
    ("C", "X", "2026-03-15", 5), ("C", "Y", "2026-04-15", 40),
    ("D", "Y", "2026-04-20", 2),
]


def _book(tmp_path, rows=ROWS):
    from twkit.book import Book
    path = tmp_path / "s.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["region", "category", "date", "sales"])
        w.writerows(rows)
    ed = Book()
    ed.set_csv_connection(str(path), fields=[
        {"name": "region", "datatype": "string", "role": "dimension", "field_type": "nominal"},
        {"name": "category", "datatype": "string", "role": "dimension", "field_type": "nominal"},
        {"name": "date", "datatype": "date", "role": "dimension", "field_type": "ordinal"},
        {"name": "sales", "datatype": "real", "role": "measure", "field_type": "quantitative"},
    ])
    ed.add_calculated_field("Region", "[region]", datatype="string")
    ed.add_calculated_field("Number", "INDEX()", datatype="integer")
    ed.add_worksheet("S")
    ed.configure_chart("S", mark_type="Bar", columns=["SUM(sales)"], rows=["region"])
    out = tmp_path / "b.twbx"
    ed.save(str(out))
    return str(out)


def _run(book, *filters, rows_ref=None, params=None, dynamic=True):
    root = load(book).root
    ws = next(w for w in root.iter("worksheet") if w.get("name") == "S")
    view = ws.find("table/view")
    for xml in filters:
        view.append(etree.fromstring(f"<r xmlns:user='{USER_NS}'>{xml}</r>")[0])
    if rows_ref:
        ws.find("table/rows").text = f"{DS}.{rows_ref}"
    if params:
        pds = etree.SubElement(root.find("datasources"), "datasource", name="Parameters")
        for name, value in params.items():
            etree.SubElement(pds, "column", name=f"[{name}]", caption=name, datatype="integer",
                             role="measure", type="quantitative", value=str(value),
                             **{"param-domain-type": "range"})
    r = next(x for x in D.dry_run(book, limit=50, sample_rows=50, root=root, dynamic=dynamic)
             if x.sheet == "S")
    assert r.status in ("ok", "empty"), f"{r.status}: {r.note}\n{r.sql}"
    return {row[0]: float(row[1]) for row in r.sample}, r


def _top(n, by="[sales]", direction="DESC", end="top", field="[none:region:nk]", ctx=""):
    return (f"<filter class='categorical' column='{DS}.{field}'{ctx}>"
            f"<groupfilter count='{n}' end='{end}' function='end' units='records'>"
            f"<groupfilter direction='{direction}' expression='{by}' function='order'>"
            f"<groupfilter function='level-members' level='{field}'/>"
            f"</groupfilter></groupfilter></filter>")


def _member(field, value, ctx=""):
    return (f"<filter class='categorical' column='{DS}.[none:{field}:nk]'{ctx}>"
            f"<groupfilter function='member' level='[none:{field}:nk]' "
            f"member='&quot;{value}&quot;'/></filter>")


def test_top_n_on_bare_column_keeps_n_rows(tmp_path):
    got, _ = _run(_book(tmp_path), _top(2))
    assert set(got) == {"A", "B"}, got


def test_top_n_depth_parameter_and_bottom(tmp_path):
    book = _book(tmp_path)
    got, _ = _run(book, _top("[Parameters].[Top N]"), params={"Top N": 3})
    assert set(got) == {"A", "B", "C"}, got
    low, _ = _run(book, _top(1, end="bottom"))
    assert set(low) == {"D"}, low
    asc, _ = _run(book, _top(1, by="SUM([sales])", direction="ASC"))
    assert set(asc) == {"D"}, asc


def test_top_n_on_calculated_dimension(tmp_path):
    root_book = _book(tmp_path)
    calc = next(c.get("name") for c in load(root_book).root.iter("column")
                if c.get("caption") == "Region")
    field = f"[none:{calc.strip('[]')}:nk]"
    got, r = _run(root_book, _top(2, field=field), rows_ref=field)
    assert set(got) == {"A", "B"}, r.sql


def test_regular_filter_cuts_top_context_filter_decides(tmp_path):
    book = _book(tmp_path)
    plain, _ = _run(book, _top(1), _member("category", "Y"))
    assert plain == {"A": 1.0}, plain
    ctx, _ = _run(book, _top(1), _member("category", "Y", ctx=" context='true'"))
    assert ctx == {"B": 50.0}, ctx


def test_date_range_filters_rows(tmp_path):
    f = (f"<filter class='quantitative' column='{DS}.[none:date:qk]' included-values='in-range'>"
         f"<min>#2026-02-01#</min><max>#2026-03-31#</max></filter>")
    got, _ = _run(_book(tmp_path), f)
    assert got == {"A": 1.0, "B": 60.0, "C": 5.0}, got


def test_measure_range_after_aggregation_none_per_row(tmp_path):
    book = _book(tmp_path)
    agg = (f"<filter class='quantitative' column='{DS}.[sum:sales:qk]' "
           f"included-values='in-range'><min>50</min></filter>")
    got, _ = _run(book, agg)
    assert got == {"A": 101.0, "B": 60.0}, got
    row = (f"<filter class='quantitative' column='{DS}.[none:sales:qk]' "
           f"included-values='in-range'><min>40</min></filter>")
    got, _ = _run(book, row)
    assert got == {"A": 100.0, "B": 50.0, "C": 40.0}, got
    every, _ = _run(book, row.replace("in-range", "all"))
    assert len(every) == 4, every


def test_measure_filter_before_table_calc(tmp_path):
    book = _book(tmp_path)
    calc = next(c.get("name") for c in load(book).root.iter("column")
                if c.get("caption") == "Number").strip("[]")
    ref = f"[usr:{calc}:qk]"
    root = load(book).root
    ws = next(w for w in root.iter("worksheet") if w.get("name") == "S")
    ws.find("table/cols").text = f"{DS}.[sum:sales:qk] + {DS}.{ref}"
    etree.SubElement(ws.find("table/view"), "column-instance", column=f"[{calc}]",
                     derivation="User", name=ref, pivot="key", type="quantitative")
    ws.find(f"table/view/column-instance[@name='{ref}']").append(
        etree.Element("table-calc", {"ordering-type": "Columns"}))
    ws.find("table/view").append(etree.fromstring(
        f"<filter class='quantitative' column='{DS}.[sum:sales:qk]' "
        f"included-values='in-range'><max>60</max></filter>"))
    r = next(x for x in D.dry_run(book, limit=50, sample_rows=50, root=root, dynamic=True)
             if x.sheet == "S")
    assert r.status == "ok", f"{r.status}: {r.note}"
    got = {row[-3]: row[-1] for row in r.sample}
    assert got == {"B": "1", "C": "2", "D": "3"}, (r.sample, r.sql)


def test_range_on_table_calculation_not_translated():
    tr = D.Translator({"Rank": "INDEX()"}, {}, {}, {"sales"}, dialect="hyper")
    tr.allow_tc = True
    fl = etree.fromstring("<filter class='quantitative' column='[ds].[usr:Rank:qk:10]' "
                          "included-values='in-range'><min>1</min><max>5</max></filter>")
    assert D._range_filter(fl, "usr", "Rank", tr) == ("", "")


def _rel(first, last, period="month", extra=""):
    return (f"<filter class='relative-date' column='{DS}.[none:date:qk]' first-period='{first}' "
            f"include-future='true' include-null='false' last-period='{last}' "
            f"period-type-v2='{period}'{extra}/>")


def test_relative_date_from_frozen_today(tmp_path, monkeypatch):
    monkeypatch.setitem(D.DIALECTS["hyper"], "today", "DATE '2026-04-20'")
    monkeypatch.setitem(D.DIALECTS["hyper"], "now", "TIMESTAMP '2026-04-20 12:00:00'")
    got, _ = _run(_book(tmp_path), _rel(-1, 0))
    assert got == {"B": 50.0, "C": 45.0, "D": 2.0}, got


def test_relative_date_from_book_anchor(tmp_path):
    got, _ = _run(_book(tmp_path), _rel(0, 0, extra=" period-anchor='#2026-01-15#'"))
    assert got == {"A": 100.0}, got


def test_old_snapshot_without_dynamic_not_empty(tmp_path, monkeypatch):
    monkeypatch.setitem(D.DIALECTS["hyper"], "today", "DATE '2026-10-04'")
    monkeypatch.setitem(D.DIALECTS["hyper"], "now", "TIMESTAMP '2026-10-04 12:00:00'")
    book = _book(tmp_path)
    live, r = _run(book, _rel(-1, 0))
    assert live == {} and r.status == "empty", live
    snap, _ = _run(book, _rel(-1, 0), dynamic=False)
    assert snap == {"B": 50.0, "C": 45.0, "D": 2.0}, snap


def test_relative_date_window():
    a = dt.datetime(2026, 10, 4, 15, 30)
    assert D.relative_window(a, "month", -5, 0) == (dt.datetime(2026, 5, 1), dt.datetime(2026, 11, 1))
    assert D.relative_window(a, "year", -1, -1) == (dt.datetime(2025, 1, 1), dt.datetime(2026, 1, 1))
    assert D.relative_window(a, "quarter", 0, 0) == (dt.datetime(2026, 10, 1), dt.datetime(2027, 1, 1))
    assert D.relative_window(a, "week", 0, 0)[0] == dt.datetime(2026, 10, 4)
    assert D.relative_window(a, "iso-week", 0, 0)[0] == dt.datetime(2026, 9, 28)
    assert D.relative_window(a, "day", -1, -1) == (dt.datetime(2026, 10, 3), dt.datetime(2026, 10, 4))
    assert D.relative_window(a, "year", 0, 0, include_future=False)[1] == dt.datetime(2026, 10, 5)
    assert D.relative_window(a, "iso-year", 0, 0) is None


def test_calendar_month_year_number_and_day(tmp_path):
    f = (f"<filter class='categorical' column='{DS}.[my:date:ok]'>"
         f"<groupfilter function='member' level='[my:date:ok]' member='202603'/></filter>")
    got, r = _run(_book(tmp_path), f)
    assert got == {"B": 50.0, "C": 5.0}, r.sql
    days, r = _run(_book(tmp_path), f, rows_ref="[day:date:ok]")
    assert days == {"10": 50.0, "15": 5.0}, r.sql


def test_date_minus_date_plus_number_is_not_date_shift():
    dc = {'"d"'}
    diff = "(CAST(DATE '2026-09-30' AS DATE) - CAST(DATE '2026-07-01' AS DATE)) + 1"
    assert D.date_plus(diff, dc) == diff
    assert not D._is_date_operand("(CAST(a AS DATE) - CAST(b AS DATE))", dc)
    assert D._is_date_operand("(DATE '2026-01-01' + 3 * INTERVAL '1 day')", dc)
    assert D.date_plus('("d" - 1) + 2', dc) == "(\"d\" - (1) * INTERVAL '1 day') + (2) * INTERVAL '1 day'"


def test_delta_vs_prior_computed_in_hyper(tmp_path):
    from twkit import blocks as B
    from twkit.extract import build_hyper_from_csv

    class _Rec:
        def __init__(self):
            self.calcs = {}

        def add_calculated_field(self, name, formula, **kw):
            self.calcs[name] = formula

    rec = _Rec()
    prior, delta = B.delta_vs_prior(rec, "Δ", "sales", "date", param_from="p_from", param_to="p_to")
    rows = [("A", "X", "2026-03-30", 7), ("A", "X", "2026-04-02", 10),
            ("A", "X", "2026-08-01", 30)]
    path = tmp_path / "d.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("region", "category", "date", "sales")] + rows)
    hyper = str(tmp_path / "d.hyper")
    build_hyper_from_csv(str(path), hyper)
    t = D._HyperTarget(hyper)
    try:
        if "date" not in t.date_cols:
            pytest.skip("the CSV build did not detect the date")
        tr = D.Translator(rec.calcs, {}, {"p_from": "#2026-07-01#", "p_to": "#2026-09-30#"},
                          t.columns, dialect="hyper")
        tr.date_cols = t.date_cols
        sql, why = tr.to_sql(f"[{delta}]")
        assert not why, why
        (val,), = t.execute(f"SELECT {sql} FROM {t.table}")
        assert abs(float(val) - 2.0) < 1e-9, sql
    finally:
        t.close()
