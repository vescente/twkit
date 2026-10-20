"""edit_hover_measure_tooltip: the tooltip of a Measure Names table follows the hovered measure."""
import pytest

import _matrix_book as M
from twkit import dash as DASH
from twkit import edit as ED
from twkit import lint as L
from twkit.book import Book


@pytest.fixture()
def book(tmp_path):
    b = Book.open(M.build(str(tmp_path)))
    ED.viz_in_tooltip(b.root, "Bars", "Table")
    return b


def test_measure_formats_become_decimals_kind_and_prefix():
    f = DASH._measure_format
    assert f('c"€ "#,##0.0;"€ "-#,##0.0') == "1n€ "
    assert f("p0.0%") == "1p"
    assert f("N") == "0n"
    assert f("") == "0n"
    assert f('c"€ "#,##0.00;"€ "-#,##0.00') == "2n€ "


def test_tooltip_sheet_shows_one_measure_picked_by_a_hover_parameter(book, tmp_path):
    res = DASH.hover_measure_tooltip(book, "Overview", "Bars", "Table")
    assert res["ok"] and res["measures"] == 1 and len(res["skipped"]) == 2, res
    tip = book.sheet("Table")
    assert "[:Measure Names]" not in (tip.findtext("table/rows") or "")
    assert not [e for e in tip.iter("text") if (e.get("column") or "").endswith("[Multiple Values]")]
    assert [e for e in tip.iter("text") if ":nk]" in (e.get("column") or "")]
    act = next(book.root.iter("edit-parameter-action"))
    assert act.find("activation").get("type") == "on-hover"
    src = next(p.get("value") for p in act.iter("param") if p.get("name") == "source-field")
    assert src.endswith("[:Measure Names]")
    formulas = [c.find("calculation").get("formula") for c in book.datasource.findall("column")
                if (c.get("caption") or "").startswith("Hover ")]
    assert len(formulas) == 5 and not any("REGEXP" in f for f in formulas)
    out = book.save(str(tmp_path / "hover.twbx"))
    assert not [v for v in L.lint(out) if v.severity == "error"]


def test_second_run_is_refused(book):
    DASH.hover_measure_tooltip(book, "Overview", "Bars", "Table")
    with pytest.raises(ValueError, match="already exists"):
        DASH.hover_measure_tooltip(book, "Overview", "Bars", "Table")


def test_needs_the_viz_in_tooltip_first(tmp_path):
    b = Book.open(M.build(str(tmp_path)))
    with pytest.raises(ValueError, match="edit_viz_in_tooltip"):
        DASH.hover_measure_tooltip(b, "Overview", "Bars", "Table")
