import csv
import os
import sys

import pytest

from twkit import dryrun
from twkit.extract import build_hyper_from_csv

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

ROWS = [
    ("Sales", "Germany", "2026-01-01", "GGR",     "100.5"),
    ("Sales", "Germany", "2026-01-02", "GGR",     "200.25"),
    ("Sales", "Poland",   "2026-01-01", "GGR",     "50"),
    ("Sales", "Poland",   "2026-01-02", "GGR",     "75.75"),
]


def _write_csv(path, rows=ROWS):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sheet", "dim_1", "date", "measure", "value"])
        w.writerows(rows)
    return path


def _book_on_csv(tmp_path, csv_path, filters=None, mark="Bar", out_name="csv_book.twbx"):
    from twkit.book import Book
    ed = Book()
    ed.set_csv_connection(str(csv_path), fields=[
        {"name": "sheet", "datatype": "string", "role": "dimension", "field_type": "nominal"},
        {"name": "dim_1", "datatype": "string", "role": "dimension", "field_type": "nominal"},
        {"name": "date", "datatype": "date", "role": "dimension", "field_type": "ordinal"},
        {"name": "measure", "datatype": "string", "role": "dimension", "field_type": "nominal"},
        {"name": "value", "datatype": "real", "role": "measure", "field_type": "quantitative"},
    ])
    ed.add_calculated_field("Value", "SUM([value])", datatype="real")
    ed.add_worksheet("Countries")
    ed.configure_chart("Countries", mark_type=mark, columns=["Value"], rows=["dim_1"],
                       label="Value" if mark == "Text" else None,
                       filters=filters)
    ed.add_dashboard("Page", width=900, height=600, worksheet_names=["Countries"])
    out = tmp_path / out_name
    ed.save(str(out))
    return str(out)


def test_dry_run_on_csv_book(tmp_path):
    csv_path = _write_csv(tmp_path / "data.csv")
    book = _book_on_csv(tmp_path, csv_path)

    res = dryrun.dry_run(book)

    sheets = {r.sheet for r in res}
    assert "(source)" not in sheets
    assert "Countries" in sheets, sheets
    mine = next(r for r in res if r.sheet == "Countries")
    assert mine.status == "ok", f"{mine.status}: {getattr(mine, 'note', '')}"
    assert mine.rows > 0


def test_string_gap_does_not_make_measure_text(tmp_path):
    rows = list(ROWS) + [("Sales", "Czechia", "2026-01-03", "GGR", "%null%")]
    csv_path = _write_csv(tmp_path / "with_sentinel.csv", rows)

    info = build_hyper_from_csv(str(csv_path), str(tmp_path / "out.hyper"))

    assert info["types"]["value"] in ("double", "big_int"), info["types"]
    assert info["coerced"] == 0, info
    assert info["rows"] == len(rows)


def test_real_junk_in_measure_nulled_and_counted(tmp_path):
    rows = list(ROWS) + [("Sales", "Czechia", "2026-01-03", "GGR", "n/a")]
    csv_path = _write_csv(tmp_path / "with_junk.csv", rows)

    info = build_hyper_from_csv(str(csv_path), str(tmp_path / "junk.hyper"))

    assert info["types"]["value"] in ("double", "big_int"), info["types"]
    assert info["coerced"] == 1, info
    assert info["rows"] == len(rows)


def test_column_types_from_values(tmp_path):
    csv_path = _write_csv(tmp_path / "types.csv")

    info = build_hyper_from_csv(str(csv_path), str(tmp_path / "types.hyper"))

    assert info["types"]["date"] == "date", info["types"]
    assert info["types"]["dim_1"] == "text", info["types"]


def test_value_filter_reaches_sql(tmp_path):
    csv_path = _write_csv(tmp_path / "flt.csv")
    book = _book_on_csv(tmp_path, csv_path, filters=[
        {"column": "[sheet]", "values": ["Sales"]},
        {"column": "[measure]", "values": ["GGR"]},
    ])

    res = dryrun.dry_run(book, limit=1)
    mine = next(r for r in res if r.sheet == "Countries")

    assert "WHERE" in mine.where_sql, mine.where_sql
    assert "sheet IN ('Sales')" in mine.where_sql, mine.where_sql
    assert "measure IN ('GGR')" in mine.where_sql, mine.where_sql
    assert mine.status == "ok", getattr(mine, "note", "")


def test_tableau_trims_csv_edge_spaces(tmp_path):
    rows = [("Sales ", "Germany", "2026-01-01", "GGR", "10"),
            ("Sales ", "Poland", "2026-01-02", "GGR", "20")]
    csv_path = _write_csv(tmp_path / "space.csv", rows)
    for member, want in (("Sales ", "empty"), ("Sales", "ok")):
        book = _book_on_csv(tmp_path, csv_path,
                            filters=[{"column": "[sheet]", "values": [member]}])
        mine = next(r for r in dryrun.dry_run(book, limit=1) if r.sheet == "Countries")
        assert mine.status == want, f"{member!r}: {mine.status} / {mine.where_sql}"


def test_top_n_translated_as_subquery(tmp_path):
    rows = [("Sales", f"Country {i}", "2026-01-01", "GGR", str(10 ** i))
            for i in range(6)]
    csv_path = _write_csv(tmp_path / "topn.csv", rows)
    book = _book_on_csv(tmp_path, csv_path, filters=[
        {"column": "[sheet]", "values": ["Sales"]},
        {"column": "dim_1", "top": 2, "by": "Value", "direction": "DESC"},
    ])

    mine = next(r for r in dryrun.dry_run(book, limit=50) if r.sheet == "Countries")

    assert "sheet IN ('Sales')" in mine.where_sql, mine.where_sql
    assert "dim_1 IN (SELECT" in mine.where_sql, mine.where_sql
    assert "LIMIT 2" in mine.where_sql, mine.where_sql
    assert mine.rows == 2


def test_r24_silent_on_text_mark(tmp_path):
    rows = [("Sales", f"Country {i}", "2026-01-01", "GGR", str(10 ** i))
            for i in range(7)]
    csv_path = _write_csv(tmp_path / "wide.csv", rows)

    bar = _book_on_csv(tmp_path, csv_path, mark="Bar", out_name="bar.twbx",
                       filters=[{"column": "[measure]", "values": ["GGR"]}])
    txt = _book_on_csv(tmp_path, csv_path, mark="Text", out_name="text.twbx",
                       filters=[{"column": "[measure]", "values": ["GGR"]}])

    bar_hits = [f for f in dryrun.visual_check(bar).get("findings", [])
                if f["rule"] == "R24"]
    txt_hits = [f for f in dryrun.visual_check(txt).get("findings", [])
                if f["rule"] == "R24"]

    assert bar_hits
    assert not txt_hits


def test_packaged_csv_is_the_one_the_connection_names():
    from types import SimpleNamespace
    from lxml import etree
    from twkit import dryrun as DR
    root = etree.fromstring("<workbook><connection class='textscan' filename='sales_doubled.csv'/></workbook>")
    book = SimpleNamespace(archive=["Data/sales.csv", "Data/sales_doubled.csv"], root=root)
    assert DR._packaged_csv(book) == "Data/sales_doubled.csv"
    assert DR._packaged_csv(SimpleNamespace(archive=["a.csv"], root=etree.fromstring("<workbook/>"))) == "a.csv"
