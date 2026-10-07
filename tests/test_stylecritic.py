import os

import pytest

from twkit import safexml
from twkit import stylecritic as S

LABEL10_CELL12 = {"label_pt": 10.0, "cell_pt": 12.0, "title_pt": 15.0}


def _col(nat, have, n=10, num=0, cells=(), head=None, fs=11.0):
    c = {"n": n, "num": num, "nat": nat, "fs": fs, "have": have, "cells": [list(x) for x in cells]}
    if head:
        c["head"] = {"text": head[0], "need": head[1], "fs": fs, "have": have}
    return c


def _zone(name="Sheet", form="table", fit="standard", box=(0, 0, 400, 300), tables=(), **kw):
    z = {"id": kw.pop("id", "1"), "name": name, "kind": "", "form": form, "fit": fit,
         "box": list(box), "sheet": kw.pop("sheet", True), "text": kw.pop("text", False),
         "floating": kw.pop("floating", False), "tables": list(tables), "lbls": [],
         "ink": {}, "marks": {}, "swatches": [], "bars": None, "content": None, "empty": ""}
    z.update(kw)
    return z


def _table(cols, nbody=10, first=30, rowh=20):
    return {"box": [0, 0, 0, 0], "cols": cols, "nbody": nbody, "first": first,
            "last": first + nbody * rowh, "rowh": rowh}


def _codes(found, level=None):
    return [f["code"] for f in found if level is None or f["level"] == level]


def _root(xml: str):
    return safexml.from_bytes(xml.encode("utf-8"))


def test_overflowing_table_squeezes_headers_and_clips_values():
    nums = [_col(60, 70, num=10, head=("GGR €", 40)) for _ in range(9)]
    prov = _col(105, 70, cells=[("endorphina", 62), ("pragmaticexternal", 105), ("redgenn", 45)],
                head=("Provider", 53))
    z = _zone(box=(0, 0, 800, 450), tables=[_table([prov] + nums, nbody=20)])
    found = S.judge_table("p", z, z["tables"][0], LABEL10_CELL12)
    assert "K5" in _codes(found, "warn"), found
    k2 = [f for f in found if f["code"] == "K2"]
    assert k2 and k2[0]["level"] == "error" and "squeezed" in k2[0]["what"], found
    assert "pragmat" in k2[0]["evidence"] and "redgenn" not in k2[0]["evidence"]


def test_table_fits_by_content_values_intact():
    pid = _col(128, 90, cells=[("brandname- 1080129", 128)], head=("Player ID + Casino", 101))
    cat = _col(42, 90, head=("FavoriteCategoryName", 140))
    nums = [_col(50, 90, num=10, head=("NGR €", 40)) for _ in range(6)]
    z = _zone(box=(0, 0, 1500, 400), tables=[_table([pid, cat] + nums)])
    found = S.judge_table("p", z, z["tables"][0], LABEL10_CELL12)
    assert not _codes(found, "error"), found
    k3 = [f for f in found if f["code"] == "K3"]
    assert k3 and "Favorite" in k3[0]["evidence"]


def test_header_that_wraps_into_two_lines_is_not_clipped():
    act = _col(60, 83, head=("Activity Type", 76), fs=11.0)
    nums = [_col(40, 50, num=10, head=("May-26", 39)) for _ in range(4)]
    z = _zone(box=(0, 0, 600, 300), tables=[_table([act] + nums)])
    found = S.judge_table("p", z, z["tables"][0], LABEL10_CELL12)
    assert not [f for f in found if f["code"] == "K3"], found






def test_over_width_cap_single_long_labels_warn_merged_error():
    long_ = ("Coin Win Express: Hold The Spin", 190)
    one = _col(190, 300, cells=[long_], head=("Favorite Game", 80))
    z = _zone(box=(0, 0, 900, 300), tables=[_table([one, _col(40, 300, num=10)])])
    found = S.judge_table("p", z, z["tables"][0], LABEL10_CELL12)
    assert [(f["code"], f["level"]) for f in found if f["code"] == "K2"] == [("K2", "warn")]

    twins = _col(190, 300, cells=[("Gates of Olympus Super Scatter", 190),
                                  ("Gates of Olympus Super Scatter 1000", 210)])
    z = _zone(box=(0, 0, 900, 300), tables=[_table([twins, _col(40, 300, num=10)])])
    found = S.judge_table("p", z, z["tables"][0], LABEL10_CELL12)
    k2 = [f for f in found if f["code"] == "K2"]
    assert k2 and k2[0]["level"] == "error" and "identical" in k2[0]["what"], found


