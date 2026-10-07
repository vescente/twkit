import os
import zipfile

import pytest
from lxml import etree

from twkit import blocks as B
from twkit import story as ST
from twkit import style as S
from twkit.lint import ERROR, counts, lint
from _userdata import FIXTURES, CORPUS  # noqa: E402

DB, TABLE = "reports", "partner_daily"


@pytest.fixture
def wb():
    from twkit.book import Book

    from twkit import config
    from twkit.schema import apply_to_workbook, fetch_schema
    e = Book()
    e.set_mysql_connection(server=config.get("host"), dbname=DB, username=config.get("user"),
                           table_name=TABLE, port=config.get("port"))
    fields = fetch_schema(DB, TABLE)
    apply_to_workbook(e, fields)
    e._fields = fields
    return e


def _saved(wb, tmp_path, name="x.twbx"):
    out = str(tmp_path / name)
    wb.save(out)
    with zipfile.ZipFile(out) as z:
        root = etree.fromstring(z.read([n for n in z.namelist() if n.endswith(".twb")][0]))
    return out, root


def test_auto_folders_groups_fields(wb, tmp_path):
    made = B.auto_folders(wb, wb._fields)
    assert made == 4, "expected Fields / Date / Measures / System"
    wb.add_worksheet("s")
    wb.configure_chart("s", mark_type="Bar", columns=["event_date"], rows=["ngr"])
    out, root = _saved(wb, tmp_path)
    folders = {f.get("name"): len(f.findall("folder-item")) for f in root.iter("folder")}
    assert folders["Measures"] > folders["System"]
    assert folders.get("Date", 0) >= 1
    assert counts(lint(out))[ERROR] == 0


def test_folders_live_under_folders_common(wb, tmp_path):
    B.auto_folders(wb, wb._fields)
    wb.add_worksheet("s")
    wb.configure_chart("s", mark_type="Bar", columns=["event_date"], rows=["ngr"])
    _, root = _saved(wb, tmp_path, "y.twbx")
    for f in root.iter("folder"):
        assert etree.QName(f.getparent()).localname == "folders-common"
        assert f.get("role") is None, "role is not set"


def test_folders_skip_unknown_fields(wb):
    made = B.field_folders(wb, {"Junk": ["no_such_field"], "Live": ["ngr"]})
    assert made == 1


def test_auto_folders_silent_below_threshold(wb):
    assert B.auto_folders(wb, wb._fields[:5]) == 0, "folders only get in the way on five fields"


def _with_sheets(wb):
    B.trend(wb, "Trend", "event_date", "ngr")
    B.top_n_bar(wb, "Top", "traffic_source", "ngr", top=5)
    return wb


def test_story_matches_vendor_structure(wb, tmp_path):
    _with_sheets(wb)
    ST.add_story(wb, "Review", [
        {"sheet": "Trend", "caption": "NGR tripled"},
        {"sheet": "Top", "caption": "one source drove the growth"},
    ])
    out, root = _saved(wb, tmp_path, "story.twbx")
    dash = [d for d in root.iter("dashboard") if d.get("type") == "storyboard"]
    assert dash, "a story must be a dashboard with type=storyboard"
    zones = [z.get("type-v2") for z in dash[0].iter("zone")]
    assert zones == ["layout-basic", "layout-flow", "title", "flipboard-nav", "flipboard"], zones
    nav = [z for z in dash[0].iter("zone") if z.get("type-v2") == "flipboard-nav"][0]
    board = [z for z in dash[0].iter("zone") if z.get("type-v2") == "flipboard"][0]
    assert nav.get("paired-zone-id") == board.get("id"), "zones must be paired"
    assert board.get("paired-zone-id") == nav.get("id")
    assert len(list(dash[0].iter("story-point"))) == 2
    assert counts(lint(out))[ERROR] == 0


def test_story_registers_window(wb, tmp_path):
    _with_sheets(wb)
    ST.add_story(wb, "Review", [{"sheet": "Trend", "caption": "conclusion"}])
    _, root = _saved(wb, tmp_path, "story2.twbx")
    assert any(w.get("name") == "Review" and w.get("class") == "dashboard"
               for w in root.iter("window")), "without a window there is no story tab"


@pytest.mark.parametrize("points,expect", [
    ([], "at least one step"),
    ([{"sheet": "No such", "caption": "x"}], "is not in the workbook"),
    ([{"sheet": "Trend"}], "no caption"),
    ([{"caption": "x"}], "no sheet given"),
])
def test_story_rejects_broken_input(wb, points, expect):
    _with_sheets(wb)
    with pytest.raises(ValueError, match=expect):
        ST.add_story(wb, "Review", points)


