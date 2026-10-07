import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED
from twkit import safexml

_WB = """<workbook version='18.1'>
  <datasources>
    <datasource name='federated.x' version='18.1'>
      <column datatype='date' name='[dt]' role='dimension' type='ordinal' />
      <column datatype='integer' name='[level]' role='dimension' />
      <column datatype='string' name='[brand]' role='dimension' />
      <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Sheet'><table>
      <view>
        <datasources><datasource name='federated.x' /></datasources>
        <datasource-dependencies datasource='federated.x'>
          <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
        </datasource-dependencies>
        <slices /><aggregation value='true' />
      </view>
      <style /><panes><pane /></panes><rows /><cols />
    </table></worksheet>
  </worksheets>
</workbook>
"""


def _root():
    return etree.fromstring(_WB.encode("utf-8"))


def _view(root):
    return [w for w in root.iter("worksheet")][0].find("table/view")


def _filters(root):
    return _view(root).findall("filter")


def test_integer_dimension_gets_ok():
    root = _root()
    ws = [w for w in root.iter("worksheet")][0]
    assert ED._dim_ref(root, ws, "level") == "[federated.x].[none:level:ok]"
    assert ED._dim_ref(root, ws, "brand") == "[federated.x].[none:brand:nk]"
    assert ED._dim_ref(root, ws, "GGR") == "[federated.x].[none:GGR:qk]"


def test_range_date_wrapped_in_hashes():
    root = _root()
    res = ED.range_filter(root, "Sheet", "dt", "2026-01-01", "2026-03-31")
    assert res["ok"] and res["from"] == "#2026-01-01#"
    f = _filters(root)[0]
    assert f.get("included-values") == "in-range"
    assert f.findtext("min") == "#2026-01-01#"
    assert f.findtext("max") == "#2026-03-31#"


def test_date_under_range_filter_goes_as_qk():
    root = _root()
    ED.range_filter(root, "Sheet", "dt", 1, 2)
    assert _filters(root)[0].get("column") == "[federated.x].[none:dt:qk]"


def test_one_bound_and_no_bounds():
    root = _root()
    ED.range_filter(root, "Sheet", "GGR", low=100)
    f = _filters(root)[0]
    assert f.findtext("min") == "100" and f.find("max") is None
    root2 = _root()
    ED.range_filter(root2, "Sheet", "GGR")
    assert _filters(root2)[0].get("included-values") == "all"


def test_relative_date_built_as_in_corpus():
    root = _root()
    res = ED.relative_date_filter(root, "Sheet", "dt", period="month", first=-5)
    assert res["ok"] and res["period"] == "month"
    f = _filters(root)[0]
    assert f.get("class") == "relative-date"
    assert (f.get("first-period"), f.get("last-period")) == ("-5", "0")
    assert f.get("include-future") == "true" and f.get("include-null") == "false"
    assert f.get("period-type-v2") == "month"


def test_inverted_window_refused():
    root = _root()
    res = ED.relative_date_filter(root, "Sheet", "dt", first=0, last=-5)
    assert res["ok"] is False and "the window is empty" in res["why"]


def test_repeat_filter_replaces_previous():
    root = _root()
    ED.range_filter(root, "Sheet", "GGR", 1, 2)
    res = ED.range_filter(root, "Sheet", "GGR", 5, 9)
    assert res["previous_filters_removed"] == 1
    assert len(_filters(root)) == 1


def test_filter_before_slices():
    root = _root()
    ED.range_filter(root, "Sheet", "GGR", 1, 2)
    tags = [c.tag for c in _view(root)]
    assert tags.index("filter") < tags.index("slices")


def test_context_set_and_cleared():
    root = _root()
    ED.range_filter(root, "Sheet", "GGR", 1, 2)
    assert ED.set_filter_context(root, ["Sheet"], "GGR")["in_context"] == 1
    assert _filters(root)[0].get("context") == "true"
    assert ED.set_filter_context(root, ["Sheet"], "GGR", on=False)["out_of_context"] == 1
    assert _filters(root)[0].get("context") is None


def test_context_without_filters_refused():
    root = _root()
    res = ED.set_filter_context(root, ["Sheet"], "brand")
    assert res["ok"] is False and "silently" in res["why"]


def test_refusals_on_typos():
    root = _root()
    assert ED.range_filter(root, "None", "GGR", 1, 2)["ok"] is False
    assert ED.relative_date_filter(root, "Sheet", "dt", period="epoch")["ok"] is False
    assert ED.set_filter_context(root, ["None"], "GGR")["ok"] is False


