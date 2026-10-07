import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "mcp"))

import pytest

from twkit import render as RD
from _userdata import FIXTURES  # noqa: E402

REF = os.path.join(FIXTURES, "Transactions.REF.twbx")
pytestmark = pytest.mark.skipif(not os.path.exists(REF), reason="reference book not available")


def test_description_built_without_db_or_tableau():
    r = RD.describe(REF)
    assert r["pages"]
    assert "data" in r and "no" in r["data"]
    for p in r["pages"]:
        assert p["tree"]
        assert "×" in p["canvas"]


def test_tree_follows_workbook_nesting():
    r = RD.describe(REF)
    page = r["pages"][0]
    assert page["tree"][0].startswith("[")
    assert any(l.startswith("  ") for l in page["tree"])


def test_area_within_canvas():
    r = RD.describe(REF)
    for p in r["pages"]:
        a = p["area"]
        assert 0.0 <= a["free"] <= 1.0
        assert a["sheets"] >= 0 and a["controls"] >= 0


def test_filter_card_not_a_sheet():
    class Z:
        def __init__(self, kind, name):
            self.kind, self.name = kind, name

    assert RD.is_sheet(Z("worksheet", "Trend"))
    assert not RD.is_sheet(Z("filter", "Trend"))
    assert not RD.is_sheet(Z("color", "Trend"))
    assert not RD.is_sheet(Z("layout-flow", ""))


def test_verdict_requires_screenshot_for_unchecked_sheet():
    v = RD._verdict([], skipped={"Matrix"}, placed={"Matrix"}, has_data=True)
    assert v.startswith("look"), v
    assert "Matrix" in v


def test_verdict_silent_on_healthy_layout():
    v = RD._verdict([], skipped=set(), placed={"Sheet"}, has_data=True)
    assert "no screenshot needed" in v


def test_verdict_does_not_pass_unchecked_as_checked():
    v = RD._verdict([], skipped=set(), placed={"Sheet"}, has_data=False)
    assert "data not checked" in v


def test_layout_error_raises_flag():
    bad = [{"code": "V7", "level": "error", "page": "Overview",
            "what": "button controls a zone that does not exist", "fix": ""}]
    assert RD._verdict(bad, set(), set(), True).startswith("LOOK")


def test_button_parsed_with_its_zones():
    from lxml import etree
    dash = etree.fromstring(
        "<dashboard><zones>"
        "<zone id='9' type-v2='dashboard-object'><button>"
        "<toggle-action>tabdoc:toggle-button-click-action window-id=\"{X}\" "
        "zone-id=\"9\" zone-ids=[7]</toggle-action></button></zone>"
        "</zones></dashboard>")
    assert RD._toggles(dash) == {"9": ["7"]}


def test_dead_button_is_error():
    from lxml import etree
    dash = etree.fromstring(
        "<dashboard><size sizing-mode='fixed' minwidth='1000' minheight='800'/>"
        "<zones>"
        "<zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'/>"
        "<zone id='9' type-v2='dashboard-object' x='0' y='0' w='1000' h='1000'>"
        "<button><toggle-action>zone-id=\"9\" zone-ids=[77]</toggle-action></button>"
        "</zone></zones></dashboard>")
    cw, ch, _ = 1000, 800, "fixed"
    tree = RD._build_tree(dash, cw, ch)
    flat = [z for t in tree for z in t.walk()]
    found = RD._findings("Overview", tree, flat, cw, ch, {}, {}, set(), dash)
    assert any(f["code"] == "V7" and f["level"] == "error" for f in found), found


def test_floating_zone_differs_from_tile():
    from lxml import etree
    dash = etree.fromstring(
        "<dashboard><zones>"
        "<zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'/>"
        "<zone id='9' type-v2='dashboard-object' x='500' y='500' w='2000' h='2000'/>"
        "</zones></dashboard>")
    tree = RD._build_tree(dash, 1000, 800)
    assert [z.floating for z in tree] == [False, True]


def test_sheet_stack_is_fact_not_defect():
    from lxml import etree
    dash = etree.fromstring(
        "<dashboard><zones><zone id='1' type-v2='layout-flow' x='0' y='0' "
        "w='100000' h='100000'>"
        "<zone id='2' name='A' x='0' y='0' w='50000' h='50000'/>"
        "<zone id='3' name='B' x='0' y='0' w='50000' h='50000'/>"
        "</zone></zones></dashboard>")
    tree = RD._build_tree(dash, 1000, 800)
    flat = [z for t in tree for z in t.walk()]
    found = RD._findings("Overview", tree, flat, 1000, 800, {}, {}, set(), dash)
    stack = [f for f in found if f["code"] == "V1"]
    assert stack and stack[0]["level"] == "info"
    assert not [f for f in found if f["level"] == "error"]


