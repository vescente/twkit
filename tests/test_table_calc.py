import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED
from twkit import lint as LT

_WB = """<workbook version='18.1'>
  <datasources>
    <datasource name='federated.x' version='18.1'>
      <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
      <column datatype='date' name='[month]' role='dimension' type='ordinal' />
      <column caption='ARPU' datatype='real' name='[Calculation_1]'
              role='measure' type='quantitative'>
        <calculation class='tableau' formula='SUM([GGR]) / COUNTD([uid])' />
      </column>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Matrix'><table><view>
      <datasources><datasource name='federated.x' /></datasources>
      <datasource-dependencies datasource='federated.x'>
        <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
      </datasource-dependencies>
      <aggregation value='true' />
    </view></table></worksheet>
    <worksheet name='Trend'><table><view>
      <datasources><datasource name='federated.x' /></datasources>
      <datasource-dependencies datasource='federated.x'>
        <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
      </datasource-dependencies>
      <aggregation value='true' />
    </view></table></worksheet>
  </worksheets>
</workbook>
"""


def _root():
    return etree.fromstring(_WB.encode("utf-8"))


def _tc(root, name="[Running GGR]"):
    for col in root.iter("column"):
        if col.get("name") == name:
            calc = col.find("calculation")
            if calc is not None and calc.find("table-calc") is not None:
                return calc
    return None


def test_direction_written_not_implied():
    root = _root()
    res = ED.table_calc(root, "Running GGR", kind="running total",
                        field="GGR", direction="down")
    assert res["ok"], res
    calc = _tc(root)
    assert calc is not None
    assert calc.find("table-calc").get("ordering-type") == "Columns"
    assert calc.get("formula") == "RUNNING_SUM(SUM([GGR]))"


def test_aggregated_calculation_not_wrapped_in_second_aggregate():
    root = _root()
    res = ED.table_calc(root, "ARPU cumulative", kind="running total",
                        field="ARPU", direction="down")
    assert res["formula"] == "RUNNING_SUM([Calculation_1])"


def test_declaration_spread_to_sheet_copies():
    root = _root()
    ED.table_calc(root, "Running GGR", kind="running total", field="GGR",
                  direction="down", sheets=["Matrix", "Trend"])
    got = []
    for ws in root.iter("worksheet"):
        dep = ws.find(".//datasource-dependencies[@datasource='federated.x']")
        col = [c for c in dep.findall("column") if c.get("name") == "[Running GGR]"]
        assert col, ws.get("name")
        assert col[0].find("calculation").find("table-calc") is not None, ws.get("name")
        got.append(ws.get("name"))
    assert sorted(got) == ["Matrix", "Trend"]


def test_by_field_without_field_refused():
    root = _root()
    res = ED.table_calc(root, "X", kind="rank", field="GGR", direction="by field")
    assert res["ok"] is False
    assert "wrong" in res["why"]


def test_ordering_field_enables_by_field_mode():
    root = _root()
    res = ED.table_calc(root, "RR", kind="difference from previous", field="GGR",
                        direction="down", ordering_field="month")
    assert res["direction"] == "Field"
    assert res["by_field"] == "[federated.x].[month]"
    assert "note" in res
    assert _tc(root, "[RR]").find("table-calc").get("ordering-field") == \
        "[federated.x].[month]"


def test_window_substituted_into_formula():
    root = _root()
    res = ED.table_calc(root, "MA", kind="moving average", field="GGR", window=5)
    assert res["formula"] == "WINDOW_AVG(SUM([GGR]), -5, 0)"


def test_percent_recipes_get_percent_format():
    root = _root()
    res = ED.table_calc(root, "Share", kind="% of total", field="GGR",
                        direction="across")
    assert res["direction"] == "Rows"
    assert res["format"] == "p0.0%"
    col = [c for c in root.iter("column") if c.get("name") == "[Share]"][0]
    assert col.get("default-format") == "p0.0%"


