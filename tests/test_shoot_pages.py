import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "mcp"))

from lxml import etree

from twkit import safexml, shot


def _tree(xml):
    return safexml.from_bytes(etree.tostring(etree.fromstring(xml)))


WB = """<workbook><dashboards>
   <dashboard name='Overview'/><dashboard name='Report'/></dashboards>
 <windows>
   <window class='dashboard' name='Overview' maximized='true'/>
   <window class='dashboard' name='Report'/>
   <window class='worksheet' name='KPI' maximized='true'/>
 </windows></workbook>"""


def test_active_page_switched_in_file():
    root = _tree(WB)
    assert shot.set_active_page(root, "Report") is True
    act = {w.get("name"): w.get("maximized") for w in root.iter("window")
           if w.get("class") == "dashboard"}
    assert act == {"Overview": None, "Report": "true"}
    ws = next(w for w in root.iter("window") if w.get("class") == "worksheet")
    assert ws.get("maximized") is None
    assert sum(1 for w in root.iter("window") if w.get("maximized")) == 1


def test_missing_page_named():
    assert shot.set_active_page(_tree(WB), "no such") is False


def test_pages_read_from_book(tmp_path):
    book = str(tmp_path / "B.twbx")
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("B.twb", WB)
    assert shot.pages(book) == ["Overview", "Report"]


def test_gallery_built_and_links_screenshots(tmp_path):
    d = str(tmp_path)
    for n in ("Overview.png", "Report.png"):
        open(os.path.join(d, n), "wb").write(b"x")
    p = shot.write_gallery(d, "Game report", {"Overview": os.path.join(d, "Overview.png"),
                                              "Report": os.path.join(d, "Report.png")})
    html = open(p, encoding="utf-8").read()
    assert 'src="Overview.png"' in html and 'src="Report.png"' in html
    assert "REAL Tableau render" in html


def test_capture_only_tableau_window(tmp_path, monkeypatch):
    monkeypatch.setattr(shot, "pick_window",
                        lambda *a, **k: {"id": 7, "owner": "Safari", "w": 900, "h": 700})
    r = shot.capture(str(tmp_path / "x.png"))
    assert r["ok"] is False and "Safari" in r["why"]


def test_no_window_id_no_fullscreen_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(shot, "pick_window",
                        lambda *a, **k: {"id": 0, "owner": "Tableau", "w": 900, "h": 700})
    r = shot.capture(str(tmp_path / "x.png"))
    assert r["ok"] is False and "full-screen" in r["why"]


def test_code_has_no_fullscreen_screencapture():
    import re
    src = open(os.path.join(ROOT, "mcp", "twkit", "shot.py"), encoding="utf-8").read()
    calls = re.findall(r'\[\s*"screencapture"[^\]]*\]', src, re.S)
    assert calls
    for c in calls:
        assert "-l{" in c or '-l"' in c


def test_reference_line_without_forbidden_attributes(tmp_path):
    import _matrix_book as M
    from twkit.book import Book
    b = Book.open(M.build(str(tmp_path)))
    b.add_reference_line("Bars", axis_field="SUM(sales)", value_field="SUM(sales)",
                         tooltip="Average = <Value>")
    for rl in b.root.iter("reference-line"):
        assert rl.get("tooltip") is None and rl.get("tooltip-type") is None


def test_log_channel_sees_failed_load(tmp_path):
    from twkit import tablog
    log = tmp_path / "log.txt"
    log.write_text(
        '{"ts":"1","sev":"info","k":"begin-command","v":"Errors occurred while trying '
        'to load the workbook.\\nError(3641,1612): attribute \'tooltip\' is not declared '
        "for element 'reference-line'\"}\n", encoding="utf-8")
    fails = tablog.load_failures(path=str(log))
    assert any("is not declared for element 'reference-line'" in f for f in fails), fails


def test_view_child_order_fixed():
    from twkit.order import normalize_view, normalize_views
    root = _tree("""<workbook><worksheets><worksheet name='w'><table>
      <view><datasource-dependencies/><slices/><aggregation/><filter column='x'/></view>
    </table></worksheet></worksheets></workbook>""")
    assert normalize_views(root) == 1
    tags = [c.tag for c in root.find(".//view")]
    assert tags == ["datasource-dependencies", "filter", "slices", "aggregation"], tags
    assert normalize_views(root) == 0


def test_sheet_zones_stretch():
    from twkit import edit as ED
    root = _tree("""<workbook><dashboards><dashboard name='D'><zones>
      <zone id='1' type-v2='layout-basic'>
        <zone id='2' name='Chart'/>
        <zone id='4' name='Chart2' type-v2='NONE'/>
        <zone id='3' name='Flt' type-v2='filter' param='p'/>
      </zone></zones></dashboard></dashboards></workbook>""")
    dash = root.find(".//dashboard")
    assert ED.stretch_zones(dash) == {"zones_stretched": 2}
    lc = root.find(".//zone[@name='Chart']/layout-cache")
    assert lc.get("type-h") == "scalable" and lc.get("type-w") == "scalable"
    assert root.find(".//zone[@name='Flt']/layout-cache") is None


def test_parameter_field_binding_removed():
    from twkit import edit as ED
    root = _tree("""<workbook><datasources><datasource name='Parameters'>
      <column name='[P1]' caption='Date from' param-domain-type='any' value='#2026-08-01#'
              default-value-field='[ds].[_start_period]'>
        <calculation formula='#2026-08-01#'/></column>
    </datasource></datasources></workbook>""")
    assert ED.set_param_value(root, "Date from", "2026-03-01", quote="#") == 1
    c = root.find(".//column")
    assert c.get("value") == "#2026-03-01#"
    assert "default-value-field" not in c.attrib
    root2 = _tree("""<workbook><datasources><datasource name='Parameters'>
      <column name='[P1]' caption='D' param-domain-type='any' value='#1#'
              default-value-field='[ds].[x]'><calculation formula='#1#'/></column>
    </datasource></datasources></workbook>""")
    ED.set_param_value(root2, "D", "2026-03-01", quote="#", unpin_dynamic=False)
    assert root2.find(".//column").get("default-value-field")


def test_sheet_title_own_size():
    from twkit import edit as ED
    root = _tree("<workbook><worksheets><worksheet name='GGR'><table/></worksheet>"
                 "</worksheets></workbook>")
    assert ED.set_sheet_title(root, "GGR", size="9") == 1
    run = root.find(".//layout-options/title/formatted-text/run")
    assert run.get("fontsize") == "9" and run.text == "GGR"
    assert run.get("bold") == "true" and "fontweight" not in run.attrib
    ED.set_sheet_title(root, "GGR", size="8")
    assert len(root.findall(".//worksheet/layout-options")) == 1
