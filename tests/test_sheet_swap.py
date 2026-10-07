import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED

_PARAM = """
      <column caption='p_view' datatype='string' name='[p_view]'
              param-domain-type='list' role='measure' type='nominal' value='&quot;A&quot;'>
        <calculation class='tableau' formula='&quot;A&quot;' />
        <members><member value='&quot;A&quot;' /><member value='&quot;B&quot;' /></members>
      </column>
"""

_WB = f"""<workbook version='18.1'>
  <datasources>
    <datasource hasconnection='false' inline='true' name='Parameters'>{_PARAM}</datasource>
    <datasource name='federated.x'>
      <column datatype='real' name='[Money]' role='measure' type='quantitative' />
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Wide'><table><view>
      <datasources><datasource name='federated.x' /></datasources>
      <aggregation value='true' />
    </view></table></worksheet>
    <worksheet name='Narrow'><table><view>
      <datasources><datasource name='federated.x' /></datasources>
      <aggregation value='true' />
    </view></table></worksheet>
  </worksheets>
  <dashboards>
    <dashboard name='D'><zones>
      <zone id='1' name='Wide' /><zone id='2' name='Narrow' />
    </zones></dashboard>
  </dashboards>
  <windows>
    <window class='dashboard' name='D'>
      <viewpoints>
        <viewpoint name='Wide'><zoom type='entire-view' /></viewpoint>
      </viewpoints>
    </window>
  </windows>
</workbook>
"""


def _root():
    return etree.fromstring(_WB.encode("utf-8"))


def _res(root):
    return ED.sheet_swap(root, "p_view", {"Wide": "B", "Narrow": "A"}, wide=["Wide"])


def test_gate_and_filter_on_every_sheet():
    root = _root()
    res = _res(root)
    assert res["ok"]
    assert sorted(res["calculations"]) == ["Swap Narrow", "Swap Wide"]
    for sheet in ("Wide", "Narrow"):
        ws = [w for w in root.iter("worksheet") if w.get("name") == sheet][0]
        cols = [f.get("column") or "" for f in ws.iter("filter")]
        assert any(f"Swap {sheet}" in c for c in cols), sheet
        members = [g.get("member") for g in ws.iter("groupfilter")]
        assert '"show"' in members, sheet


def test_parameter_declared_in_sheet_dependencies():
    root = _root()
    _res(root)
    for sheet in ("Wide", "Narrow"):
        ws = [w for w in root.iter("worksheet") if w.get("name") == sheet][0]
        deps = [d for d in ws.iter("datasource-dependencies")
                if d.get("datasource") == "Parameters"]
        assert deps and deps[0].findall("column"), sheet


def test_viewpoint_added_for_each_page_sheet():
    root = _root()
    res = _res(root)
    assert res["viewpoints_added"] == 1
    names = {v.get("name") for v in root.iter("viewpoint")}
    assert names == {"Wide", "Narrow"}


def test_wide_sheet_fit_removed():
    root = _root()
    _res(root)
    wide = [v for v in root.iter("viewpoint") if v.get("name") == "Wide"][0]
    assert wide.find("zoom") is None


def test_missing_sheet_refused_loudly():
    root = _root()
    res = ED.sheet_swap(root, "p_view", {"No such": "A"})
    assert res["ok"] is False
    assert "no such sheets" in res["why"]
