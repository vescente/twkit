"""A dimension across the columns with Measure Names nested under it (plan vs fact tables)."""
import re
import xml.etree.ElementTree as ET  # noqa: S405

from twkit import dryrun as D
from twkit import frame as F

PVF = """<worksheet name='pvf'><table><view>
<manual-sort column='[ds].[none:metric:nk]' direction='ASC'><dictionary>
<bucket>"GGR"</bucket><bucket>"Dep"</bucket><bucket>"ARPPU"</bucket></dictionary></manual-sort>
</view><style>
<style-rule element='header'>
<format attr='background-color' field='[ds].[none:metric:nk]' value='#484848'/>
<format attr='background-color' field='[ds].[:Measure Names]' value='#6f6f6f'/>
<format attr='total-label' data-class='total' field='[ds].[none:d:ok]' value='Total'/></style-rule>
<style-rule element='mark'>
<encoding attr='color' field='[ds].[usr:fact:qk]' type='custom-interpolated'>
<color-palette custom='true' name='' type='ordered-sequential'><color>#e7eff6</color><color>#e7eff6</color></color-palette></encoding>
<encoding attr='color' field='[ds].[usr:delta:qk]' type='custom-interpolated' center='0' num-steps='2'>
<color-palette custom='true' name='' type='ordered-diverging'><color>#f8e2e2</color><color>#dcefe0</color></color-palette></encoding>
</style-rule></style>
<panes><pane><mark class='Square'/><encodings>
<color column='[ds].[Multiple Values]' separate-domains='true'/><text column='[ds].[Multiple Values]'/></encodings>
<style><style-rule element='mark'><format attr='opacity' value='0.45'/></style-rule>
<style-rule element='label'><format attr='color' value='#333333'/></style-rule></style></pane></panes>
<rows total='true' onTop='true'>[ds].[none:d:ok]</rows>
<cols>([ds].[none:metric:nk] / [ds].[:Measure Names])</cols></table></worksheet>"""

ROWS = [["2026-10-01", "ARPPU", "8", "10", "-0.2"], ["2026-10-01", "Dep", "100", "90", "0.11"],
        ["2026-10-01", "GGR", "50", "60", "-0.17"], ["2026-10-02", "ARPPU", "9", "10", "-0.1"],
        ["2026-10-02", "Dep", "120", "90", "0.33"], ["2026-10-02", "GGR", "70", "60", "0.17"]]
REFS = ["[none:d:ok]", "[none:metric:nk]"]
MREFS = ["[usr:fact:qk]", "[usr:plan:qk]", "[usr:delta:qk]"]
CAPS = ["Date", "Metric", "Fact", "Plan", "Δ"]
MASKS = ["", "", "n#,##0", "n#,##0", "*↑ #,##0.0%;↓ #,##0.0%; "]


def _html(**kw):
    ws = ET.fromstring(PVF)  # noqa: S314
    return F._render_crosstab(ws, ROWS, 2, REFS, CAPS, MASKS, mrefs=MREFS, **kw)


