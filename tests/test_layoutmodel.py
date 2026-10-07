import os
import zipfile
import xml.etree.ElementTree as ET

import pytest

from twkit import layoutmodel as LM
from _userdata import FIXTURES, CORPUS  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OURS = os.path.join(FIXTURES, "Self Service.twbx")


def _dash(path, idx=0):
    with zipfile.ZipFile(path) as z:
        twb = [n for n in z.namelist() if n.endswith(".twb")][0]
        root = ET.fromstring(z.read(twb))
    return list(root.iter("dashboard"))[idx]


def test_coordinates_converted_to_pixels():
    dash = ET.fromstring(
        '<dashboard name="d"><size sizing-mode="fixed" width="1000" height="500"/>'
        '<zones><zone name="s" type-v2="worksheet" x="0" y="0" w="50000" h="100000"/>'
        '</zones></dashboard>')
    m = LM.build(dash)
    assert (m.width, m.height) == (1000, 500)
    z = m.sheets()[0]
    assert z.w == 500 and z.h == 500


def test_range_measured_by_minimum():
    dash = ET.fromstring('<dashboard name="d"><size sizing-mode="range" minwidth="800" '
                         'maxwidth="3200" minheight="600" maxheight="1900"/>'
                         '<zones/></dashboard>')
    m = LM.build(dash)
    assert (m.width, m.height) == (800, 600)


def test_without_size_typical_screen_used():
    m = LM.build(ET.fromstring('<dashboard name="d"><zones/></dashboard>'))
    assert (m.width, m.height) == LM.DEFAULT_SIZE


@pytest.mark.skipif(not os.path.exists(OURS), reason="built book not available")
def test_phone_layout_does_not_double_zones():
    m = LM.build(_dash(OURS))
    assert len(m.zones) == 37, f"zones {len(m.zones)}: phone layout included?"
    assert len(m.sheets()) == 7


def test_text_width_grows_with_size_and_length():
    a = LM.text_width("FTD", 9)
    b = LM.text_width("FTD count", 9)
    c = LM.text_width("FTD", 18)
    assert b > a and c > a
    assert 10 < a < 40, a


def test_unknown_font_does_not_break_measure():
    assert LM.text_width("test", 9, "No Such Font Family") > 0


def test_layout_containers_not_sheets():
    dash = ET.fromstring(
        '<dashboard name="d"><size sizing-mode="fixed" width="1000" height="500"/><zones>'
        '<zone type-v2="layout-basic" x="0" y="0" w="100000" h="100000"/>'
        '<zone type-v2="layout-flow" param="horz" x="0" y="0" w="100000" h="10000"/>'
        '<zone name="s" type-v2="worksheet" x="0" y="0" w="50000" h="50000"/>'
        '<zone name="f" type-v2="filter" x="0" y="0" w="10000" h="5000"/>'
        '</zones></dashboard>')
    m = LM.build(dash)
    assert [z.name for z in m.sheets()] == ["s"]
    assert len(m.controls()) == 1


def test_r22_flags_collapsed_sheet():
    from twkit import lint
    xml = ('<?xml version=\'1.0\' encoding=\'utf-8\' ?>\n\n<workbook>'
           '<datasources/><worksheets><worksheet name="s"><table>'
           '<view><datasource-dependencies><column name="[m]" caption="A very long caption"/>'
           '</datasource-dependencies></view>'
           '<panes><pane><mark class="Text"/></pane></panes>'
           '<cols>[ds].[none:m:nk]</cols></table></worksheet></worksheets>'
           '<dashboards><dashboard name="d">'
           '<size sizing-mode="fixed" width="1000" height="500"/>'
           '<zones><zone name="s" type-v2="worksheet" x="0" y="0" w="500" h="50000"/>'
           '</zones></dashboard></dashboards></workbook>')
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".twb", delete=False, encoding="utf-8") as f:
        f.write(xml)
        p = f.name
    try:
        found = [v for v in lint.lint(p) if v.rule == "R22"]
        assert found, "collapsed zone (5 px for a ~120 px label) not caught"
        assert found[0].severity == "warn"
    finally:
        os.unlink(p)


@pytest.mark.skipif(not os.path.exists(OURS), reason="built book not available")
def test_r22_silent_on_our_book():
    from twkit import lint
    assert not [v for v in lint.lint(OURS) if v.rule == "R22"]