def test_numbers_in_squeezed_table_break():
    vals = _col(60, 40, num=10, cells=[("€ 13,459K", 60)])
    z = _zone(fit="entire-view", tables=[_table([_col(30, 40), vals])])
    found = S.judge_table("p", z, z["tables"][0], LABEL10_CELL12)
    assert "K1" in _codes(found, "error"), found


def test_sheet_title_in_three_lines():
    z = _zone(title={"text": "TOP PROVIDERS TABLE TREND CHART", "need": 230, "width": 156,
                     "h": 20, "fs": 15, "px": 20, "lines": 3})
    found = S.judge_zone("p", z, LABEL10_CELL12, None)
    assert "K4" in _codes(found, "warn")


def test_scroll_for_few_rows_and_long_list():
    tb = _table([_col(40, 100, num=12)], nbody=12, rowh=20)
    z = _zone(box=(0, 0, 300, 220), tables=[tb])
    found = S.judge_zone("p", z, LABEL10_CELL12, {"overflow": {"sh": 280, "ch": 220, "sw": 300, "cw": 300}})
    assert "K6" in _codes(found, "warn")
    long_ = _table([_col(40, 100, num=300)], nbody=300, rowh=20)
    z = _zone(box=(0, 0, 300, 220), tables=[long_])
    found = S.judge_zone("p", z, LABEL10_CELL12, {"overflow": {"sh": 6000, "ch": 220, "sw": 300, "cw": 300}})
    assert "K6" not in _codes(found)


def test_squashed_rows_from_frame_measure():
    fr = {"zones": [], "squashed": [{"id": "5", "name": "Daily", "fit": "entire-view",
                                    "rows": 120, "row_px": 6.1, "font_px": 11}]}
    found = S.judge_page("p", {"zones": [], "canvas": [800, 600]}, fr, {})
    assert [(f["code"], f["level"]) for f in found] == [("P1", "error")]


def test_bars_denser_than_label_font_overlap():
    z = _zone(form="bar", bars={"n": 20, "pitch": 6.5, "fs": 11})
    assert "P2" in _codes(S.judge_zone("p", z, LABEL10_CELL12, None), "error")
    z = _zone(form="bar", bars={"n": 5, "pitch": 40, "fs": 11})
    assert "P2" not in _codes(S.judge_zone("p", z, LABEL10_CELL12, None))


def test_floating_zone_covers_sheet_labels():
    sheet = _zone(name="Bars", lbls=[{"t": "Germany", "cls": "lbl blab", "box": [10, 50, 60, 12]}])
    btn = _zone(id="9", name="", kind="dashboard-object", sheet=False, floating=True,
                content=[0, 40, 100, 30])
    found = S.judge_floating("p", [sheet, btn])
    assert _codes(found) == ["P3"]
    btn["content"] = [300, 300, 50, 20]
    assert not S.judge_floating("p", [sheet, btn])


def _drift_row(title_lines_b=1, first_b=40):
    a = _zone(name="Selected", form="mlist", box=(0, 100, 200, 300),
              tables=[_table([_col(50, 90, n=13)], nbody=13, first=140)],
              title={"text": "Selected", "need": 60, "width": 188, "h": 20, "fs": 15, "px": 20,
                     "lines": 1})
    b = _zone(id="2", name="Previous Avg", form="mlist", box=(200, 100, 90, 300),
              tables=[_table([_col(50, 80, n=13)], nbody=13, first=100 + first_b)],
              title={"text": "Previous Avg", "need": 90, "width": 78, "h": 20, "fs": 15, "px": 20,
                     "lines": title_lines_b})
    return [a, b]


def test_two_line_title_shifts_neighbour_table():
    found = S.judge_drift("p", _drift_row(title_lines_b=2))
    assert [(f["code"], f["level"]) for f in found] == [("R1", "error")], found
    assert "Previous Avg" in found[0]["what"] and "2 lines" in found[0]["evidence"]
    assert not S.judge_drift("p", _drift_row(title_lines_b=1))