def test_unknown_recipe_lists_known_ones():
    root = _root()
    res = ED.table_calc(root, "X", kind="magic", field="GGR")
    assert res["ok"] is False
    assert "running total" in res["recipes"]


def test_missing_field_refused():
    root = _root()
    assert ED.table_calc(root, "X", kind="rank", field="No such")["ok"] is False


def test_english_recipe_names_understood():
    root = _root()
    assert ED.table_calc(root, "X", kind="running_total", field="GGR")["recipe"] \
        == "running total"


class _B:
    def __init__(self, root):
        self.root = root
        self.path = "probe.twbx"


def test_r30_flags_table_function_without_direction():
    root = _root()
    ds = root.find("./datasources/datasource")
    col = etree.SubElement(ds, "column")
    col.set("caption", "Cumulative")
    col.set("name", "[Bad]")
    col.set("datatype", "real")
    calc = etree.SubElement(col, "calculation")
    calc.set("class", "tableau")
    calc.set("formula", "RUNNING_SUM(SUM([GGR]))")
    v = LT.r30_table_calc_direction(_B(root))
    assert [x.severity for x in v] == ["error"]
    assert "Cumulative" in v[0].message


def test_r30_silent_when_direction_set():
    root = _root()
    ED.table_calc(root, "Good", kind="running total", field="GGR")
    assert LT.r30_table_calc_direction(_B(root)) == []


def test_r30_ignores_field_whose_name_looks_like_a_function():
    root = _root()
    ds = root.find("./datasources/datasource")
    col = etree.SubElement(ds, "column")
    col.set("name", "[Calm]")
    col.set("datatype", "real")
    calc = etree.SubElement(col, "calculation")
    calc.set("class", "tableau")
    calc.set("formula", "DATETRUNC([Profit Bin Size (copy)], [Order Date]) "
                        "+ [Unemployment, total (% of labor force)]")
    assert LT.r30_table_calc_direction(_B(root)) == []


def test_r31_flags_sheet_missing_direction_present_in_source():
    root = _root()
    ED.table_calc(root, "Running GGR", kind="running total", field="GGR",
                  sheets=["Matrix", "Trend"])
    ws = [w for w in root.iter("worksheet") if w.get("name") == "Trend"][0]
    col = [c for c in ws.iter("column") if c.get("name") == "[Running GGR]"][0]
    calc = col.find("calculation")
    calc.remove(calc.find("table-calc"))
    v = LT.r31_table_calc_drift(_B(root))
    assert v and v[0].severity == "error"
    assert "Trend" in v[0].message


def test_r31_silent_on_consistent_workbook():
    root = _root()
    ED.table_calc(root, "Running GGR", kind="running total", field="GGR",
                  sheets=["Matrix", "Trend"])
    assert LT.r31_table_calc_drift(_B(root)) == []


def test_r31_different_directions_across_sheets_is_warning():
    root = _root()
    ED.table_calc(root, "Running GGR", kind="running total", field="GGR",
                  sheets=["Matrix", "Trend"])
    ws = [w for w in root.iter("worksheet") if w.get("name") == "Trend"][0]
    col = [c for c in ws.iter("column") if c.get("name") == "[Running GGR]"][0]
    col.find("calculation").find("table-calc").set("ordering-type", "Rows")
    v = LT.r31_table_calc_drift(_B(root))
    assert [x.severity for x in v] == ["warn"]


def test_sheet_name_typo_refused_not_empty_list():
    root = _root()
    res = ED.table_calc(root, "X", kind="rank", field="GGR", sheets=["Matrix", "Matrixx"])
    assert res["ok"] is False
    assert "Matrixx" in res["why"]
    assert "Matrix" in res["workbook_sheets"]


def test_raw_xml_name_rejected():
    root = _root()
    for raw in ("rows", "columns", "Rows", "Columns"):
        res = ED.table_calc(root, "X", kind="rank", field="GGR", direction=raw)
        assert res["ok"] is False, raw
        assert "down" in res["directions"]