def test_table_columns_via_measure_names():
    from twkit.dryrun import _visible_columns
    ws = ET.fromstring(
        '<worksheet name="t"><table><view><filter column="[ds].[:Measure Names]">'
        '<groupfilter member="&quot;[ds].[m1]&quot;"/>'
        '<groupfilter member="&quot;[ds].[m2]&quot;"/>'
        '<groupfilter member="&quot;[ds].[m3]&quot;"/></filter></view>'
        '<rows>[ds].[none:dim:nk]</rows><cols>[ds].[:Measure Names]</cols>'
        '</table></worksheet>')
    assert _visible_columns(ws) == 4


def test_thresholds_from_corpus():
    from twkit import dryrun
    assert 100 < dryrun.SPREAD_LIMIT < 10_000, "threshold outside the measured corpus gap"
    assert dryrun.LABEL_RATIO >= 3.0


def test_spread_threshold_shared_by_check_and_sketch():
    import inspect
    from twkit import sketch
    src = inspect.getsource(sketch._draw_bars)
    assert "SPREAD_LIMIT" in src, "the sketch must take the threshold from dryrun"


def test_set_width_beats_equal_split():
    from twkit import layoutmodel as LM
    ws = ET.fromstring(
        '<worksheet name="w"><table><style><style-rule element="cell">'
        '<format attr="width" field="[ds].[none:field:nk]" value="260"/>'
        '</style-rule></style><rows>([ds].[none:field:nk])</rows></table></worksheet>')
    assert LM.declared_width(ws, "([ds].[none:field:nk])") == 260.0
    assert LM.declared_width(ws, "[ds].[none:other:nk]") == 0.0


def test_without_source_view_not_declared_checked(tmp_path):
    from twkit import dryrun
    twb = tmp_path / "p.twb"
    twb.write_text("<workbook><datasources/><worksheets/></workbook>", encoding="utf-8")
    assert "not checked" in dryrun.visual_check(str(twb))["verdict"]


def test_clipping_measured_by_font_not_char_count():
    from twkit.dryrun import truncate_to_px
    assert truncate_to_px("short", 500, 9, "Arial") == "short"
    cut = truncate_to_px("a very long category label text", 60, 9, "Arial")
    assert cut.endswith("…") and len(cut) < 31


def test_r27_flags_merged_labels():
    from twkit.dryrun import indistinct_after_truncation
    labels = ["Affiliates [LM] Atas, Jemshit B", "Affiliates [LM] Atas, Jemshit B, CS"]
    assert indistinct_after_truncation(labels, 65, 9, "Arial")
    assert not indistinct_after_truncation(labels, 400, 9, "Arial")


def test_r27_silent_on_distinct_labels():
    from twkit.dryrun import indistinct_after_truncation
    assert not indistinct_after_truncation(
        ["Anton Ivanov", "Boris Petrov", "Victor Sidorov"], 60, 9, "Arial")


def test_r27_ignores_dates_and_numbers():
    from twkit.dryrun import indistinct_after_truncation
    dates = ["2026-04-01 00:00:00", "2026-04-02 00:00:00", "2026-04-03 00:00:00"]
    nums = ["1764761984", "1764761985", "1764761986"]
    assert not indistinct_after_truncation(dates, 30, 9, "Arial")
    assert not indistinct_after_truncation(nums, 30, 9, "Arial")


@pytest.mark.skipif(not os.path.exists(OURS), reason="built book not available")
def test_our_book_without_visual_defects():
    pytest.importorskip("tableauhyperapi")
    from twkit import dryrun
    assert not dryrun.visual_check(OURS)["findings"]
    assert not dryrun.dead_dimensions(OURS)["dead"]


def test_label_width_in_header_not_cell():
    from twkit import layoutmodel as LM
    ws = ET.fromstring(
        '<worksheet name="w"><table><style>'
        '<style-rule element="cell">'
        '<format attr="width" field="[ds].[:Measure Names]" value="103"/></style-rule>'
        '<style-rule element="header">'
        '<format attr="width" field="[ds].[none:label:nk]" value="260"/></style-rule>'
        '</style><rows>[ds].[none:label:nk]</rows></table></worksheet>')
    assert LM.declared_width(ws, "[ds].[none:label:nk]") == 260.0