def test_header_on_some_neighbours_is_drift():
    found = S.judge_drift("p", _drift_row(first_b=60))
    assert _codes(found) == ["R1"]


def test_tables_with_different_row_counts_not_block():
    row = _drift_row(title_lines_b=2)
    row[1]["tables"][0]["nbody"] = 5
    assert not S.judge_drift("p", row)


def test_color_arithmetic():
    assert S.contrast("#000000", "#ffffff") == pytest.approx(21.0, rel=1e-3)
    assert S.delta_e("#4e79a7", "#4e79a7") == pytest.approx(0.0, abs=1e-6)
    assert S.delta_e("#76b7b2", "#86bcb6") < S.DE_CLOSE < S.delta_e("#4e79a7", "#f28e2b")
    assert S.achromatic("#7a7a7a") and not S.achromatic("#e15759")


def _ws(body: str = "", name: str = "Sheet"):
    return _root(f"<worksheet name='{name}'><table><view/><style>{body}</style>"
                 f"<panes><pane><encodings><color column='[ds].[none:geo:nk]'/></encodings>"
                 f"</pane></panes></table></worksheet>")


def test_many_categories_and_indistinguishable_colors():
    from twkit.style import PALETTE
    z = _zone(form="bar", marks={c: 1 for c in PALETTE[:14]}, swatches=PALETTE[:14])
    found = S.judge_colors("p", z, _ws())
    assert "C1" in _codes(found, "warn")
    assert "C2" in _codes(found, "warn")
    z = _zone(form="bar", marks={c: 1 for c in PALETTE[:6]}, swatches=PALETTE[:6])
    assert not S.judge_colors("p", z, _ws())


def test_contrast_only_for_workbook_colors():
    low = _zone(sheet=False, text=True, name="", ink={"#cfcfcf|#ffffff": {"n": 1, "own": True,
                                                                          "sample": "Note"}})
    assert "C3" in _codes(S.judge_zone("p", low, LABEL10_CELL12, None), "warn")
    frame_own = _zone(form="bar", ink={"#ffffff|#ff9da7": {"n": 2, "own": True, "sample": "6"}})
    assert "C3" not in _codes(S.judge_zone("p", frame_own, LABEL10_CELL12, None))
    ws = _ws("<style-rule element='cell'><format attr='color' value='#d9d9d9'/></style-rule>")
    assert _codes(S.judge_book_ink("p", "Sheet", ws)) == ["C3"]
    ws = _ws("<style-rule element='cell'><format attr='color' value='#333333'/></style-rule>")
    assert not S.judge_book_ink("p", "Sheet", ws)


def test_off_palette_and_rainbow_by_xml():
    root = _root(
        "<workbook><datasources/><worksheets>"
        "<worksheet name='A'><table><style><style-rule element='mark'>"
        "<format attr='mark-color' value='#12ab34'/></style-rule></style></table></worksheet>"
        "<worksheet name='B'><table><style><style-rule element='mark'>"
        "<encoding attr='color' field='[ds].[sum:ggr:qk]' type='custom-interpolated'>"
        "<color-palette custom='true' type='ordered-sequential'>"
        "<color>#ff0000</color><color>#ffff00</color><color>#00ff00</color>"
        "<color>#0000ff</color></color-palette></encoding></style-rule></style></table></worksheet>"
        "<worksheet name='C'><table><style><style-rule element='mark'>"
        "<encoding attr='color' field='[ds].[sum:ngr:qk]' type='interpolated' "
        "palette='orange_blue_diverging_10_0'/></style-rule></style></table></worksheet>"
        "</worksheets></workbook>")
    sheets = S._sheets(root)
    found = S.judge_book_colors(root, sheets, {"A", "B", "C"})
    assert sorted(_codes(found)) == ["C4", "C5"], found
    assert "#12ab34" in next(f for f in found if f["code"] == "C4")["evidence"]
    assert next(f for f in found if f["code"] == "C5")["sheet"] == "B"
    assert not S.rainbow(["#9e3d22", "#e96c21", "#d4cfbd", "#5f94c1", "#2b5c8a"])