_WB_DECL = """<workbook version='18.1'>
  <datasources><datasource name='federated.x' version='18.1'>
    <column datatype='date' name='[Month]' role='dimension' type='ordinal' />
  </datasource></datasources>
  <worksheets>
    <worksheet name='Sheet'><table>
      <view>
        <datasources><datasource name='federated.x' /></datasources>
        <datasource-dependencies datasource='federated.x'>
          <column datatype='date' name='[Month]' role='dimension' type='ordinal' />
          <column-instance column='[Month]' derivation='None'
                           name='[none:Month:ok]' pivot='key' type='ordinal' />
        </datasource-dependencies>
        <filter class='categorical' column='[federated.x].[none:Month:ok]' />
        <slices /><aggregation value='true' />
      </view>
      <style /><panes><pane /></panes><rows /><cols />
    </table></worksheet>
  </worksheets>
</workbook>
"""


def test_relative_date_needs_continuous_instance():
    root = etree.fromstring(_WB_DECL.encode("utf-8"))
    res = ED.relative_date_filter(root, "Sheet", "Month", first=-3)
    assert res["field"] == "[federated.x].[none:Month:qk]"
    dep = [w for w in root.iter("worksheet")][0].find(
        ".//datasource-dependencies[@datasource='federated.x']")
    names = {ci.get("name") for ci in dep.findall("column-instance")}
    assert "[none:Month:qk]" in names
    made = [ci for ci in dep.findall("column-instance")
            if ci.get("name") == "[none:Month:qk]"][0]
    assert made.get("type") == "quantitative"


def test_same_field_filter_other_suffix_removed():
    root = etree.fromstring(_WB_DECL.encode("utf-8"))
    view = [w for w in root.iter("worksheet")][0].find("table/view")
    view.findall("filter")[0].set("column", "[federated.x].[none:Month:qk]")
    res = ED.relative_date_filter(root, "Sheet", "Month", first=-3)
    assert res["previous_filters_removed"] == 1
    assert len(view.findall("filter")) == 1


def test_relative_date_declares_manifest_entry():
    root = etree.fromstring(_WB_DECL.replace(
        "<worksheets>",
        "<document-format-change-manifest><BasicButtonObject />"
        "</document-format-change-manifest><worksheets>").encode("utf-8"))
    res = ED.relative_date_filter(root, "Sheet", "Month", first=-3)
    assert "manifest" in res
    man = root.find(".//document-format-change-manifest")
    assert man.find("ISO8601PeriodTypes") is not None


def test_r32_flags_attribute_without_manifest_entry():
    from twkit import lint as LT

    class B:
        path = "probe.twbx"

        def __init__(self, root):
            self.root = root

    root = etree.fromstring(_WB_DECL.replace(
        "<worksheets>",
        "<document-format-change-manifest />"
        "<worksheets>").encode("utf-8"))
    view = [w for w in root.iter("worksheet")][0].find("table/view")
    f = view.findall("filter")[0]
    f.set("class", "relative-date")
    f.set("period-type-v2", "month")
    v = LT.r32_manifest_gate(B(root))
    assert [x.severity for x in v] == ["error"]
    assert "ISO8601PeriodTypes" in v[0].message
    ED.ensure_manifest(root, "ISO8601PeriodTypes")
    assert LT.r32_manifest_gate(B(root)) == []


def _csv_book(declared: bool):
    decl = "<column name='[product]' datatype='string' role='dimension' type='nominal'/>" if declared else ""
    return safexml.from_bytes((
        "<workbook><datasources><datasource name='ds'><connection class='federated'><relation>"
        "<columns><column datatype='string' name='product' ordinal='1'/></columns></relation>"
        "</connection>" + decl + "</datasource></datasources><worksheets><worksheet name='Bars'>"
        "<table><view><datasources><datasource name='ds'/></datasources>"
        "<datasource-dependencies datasource='ds'/></view></table></worksheet></worksheets>"
        "</workbook>").encode())


def test_apply_filter_never_copies_the_csv_relation_column():
    for declared in (True, False):
        root = _csv_book(declared)
        got = ED.apply_filter(root, ["Bars"], "product", member="Casino")
        dep = root.find(".//worksheet//datasource-dependencies")
        assert got["sheet_count"] == 1
        assert [c.get("name") for c in dep.findall("column")] == ["[product]"]
        assert dep.find("column-instance").get("name") == "[none:product:nk]"


def test_retune_rebuilds_a_single_member_filter():
    root = _csv_book(True)
    ED.apply_filter(root, ["Bars"], "product", member="Casino")
    assert ED.retune_categorical_filter(root, "product", ["Casino", "Sport"]) == 1
    union = root.find(".//filter/groupfilter")
    assert union.get("function") == "union"
    assert [g.get("member") for g in union] == ['"Casino"', '"Sport"']
    assert all(g.get("level") == "[none:product:nk]" for g in union)


def test_tooltip_takes_a_csv_dimension_as_is_not_summed():
    for declared in (True, False):
        root = _csv_book(declared)
        root.find(".//worksheet/table").append(etree.fromstring("<panes><pane><mark class='Bar'/></pane></panes>"))
        assert ED.set_tooltip(root, "Bars", [{"field": "product"}])["ok"]
        runs = "".join(r.text or "" for r in root.iter("run"))
        assert "[none:product:nk]" in runs and "sum:product" not in runs, runs