def test_control_strip_printed_as_one_line():
    from lxml import etree
    dash = etree.fromstring(
        "<dashboard><zones><zone id='1' type-v2='layout-flow' x='0' y='0' "
        "w='100000' h='10000'>"
        + "".join(f"<zone id='{i}' type-v2='filter' name='S' x='{i*10000}' y='0' "
                  f"w='10000' h='10000'/>" for i in range(2, 8))
        + "</zone></zones></dashboard>")
    lines = RD._tree_lines(RD._build_tree(dash, 1000, 800))
    assert any("controls of" in l for l in lines), lines
    assert len(lines) == 2, lines


def test_report_cheaper_than_screenshot():
    r = RD.describe(REF)
    text = RD.format_report(r)
    per_page = len(text) / 3 / max(1, r["page_count"])
    assert per_page < 1500
    one = RD.format_report(RD.describe(REF, page=r["pages"][0]["page"]))
    assert len(one) < len(text)


def test_previews_know_last_writer(tmp_path, monkeypatch):
    import zipfile

    from twkit import preview as PV
    monkeypatch.setattr(PV, "_stamp_path", lambda: str(tmp_path / "written.json"))
    book = tmp_path / "Book.twbx"
    twb = ("<?xml version='1.0' encoding='utf-8' ?>\n\n<workbook>"
           "<thumbnails><thumbnail height='384' name='Overview' width='384'>"
           "aGk=</thumbnail></thumbnails>"
           "<datasources/><worksheets/><dashboards/></workbook>")
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("Book.twb", twb)

    st = PV.thumbs_state(str(book))
    assert st["fresh"] is None and "UNKNOWN" in st["verdict"]

    PV.mark_written(str(book))
    st = PV.thumbs_state(str(book))
    assert st["fresh"] is False and "STALE" in st["verdict"]

    import os
    import time
    os.utime(book, (time.time() + 5, time.time() + 5))
    st = PV.thumbs_state(str(book))
    assert st["fresh"] is True and "FRESH" in st["verdict"]


def test_book_without_previews_not_seen(tmp_path, monkeypatch):
    import zipfile

    from twkit import preview as PV
    monkeypatch.setattr(PV, "_stamp_path", lambda: str(tmp_path / "written.json"))
    book = tmp_path / "Empty.twbx"
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("Empty.twb", "<?xml version='1.0' encoding='utf-8' ?>\n\n"
                                 "<workbook><worksheets/><dashboards/></workbook>")
    st = PV.thumbs_state(str(book))
    assert st["fresh"] is False and "no previews" in st["verdict"]


def _book(tmp_path, name, zones):
    import zipfile
    twb = ("<?xml version='1.0' encoding='utf-8' ?>\n\n<workbook>"
           "<datasources/><worksheets/><dashboards><dashboard name='Overview'>"
           "<size sizing-mode='fixed' minwidth='1000' minheight='1000'/>"
           f"<zones>{zones}</zones></dashboard></dashboards></workbook>")
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Book.twb", twb)
    return str(p)


def test_layout_diff_names_zone_and_size(tmp_path):
    a = _book(tmp_path, "before.twbx",
              "<zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>"
              "<zone id='2' name='Trend' x='0' y='0' w='50000' h='50000'/></zone>")
    b = _book(tmp_path, "after.twbx",
              "<zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>"
              "<zone id='2' name='Trend' x='0' y='0' w='80000' h='50000'/></zone>")
    d = RD.diff(a, b)
    assert d["change_count"] == 1
    assert "500x500 -> 800x500" in d["what"][0], d["what"]


def test_diff_sees_appear_and_vanish(tmp_path):
    a = _book(tmp_path, "before2.twbx",
              "<zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>"
              "<zone id='2' name='Trend' x='0' y='0' w='50000' h='50000'/></zone>")
    b = _book(tmp_path, "after2.twbx",
              "<zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>"
              "<zone id='3' name='Matrix' x='0' y='0' w='50000' h='50000'/></zone>")
    what = " ".join(RD.diff(a, b)["what"])
    assert "removed" in what and "added" in what


def test_coordinate_jitter_not_a_change(tmp_path):
    a = _book(tmp_path, "before3.twbx",
              "<zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>"
              "<zone id='2' name='Trend' x='0' y='0' w='50000' h='50000'/></zone>")
    b = _book(tmp_path, "after3.twbx",
              "<zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>"
              "<zone id='2' name='Trend' x='100' y='0' w='50100' h='50000'/></zone>")
    assert RD.diff(a, b)["change_count"] == 0


def test_zone_hiding_visible_in_diff(tmp_path):
    a = _book(tmp_path, "before4.twbx",
              "<zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>"
              "<zone id='2' name='Trend' x='0' y='0' w='50000' h='50000'/></zone>")
    b = _book(tmp_path, "after4.twbx",
              "<zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>"
              "<zone id='2' name='Trend' hidden-by-user='true' x='0' y='0' "
              "w='50000' h='50000'/></zone>")
    assert "HIDDEN" in " ".join(RD.diff(a, b)["what"])