def test_empty_and_unbuilt_sheets_distinct():
    z = _zone(empty="no data")
    assert "E1" in _codes(S.judge_zone("p", z, LABEL10_CELL12, None), "warn")
    z = _zone(empty="skipped: LOD")
    assert "E1" not in _codes(S.judge_zone("p", z, LABEL10_CELL12, None))


def test_empty_strip_only_when_whole_row_empty():
    short = _zone(name="Casinos", box=(800, 0, 800, 400), content=[800, 0, 800, 90],
                  tables=[_table([_col(40, 90, num=3, fs=11)], nbody=3, first=30)])
    alone = S.judge_strips("p", [short], {})
    assert _codes(alone) == ["E2"]
    tall = _zone(id="2", name="Countries", box=(0, 0, 800, 400), content=[0, 0, 800, 330],
                 tables=[_table([_col(40, 90, num=10, fs=11)], nbody=14, first=30)])
    assert "E2" not in _codes(S.judge_strips("p", [short, tall], {}))


def test_empty_page_band():
    deep = {"canvas": [1000, 2000], "zones": [_zone(content=[0, 0, 1000, 300]),
                                              _zone(id="2", content=[0, 1200, 1000, 300])]}
    found = S.judge_bands("p", deep)
    assert _codes(found) == ["E3"] and "900 px" in found[0]["what"]
    deep["zones"][1]["content"] = [0, 320, 1000, 300]
    assert not S.judge_bands("p", deep)


def test_tiny_font_and_sheet_sizes_by_xml():
    ws = _ws("<style-rule element='label'><format attr='font-size' value='10'/></style-rule>"
             "<style-rule element='cell'><format attr='font-size' value='6'/></style-rule>")
    st = S.sheet_style(ws)
    assert (st["label_pt"], st["cell_pt"], st["title_pt"]) == (10.0, 6.0, S.TITLE_PT)
    assert S.sheet_style(None)["label_pt"] == S.TEXT_PT
    found = S.judge_fonts(None, {"Sheet": ws}, {"Sheet"})
    assert _codes(found) == ["E4"] and "6 pt" in found[0]["evidence"]


def _twb(tmp_path):
    p = tmp_path / "book.twb"
    p.write_text("<?xml version='1.0' encoding='utf-8' ?><workbook><datasources/><worksheets>"
                 "<worksheet name='T'><table><view/><style/></table></worksheet></worksheets>"
                 "<dashboards/></workbook>", encoding="utf-8")
    return str(p)


def test_without_detailed_measure_reports_not_checked(tmp_path):
    fr = {"book": "book", "data": "present", "pages": [
        {"page": "P", "zone_count": 1, "image": "", "zones": [{"id": "1", "name": "T"}],
         "clipped": [{"id": "1", "name": "T", "cut": 3, "total": 9, "samples": ["Netherlands"]}],
         "overflow": [], "squashed": []}]}
    r = S.critique(_twb(tmp_path), frame_result=fr)
    assert any("detailed measurement not run" in g for g in r["not_checked"]), r
    assert _codes(r["findings"]) == ["K0"] and r["findings"][0]["level"] == "warn"
    assert "View critic" in S.format_report(r)


def test_book_without_pages_not_clean(tmp_path):
    r = S.critique(_twb(tmp_path), frame_result={"book": "book", "data": "present", "pages": []})
    assert r["verdict"].startswith("no pages") and r["not_checked"]


def test_preflight_blocks_reading_breaks_not_taste(tmp_path, monkeypatch):
    from twkit import preflight as PF
    import twkit.canon as canon
    import twkit.csvcheck as csvcheck
    import twkit.dryrun as dryrun
    import twkit.extract as extract
    import twkit.lint as lint
    import twkit.preview as preview
    import twkit.render as render
    import twkit.stylescore as stylescore

    def boom(*a, **k):
        raise RuntimeError("stubbed in test")
    for mod, fn in ((lint, "lint"), (extract, "stale_extract_refs"), (csvcheck, "check_workbook"),
                    (canon, "check_workbook"), (dryrun, "dry_run"), (dryrun, "dry_run_states"),
                    (dryrun, "dead_dimensions"), (dryrun, "visual_stats"),
                    (dryrun, "visual_check"), (stylescore, "score"),
                    (preview, "thumbs_state"), (render, "describe")):
        monkeypatch.setattr(mod, fn, boom)
    monkeypatch.setattr(PF, "_sketch_all", boom)
    book = _twb(tmp_path)

    def verdict(level):
        f = S._f("clipped", "K2", level, "P", "Top 20 Providers", "values clipped", "", "")
        monkeypatch.setattr(S, "critique", lambda *a, **k: {
            "verdict": "x", "findings": [f], "not_checked": [], "images": []})
        return PF.preflight(book)

    r = verdict("error")
    assert any(b.startswith("view: Top 20 Providers") for b in r["blockers"]), r["blockers"]
    assert r["channels"]["critic"] == "x"
    r = verdict("warn")
    assert not any(b.startswith("view:") for b in r["blockers"]), r["blockers"]
    assert r["critic_notes"]