def _texts(html: str, tag: str) -> list:
    return [re.sub(r"<[^>]+>", "", c) for c in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", html)]


def test_members_follow_the_sheet_manual_order():
    heads = _texts(_html(), "th")
    assert [h for h in heads if h in ("GGR", "Dep", "ARPPU")] == ["GGR", "Dep", "ARPPU"]


def test_measure_names_under_a_member_give_a_column_each_and_a_second_header_row():
    html = _html()
    rows = re.findall(r"<tr[^>]*>.*?</tr>", html.split("<tbody>")[0])
    assert len(rows) == 2
    assert "colspan='3'" in rows[0] and "background:#484848" in rows[0]
    assert _texts(rows[1], "th")[1:] == ["Fact", "Plan", "Δ"] * 3 and "background:#6f6f6f" in rows[1]
    first = _texts(html.split("<tbody>")[1].split("</tr>")[0], "td")
    assert first[1:4] == ["50", "60", "↓ 17.0%"], "GGR first, its three measures in order"


def test_square_cells_take_measure_colour_at_pane_opacity_and_label_colour():
    html = _html()
    fact_bg = F._mix("#ffffff", "#e7eff6", 0.45)
    down_bg = F._mix("#ffffff", "#f8e2e2", 0.45)
    up_bg = F._mix("#ffffff", "#dcefe0", 0.45)
    assert f"background:{fact_bg};color:#333333" in html
    assert f"background:{down_bg}" in html and f"background:{up_bg}" in html


def test_grand_total_row_on_top_takes_the_source_totals_of_any_measure():
    totals = [["ARPPU", "8.5", "10", "-0.15"], ["Dep", "220", "180", "0.22"], ["GGR", "120", "120", "0"]]
    html = _html(totals=totals, total_keep=[1])
    body = html.split("<tbody>")[1]
    first = _texts(body.split("</tr>")[0], "td")
    assert first[0] == "Total" and first[1:4] == ["120", "120", ""]
    assert "Total" not in _html(), "no source totals and no additive measure: no total row"


class _Target:
    dialect = "hyper"
    columns: set = set()
    table = "t"

    def __init__(self):
        self.sql = []

    def execute(self, sql):
        self.sql.append(sql)
        return [("GGR", 120.0)]


def test_grand_totals_are_computed_without_the_row_dimensions():
    ws = ET.fromstring(PVF)  # noqa: S314
    t = _Target()
    got = D._grand_totals(ws, t, ['"d"', '"metric"'], ['SUM("fact")'], REFS, ['"x" = 1'], 10)
    assert got == {"totals": [["GGR", "120.0"]], "total_keep": [1]}
    assert t.sql[0].startswith('SELECT "metric", SUM("fact") FROM') and "GROUP BY 1" in t.sql[0]
    ws.find("table/rows").set("total", "false")
    assert D._grand_totals(ws, t, ['"d"'], ['SUM("fact")'], REFS[:1], [], 10) == {}


def test_plain_table_draws_the_source_total_of_a_calculation():
    ws = ET.fromstring("""<worksheet><table><panes><pane><mark class='Automatic'/></pane></panes>
<rows total='true' onTop='true'>[ds].[none:d:ok]</rows><cols>[ds].[:Measure Names]</cols></table></worksheet>""")  # noqa: S314
    rows = [["2026-10-01", "1.5"], ["2026-10-02", "2.5"]]
    html = F._render_table(rows, 1, ["Date", "Avg"], ["", "n#,##0.0"], ws=ws, mrefs=["[usr:avg:qk]"],
                           totals=[["1.8"]])
    first = _texts(html.split("<tbody>")[1].split("</tr>")[0], "td")
    assert first == ["Grand Total", "1.8"]


def test_sheet_with_parameters_as_primary_source_is_empty_as_in_tableau(tmp_path):
    import zipfile
    from lxml import etree
    from twkit import dryrun as D
    import _matrix_book as M
    path = M.build(str(tmp_path))
    with zipfile.ZipFile(path) as z:
        items = {i.filename: z.read(i.filename) for i in z.infolist()}
    twb = next(k for k in items if k.endswith(".twb"))
    root = etree.fromstring(items[twb])
    ws = next(w for w in root.iter("worksheet") if w.get("name") == "Table")
    dss = ws.find("table/view/datasources")
    dss.insert(0, etree.Element("datasource", name="Parameters"))
    items[twb] = etree.tostring(root)
    bad = str(tmp_path / "bad.twbx")
    with zipfile.ZipFile(bad, "w") as z:
        for k, v in items.items():
            z.writestr(k, v)
    res = {r.sheet: r for r in D.dry_run(bad)}
    assert res["Table"].status == "empty" and "Parameters" in res["Table"].note
    assert res["Bars"].status == "ok"