def test_story_rejects_unknown_nav_type(wb):
    _with_sheets(wb)
    with pytest.raises(ValueError, match="nav_type"):
        ST.add_story(wb, "Review", [{"sheet": "Top", "caption": "x"}], nav_type="carousel")


@pytest.mark.parametrize("key", ["eur_fin", "eur_fin_k", "eur_fin_b"])
def test_financial_formats_use_parentheses(key):
    fmt = S.FMT[key]
    assert "(" in fmt and ")" in fmt, fmt
    assert ";" in fmt, "two sections are required: positive and negative"


def test_financial_format_applies_to_field(wb, tmp_path):
    wb.add_calculated_field("Profit", "SUM([ngr])", datatype="real",
                            default_format=S.FMT["eur_fin"])
    wb.add_worksheet("s")
    wb.configure_chart("s", mark_type="Bar", columns=["event_date"], rows=["ngr"])
    out, root = _saved(wb, tmp_path, "fin.twbx")
    fmts = {c.get("caption"): c.get("default-format") for c in root.iter("column")}
    assert fmts.get("Profit") == S.FMT["eur_fin"]
    assert counts(lint(out))[ERROR] == 0


def test_flipboard_zone_pairs_after_dashboard(wb, tmp_path):
    _with_sheets(wb)
    zones = ST.flipboard_zone([{"sheet": "Trend", "caption": "it grew"},
                               {"sheet": "Top", "caption": "driven by one"}])
    layout = {"type": "container", "direction": "vertical",
              "children": [*zones, {"type": "worksheet", "name": "Top"}]}
    S.apply_sizing(wb)
    wb.add_dashboard("Overview", width=1600, height=1000, layout=layout,
                     worksheet_names=["Trend", "Top"])
    assert ST.pair_flipboard_zones(wb, "Overview", zones) is True

    out, root = _saved(wb, tmp_path, "flip.twbx")
    dash = next(d for d in root.iter("dashboard") if d.get("name") == "Overview")
    nav = next(z for z in dash.iter("zone") if z.get("type-v2") == "flipboard-nav")
    board = next(z for z in dash.iter("zone") if z.get("type-v2") == "flipboard")
    assert nav.get("paired-zone-id") == board.get("id")
    assert board.get("paired-zone-id") == nav.get("id")
    assert len(list(board.iter("story-point"))) == 2
    assert counts(lint(out))[ERROR] == 0


def test_flipboard_zone_rejects_broken_steps():
    with pytest.raises(ValueError, match="at least one step"):
        ST.flipboard_zone([])
    with pytest.raises(ValueError, match="required"):
        ST.flipboard_zone([{"sheet": "X"}])


def test_pair_flipboard_returns_false_without_stubs(wb):
    assert ST.pair_flipboard_zones(wb, "no such", [{"type": "empty"}]) is False


def test_thumbnails_extractable_from_vendor_book(tmp_path):
    from twkit import preview as PV
    src = os.path.join("/Applications/Tableau Desktop (Apple silicon) 2026.1.app",
                       "Contents", "help", "Workbooks", "en_US", "Superstore.twbx")
    if not os.path.exists(src):
        pytest.skip("Tableau Desktop is not installed")
    thumbs = PV.extract_thumbnails(src, str(tmp_path))
    assert len(thumbs) >= 5, len(thumbs)
    for t in thumbs:
        assert os.path.getsize(t.path) > 1000, t.path
        with open(t.path, "rb") as f:
            assert f.read(8).startswith(b"\x89PNG"), "must be a real PNG"


def test_ported_book_has_no_inherited_thumbnails():
    from twkit import preview as PV
    ported = os.path.join(FIXTURES, "Self Service.twbx")
    source = os.path.join(CORPUS, "Self Service.twbx")
    if not (os.path.exists(ported) and os.path.exists(source)):
        pytest.skip("workbooks not available")
    verdict = PV.compare_with_source(ported, source)
    assert not verdict["identical"], verdict


def test_strip_thumbnails_removes_all():
    from lxml import etree

    from twkit import preview as PV
    root = etree.fromstring(
        b"<workbook><thumbnails><thumbnail name='a'>x</thumbnail>"
        b"<thumbnail name='b'>y</thumbnail></thumbnails></workbook>")
    assert PV.strip_thumbnails(root) == 2
    assert root.find(".//thumbnails") is None