def test_style_width_not_squeezed_or_recomputed():
    prov = _col(105, 70, cells=[("endorphina", 62), ("pragmaticexternal", 105)], head=("Provider", 53))
    prov.update(src="xml", px=220)
    nums = [_col(60, 70, num=10, head=("GGR €", 40)) for _ in range(9)]
    z = _zone(box=(0, 0, 800, 450), tables=[_table([prov] + nums, nbody=20)])
    widths, overflow, squeezed, _ = S.column_widths([prov] + nums, LABEL10_CELL12, 788, "standard")
    assert widths[0] == 220 and not squeezed[0] and overflow
    found = S.judge_table("p", z, z["tables"][0], LABEL10_CELL12)
    assert not [f for f in found if f["code"] == "K2" and f["level"] == "error"], found


def _table_book(bands: bool, sizes=("10", "10"), delta_color: bool = True):
    from lxml import etree
    band = ("<style-rule element='pane'><format attr='band-color' scope='rows' value='#f6f1ef'/>"
            "</style-rule>") if bands else ""
    color = "<color column='[ds].[Multiple Values]'/>" if delta_color else ""
    xml = f"""<workbook><worksheets><worksheet name='t'><table>
      <view><datasource-dependencies datasource='ds'>
        <column name='[d]' caption='Δ% GGR €' datatype='real' role='measure' type='quantitative'/>
        <column-instance column='[d]' derivation='Sum' name='[sum:d:qk]' type='quantitative'/>
      </datasource-dependencies>
      <filter class='categorical' column='[ds].[:Measure Names]'>
        <groupfilter function='member' level='[:Measure Names]' member='&quot;[ds].[sum:d:qk]&quot;'/>
      </filter></view>
      <style><style-rule element='cell'><format attr='font-size' value='{sizes[0]}'/></style-rule>
        <style-rule element='header'><format attr='font-size' value='{sizes[1]}'/></style-rule>{band}</style>
      <panes><pane><mark class='Text'/><encodings><text column='[ds].[Multiple Values]'/>{color}</encodings></pane></panes>
      <rows>[ds].[none:Country:nk]</rows><cols>[ds].[:Measure Names]</cols>
    </table></worksheet></worksheets></workbook>"""
    root = etree.fromstring(xml)
    return root, {w.get("name"): w for w in root.iter("worksheet")}


def test_table_rules_typography_bands_delta_color():
    root, sheets = _table_book(bands=True)
    assert S.judge_tables(root, sheets, {"t"}) == []
    root, sheets = _table_book(bands=False, sizes=("12", "9"), delta_color=False)
    codes = {f["code"] for f in S.judge_tables(root, sheets, {"t"})}
    assert codes == {"T1", "T2", "T3"}
    assert all(f["class"] == "table" and f["level"] == S.WARN
               for f in S.judge_tables(root, sheets, {"t"}))


def test_color_key_swatch_is_not_text():
    ws = safexml.from_bytes(
        "<worksheet><layout-options><title><formatted-text>"
        "<run fontcolor='#edc948'>■ </run><run fontcolor='#555555'>Retained   </run>"
        "</formatted-text></title></layout-options><table/></worksheet>".encode())
    assert not S.judge_book_ink("p", "Sheet", ws)