def test_all_dimensions_checked():
    from twkit.dryrun import indistinct_after_truncation
    first = ["2026-07-01", "2026-08-01"]
    second = ["Affiliates_Randy A, CS", "Affiliates_Randy A, FA"]
    assert not indistinct_after_truncation(first, 96, 9, "Arial")
    assert indistinct_after_truncation(second, 96, 9, "Arial")
    assert not indistinct_after_truncation(second, 260, 9, "Arial")


def test_unchecked_not_reported_as_fine():
    from twkit import preflight as PF
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".twb", delete=False,
                                     encoding="utf-8") as f:
        f.write("<?xml version='1.0' encoding='utf-8' ?>\n\n"
                "<workbook><datasources/><worksheets/><dashboards/></workbook>")
        p = f.name
    try:
        r = PF.preflight(p)
        assert r["verdict"].startswith("NOT fully checked")
        assert r["not_checked"], "coverage gaps not listed"
        assert r.get("image"), "screenshot decision not stated"
        assert "no screenshot needed" not in r["image"], (
            "a book without data and pages cannot be declared seen")
    finally:
        os.unlink(p)


def test_missing_file_is_refusal():
    from twkit import preflight as PF
    assert PF.preflight("/no/such/book.twbx")["verdict"] == "DO NOT hand over"


def test_check_survives_neighbour_failure(monkeypatch):
    from twkit import lint, preflight as PF
    monkeypatch.setattr(lint, "lint", lambda *a, **k: 1 / 0)
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".twb", delete=False,
                                     encoding="utf-8") as f:
        f.write("<workbook><datasources/><worksheets/></workbook>")
        p = f.name
    try:
        r = PF.preflight(p)
        assert "not run" in r["channels"]["format"]
        assert "metrics" in r["channels"]
    finally:
        os.unlink(p)


@pytest.mark.skipif(not os.path.exists(OURS), reason="built book not available")
def test_empty_by_period_does_not_block():
    pytest.importorskip("tableauhyperapi")
    from twkit import dryrun
    src = os.path.join(CORPUS, "Self Service.twbx")
    if not os.path.exists(src):
        pytest.skip("owner book not available")
    w = dryrun.why_empty(src)
    assert w["empty_sheets"] > 0
    assert w["blocker_count"] == 0, w["sheets"][:2]


def test_parameters_counted_unique_not_occurrences():
    from twkit import stylescore
    import tempfile
    xml = ('<workbook><datasources><datasource>'
           '<column name="[P1]" param-domain-type="list"/>'
           '<column name="[P2]" param-domain-type="range"/></datasource>'
           '<datasource name="x"><datasource-dependencies>'
           '<column name="[P1]" param-domain-type="list"/>'
           '<column name="[P1]" param-domain-type="list"/>'
           '<column name="[P2]" param-domain-type="range"/>'
           '</datasource-dependencies></datasource></datasources>'
           '<worksheets/><dashboards/></workbook>')
    with tempfile.NamedTemporaryFile("w", suffix=".twb", delete=False,
                                     encoding="utf-8") as f:
        f.write(xml)
        p = f.name
    try:
        assert stylescore.measure(p)["params_per_book"] == 2.0
    finally:
        os.unlink(p)


def test_profiles_are_medians_consistent_with_measurer():
    from twkit import stylescore
    assert stylescore.PROFILES["house"]["params_per_book"] == 7
    assert all(prof["reflines_per_dashboard"] == 0.0
               for name, prof in stylescore.PROFILES.items() if name != "vendor")


def test_outlier_differs_from_missed_target():
    from twkit.stylescore import Metric, OUTLIER
    lo, _ = OUTLIER["params_per_book"]
    normal = Metric("params_per_book", lo + 1, 4, None, "")
    outlier = Metric("params_per_book", lo - 1, 4, None, "")
    assert normal.verdict == "stricter than target"
    assert outlier.verdict == "worse than almost all workbooks"


@pytest.mark.skipif(not os.path.exists(OURS), reason="built book not available")
def test_port_style_equals_original():
    from twkit import stylescore
    src = os.path.join(CORPUS, "Self Service.twbx")
    if not os.path.exists(src):
        pytest.skip("owner book not available")
    ours = stylescore.score_vs_corpus(OURS)
    theirs = stylescore.score_vs_corpus(src)
    assert ours["against_target"] == theirs["against_target"]
    assert not ours["worse than almost all workbooks"]