def test_look_skips_screenshot_when_fresh_render_exists(tmp_path, monkeypatch):
    import zipfile

    from twkit import preview as PV
    monkeypatch.setattr(PV, "_stamp_path", lambda: str(tmp_path / "w.json"))
    book = tmp_path / "Book.twbx"
    png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
           "DwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    twb = ("<?xml version='1.0' encoding='utf-8' ?>\n\n<workbook>"
           f"<thumbnails><thumbnail height='384' name='Overview' width='384'>{png}"
           "</thumbnail></thumbnails><datasources/><worksheets/>"
           "<dashboards/></workbook>")
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("Book.twb", twb)
    r = RD.look(str(book), out_dir=str(tmp_path / "png"))
    assert r["images"]
    assert "not needed" in r["image"] or "freshness is unknown" in r["image"]


def test_look_reports_stale_preview(tmp_path, monkeypatch):
    import zipfile

    from twkit import preview as PV
    monkeypatch.setattr(PV, "_stamp_path", lambda: str(tmp_path / "w2.json"))
    book = tmp_path / "Book2.twbx"
    twb = ("<?xml version='1.0' encoding='utf-8' ?>\n\n<workbook>"
           "<thumbnails><thumbnail height='384' name='Overview' width='384'>aGk="
           "</thumbnail></thumbnails><datasources/><worksheets/>"
           "<dashboards/></workbook>")
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("Book2.twb", twb)
    PV.mark_written(str(book))
    r = RD.look(str(book), out_dir=str(tmp_path / "png2"))
    assert not r["images"]
    assert "STALE" in r["previews"]


def test_live_source_book_does_not_hit_network(tmp_path):
    import zipfile
    book = tmp_path / "Live.twbx"
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("Live.twb", "<?xml version='1.0' encoding='utf-8' ?>\n\n"
                                "<workbook><worksheets/><dashboards/></workbook>")
    assert RD.has_local_data(str(book)) is False
    assert RD.has_local_data(str(book), db="marts", table="daily_metrics") is True


def test_look_does_not_write_to_owner_folder(tmp_path, monkeypatch):
    import zipfile

    from twkit import preview as PV
    monkeypatch.setattr(PV, "_stamp_path", lambda: str(tmp_path / "w3.json"))
    png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
           "DwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    book = tmp_path / "Foreign.twbx"
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("Foreign.twb", "<?xml version='1.0' encoding='utf-8' ?>\n\n"
                   f"<workbook><thumbnails><thumbnail height='384' name='Overview' "
                   f"width='384'>{png}</thumbnail></thumbnails>"
                   "<datasources/><worksheets/><dashboards/></workbook>")
    r = RD.look(str(book))
    assert r["images"]
    for p in r["images"]:
        assert not p.startswith(str(tmp_path) + "/_preview"), p
        assert "/twkit_preview/" in p or p.startswith("/var") or p.startswith("/tmp"), p


def _swap_book(tmp_path, name, swapped: bool):
    import zipfile
    ds = "federated.x"

    def ws(n):
        filt = f"<filter class='categorical' column='[{ds}].[Swap {n}]'/>" if swapped else ""
        return (f"<worksheet name='{n}'><table><view>{filt}</view>"
                "<panes><pane><mark class='Text'/></pane></panes></table></worksheet>")
    zones = ("<zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>"
             "<zone id='2' type-v2='layout-flow' param='vert' x='0' y='0' w='100000' h='60000'>"
             "<zone id='3' name='A' x='0' y='0' w='100000' h='20000'/>"
             "<zone id='4' name='B' x='0' y='20000' w='100000' h='20000'/>"
             "<zone id='5' name='C' x='0' y='40000' w='100000' h='20000'/>"
             "</zone></zone>")
    twb = ("<?xml version='1.0' encoding='utf-8' ?>\n\n<workbook><datasources/>"
           f"<worksheets>{ws('A')}{ws('B')}{ws('C')}</worksheets>"
           "<dashboards><dashboard name='Overview'>"
           "<size sizing-mode='fixed' minwidth='1000' minheight='1000'/>"
           f"<zones>{zones}</zones></dashboard></dashboards></workbook>")
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Book.twb", twb)
    return str(p)


def test_swapped_sheet_measured_by_container_height(tmp_path):
    stats = {"sheets": [{"sheet": n, "categories": 30} for n in "ABC"], "skipped": []}
    plain = RD.describe(_swap_book(tmp_path, "plain.twbx", False), stats=stats)
    swap = RD.describe(_swap_book(tmp_path, "swap.twbx", True), stats=stats)
    codes_plain = [f["code"] for f in plain["findings"]]
    codes_swap = [f["code"] for f in swap["findings"]]
    assert codes_plain.count("V3") == 3, codes_plain
    assert "V3" not in codes_swap, codes_swap
    assert "V8" in codes_swap, codes_swap