def test_content_needs_from_frame_geometry(monkeypatch, tmp_path):
    page = tmp_path / "page_01.html"
    page.write_text("<html></html>")
    zones = [{"name": "T", "sheet": True, "box": [0, 100, 300, 200], "fit": "standard",
              "title": {"lines": 2},
              "tables": [{"first": 165, "last": 405, "nbody": 10, "rowh": 24,
                          "cols": [_col(80, 80), _col(120, 60, num=10)]}]},
             {"name": "Chart", "sheet": True, "box": [300, 100, 300, 200]}]
    monkeypatch.setattr(S, "deep_probe", lambda pf, opts=None: {"zones": zones})
    monkeypatch.setattr(S, "_sheets", lambda root: {"T": _ws(name="T")})
    monkeypatch.setattr(safexml, "from_twbx", lambda p: None)
    got = S.content_needs("book.twbx", frame_result={"pages": [{"file": str(page)}]})
    assert set(got) == {"T"}
    assert got["T"]["h"] == 313 and got["T"]["title_lines"] == 2 and got["T"]["rows"] == 10
    assert got["T"]["w"] > 200
    assert len(got["T"]["cols"]) == 2


def test_content_needs_cols_ignore_xml_widths(monkeypatch, tmp_path):
    page = tmp_path / "page_01.html"
    page.write_text("<html></html>")
    wide = dict(_col(80, 80), src="xml", px=300)
    zones = [{"name": "T", "sheet": True, "box": [0, 100, 600, 200], "fit": "standard",
              "tables": [{"first": 165, "nbody": 1, "rowh": 24, "cols": [wide, _col(60, 60, num=1)]}]}]
    monkeypatch.setattr(S, "deep_probe", lambda pf, opts=None: {"zones": zones})
    monkeypatch.setattr(S, "_sheets", lambda root: {"T": _ws(name="T")})
    monkeypatch.setattr(safexml, "from_twbx", lambda p: None)
    got = S.content_needs("book.twbx", frame_result={"pages": [{"file": str(page)}]})["T"]
    assert got["w"] > 300 and got["cols"][0] < 150


def test_wrap_lines_counts_greedy_lines():
    assert S.wrap_lines("", 80, 10) == 0
    assert S.wrap_lines("Bet", 80, 10) == 1
    assert S.wrap_lines("Cancelled / Pending Bonus #", 60, 10) >= 3
    assert S.wrap_lines("Cancelled / Pending Bonus #", 400, 10) == 1


def test_probe_retries_a_failed_measurement_once(monkeypatch):
    calls = []

    def flaky(pf, opts=None):
        calls.append(pf)
        if len(calls) == 1:
            raise TimeoutError("page not ready")
        return {"zones": [{"name": "T"}]}
    monkeypatch.setattr(S, "deep_probe", flaky)
    d, err = S.probe("p.html")
    assert d == {"zones": [{"name": "T"}]} and err == "" and len(calls) == 2
    monkeypatch.setattr(S, "deep_probe", lambda pf, opts=None: {})
    assert S.probe("p.html") == (None, "empty measurement")


def test_content_needs_does_not_drop_sheets_silently(monkeypatch, tmp_path):
    import pytest
    page = tmp_path / "page_01.html"
    page.write_text("<html></html>")
    monkeypatch.setattr(S, "deep_probe", lambda pf, opts=None: {})
    monkeypatch.setattr(S, "_sheets", lambda root: {"T": _ws(name="T")})
    monkeypatch.setattr(safexml, "from_twbx", lambda p: None)
    with pytest.raises(RuntimeError, match="no measurement"):
        S.content_needs("book.twbx", frame_result={"pages": [{"file": str(page)}]})


def test_content_needs_of_a_stretched_table_uses_its_natural_rows(monkeypatch, tmp_path):
    page = tmp_path / "page_01.html"
    page.write_text("<html></html>")
    zones = [{"name": "T", "sheet": True, "box": [0, 100, 300, 400], "fit": "entire-view",
              "tables": [{"first": 165, "last": 495, "nbody": 10, "rowh": 33, "natrh": 20,
                          "cols": [_col(80, 80)]}]}]
    monkeypatch.setattr(S, "deep_probe", lambda pf, opts=None: {"zones": zones})
    monkeypatch.setattr(S, "_sheets", lambda root: {"T": _ws(name="T")})
    monkeypatch.setattr(safexml, "from_twbx", lambda p: None)
    got = S.content_needs("book.twbx", frame_result={"pages": [{"file": str(page)}]})["T"]
    assert got["h"] == 165 + 10 * 20 - 100 + 8, "the zone's own height came back as the need"
