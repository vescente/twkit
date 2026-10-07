import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED

_WB = """<workbook version='18.1'>
  <datasources>
    <datasource hasconnection='false' inline='true' name='Parameters'>
      <column caption='p_top' datatype='integer' name='[p_top]'
              param-domain-type='list' role='measure' type='quantitative' value='10' />
    </datasource>
    <datasource name='federated.x' version='18.1'>
      <column datatype='string' name='[country]' role='dimension' type='nominal' />
      <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
      <column caption='ARPU' datatype='real' name='[Calculation_1]'
              role='measure' type='quantitative'>
        <calculation class='tableau' formula='SUM([GGR]) / COUNTD([uid])' />
      </column>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Sheet'><table>
      <view>
        <datasources><datasource name='federated.x' /></datasources>
        <datasource-dependencies datasource='federated.x'>
          <column datatype='real' name='[GGR]' role='measure' type='quantitative' />
        </datasource-dependencies>
        <filter class='categorical' column='[federated.x].[none:other:nk]' />
        <slices><slice column='[federated.x].[none:z:nk]' /></slices>
        <aggregation value='true' />
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


def test_dimension_sorted_by_measure():
    root = _root()
    res = ED.sort_by_measure(root, "Sheet", "country", "GGR", direction="desc")
    assert res["ok"]
    cs = _view(root).find("shelf-sorts/shelf-sort-v2")
    assert cs.get("dimension-to-sort") == "[federated.x].[none:country:nk]"
    assert cs.get("measure-to-sort-by") == "[federated.x].[sum:GGR:qk]"
    assert cs.get("direction") == "DESC"
    assert cs.get("shelf") in ("rows", "columns")


def test_aggregated_calculation_goes_as_usr():
    root = _root()
    res = ED.sort_by_measure(root, "Sheet", "country", "ARPU")
    assert res["by_measure"] == "[federated.x].[usr:Calculation_1:qk]"


def test_second_sort_replaces_first():
    root = _root()
    ED.sort_by_measure(root, "Sheet", "country", "GGR", direction="desc")
    res = ED.sort_by_measure(root, "Sheet", "country", "GGR", direction="asc")
    assert res["previous_sorts_removed"] == 1
    assert len(_view(root).findall("shelf-sorts/shelf-sort-v2")) == 1
    assert _view(root).find("shelf-sorts/shelf-sort-v2").get("direction") == "ASC"


def test_sort_before_slices():
    root = _root()
    ED.sort_by_measure(root, "Sheet", "country", "GGR")
    tags = [c.tag for c in _view(root)]
    assert tags.index("shelf-sorts") < tags.index("slices")
    assert tags.index("shelf-sorts") > tags.index("datasource-dependencies")


def test_top_n_builds_three_nested_levels():
    root = _root()
    res = ED.top_n_filter(root, "Sheet", "country", "GGR", 10)
    assert res["ok"] and res["depth_given_as"] == "number"
    f = [x for x in _view(root).findall("filter")
         if x.get("column") == "[federated.x].[none:country:nk]"][0]
    end = f.find("groupfilter")
    assert end.get("function") == "end" and end.get("count") == "10"
    assert end.get("end") == "top"
    order = end.find("groupfilter")
    assert order.get("function") == "order" and order.get("direction") == "DESC"
    assert order.get("expression") == "SUM([GGR])"
    lvl = order.find("groupfilter")
    assert lvl.get("function") == "level-members"
    assert lvl.get("level") == "[none:country:nk]"


def test_top_depth_parameter_and_declaration_copy_in_sheet():
    root = _root()
    res = ED.top_n_filter(root, "Sheet", "country", "GGR", "p_top")
    assert res["depth_given_as"] == "parameter"
    end = _view(root).findall("filter")[-1].find("groupfilter")
    assert end.get("count") == "[Parameters].[p_top]"
    deps = [d for d in _view(root).findall("datasource-dependencies")
            if d.get("datasource") == "Parameters"]
    assert deps and deps[0].findall("column")


def test_missing_parameter_refused():
    root = _root()
    res = ED.top_n_filter(root, "Sheet", "country", "GGR", "p_no_such")
    assert res["ok"] is False and "silently not work" in res["why"]


def test_bottom_instead_of_top():
    root = _root()
    ED.top_n_filter(root, "Sheet", "country", "GGR", 5, direction="asc")
    end = _view(root).findall("filter")[-1].find("groupfilter")
    assert end.get("end") == "bottom"


def test_refusals_on_typos():
    root = _root()
    assert ED.sort_by_measure(root, "None", "country", "GGR")["ok"] is False
    assert ED.sort_by_measure(root, "Sheet", "country", "GGR", "sideways")["ok"] is False
    assert ED.top_n_filter(root, "None", "country", "GGR", 5)["ok"] is False


def test_sort_references_shelf_instance():
    from lxml import etree
    from twkit import edit as ED
    ds = "federated.x"
    root = etree.fromstring(f"""
<workbook><datasources><datasource name='{ds}'>
  <column datatype='string' name='[dim_1]' role='dimension' type='nominal'/>
  <column caption='V' datatype='real' name='[v]' role='measure' type='quantitative'>
    <calculation class='tableau' formula='SUM([value])'/></column>
</datasource></datasources>
<worksheets><worksheet name='Bars'><table><view>
  <datasources><datasource name='{ds}'/></datasources>
  <datasource-dependencies datasource='{ds}'>
    <column datatype='string' name='[dim_1]' role='dimension' type='nominal'/>
    <column-instance column='[dim_1]' derivation='Attribute' name='[attr:dim_1:nk]' pivot='key' type='nominal'/>
    <column-instance column='[dim_1]' derivation='None' name='[none:dim_1:nk]' pivot='key' type='nominal'/>
  </datasource-dependencies></view>
  <panes><pane><mark class='Bar'/></pane></panes>
  <rows>[{ds}].[none:dim_1:nk]</rows><cols>[{ds}].[usr:v:qk]</cols></table></worksheet></worksheets>
</workbook>""")
    res = ED.sort_by_measure(root, "Bars", "dim_1", "V", "desc")
    assert res["ok"], res
    assert res["dimension"] == f"[{ds}].[none:dim_1:nk]"


def test_sort_sets_manifest_flags():
    from lxml import etree
    from twkit import edit as ED
    ds = "federated.x"
    root = etree.fromstring(f"""
<workbook><document-format-change-manifest><MarkAnimation/></document-format-change-manifest>
<datasources><datasource name='{ds}'>
  <column datatype='string' name='[d]' role='dimension' type='nominal'/>
  <column caption='V' datatype='real' name='[v]' role='measure' type='quantitative'>
    <calculation class='tableau' formula='SUM([value])'/></column>
</datasource></datasources>
<worksheets><worksheet name='Bars'><table><view>
  <datasources><datasource name='{ds}'/></datasources>
  <datasource-dependencies datasource='{ds}'>
    <column datatype='string' name='[d]' role='dimension' type='nominal'/>
    <column-instance column='[d]' derivation='None' name='[none:d:nk]' pivot='key' type='nominal'/>
  </datasource-dependencies></view>
  <panes><pane><mark class='Bar'/></pane></panes>
  <rows>[{ds}].[none:d:nk]</rows><cols>[{ds}].[usr:v:qk]</cols></table></worksheet></worksheets>
</workbook>""")
    res = ED.sort_by_measure(root, "Bars", "d", "V", "desc")
    assert res["ok"], res
    flags = [c.tag for c in root.find("document-format-change-manifest")]
    assert flags == sorted(flags) and {"IntuitiveSorting", "IntuitiveSorting_SP2", "SortTagCleanup"} <= set(flags)
    assert ED.ensure_format_flags(root, ED.SORT_FLAGS) == []


def test_top_by_field_captioned_like_parameter():
    root = _root()
    params = [d for d in root.iter("datasource") if d.get("name") == "Parameters"][0]
    etree.SubElement(params, "column", caption="Provider", datatype="string",
                     name="[Parameter 1]", role="measure", type="nominal", value='"All"')
    fed = [d for d in root.iter("datasource") if d.get("name") == "federated.x"][0]
    c = etree.SubElement(fed, "column", caption="Provider", datatype="string",
                         name="[Calculation_P]", role="dimension", type="nominal")
    etree.SubElement(c, "calculation", {"class": "tableau", "formula": "[dim_3]"})
    res = ED.top_n_filter(root, "Sheet", "Provider", "GGR", 10)
    assert res["ok"]
    cols = [x.get("column") for x in _view(root).findall("filter")]
    assert "[federated.x].[none:Calculation_P:nk]" in cols
    assert not any("Parameter 1" in (x or "") for x in cols)


def test_sort_takes_measure_not_same_caption_dimension():
    root = _root()
    fed = [d for d in root.iter("datasource") if d.get("name") == "federated.x"][0]
    for nm, role, typ in (("[Calc_D]", "dimension", "nominal"), ("[Calc_M]", "measure", "quantitative")):
        c = etree.SubElement(fed, "column", caption="Tier", datatype="string" if role == "dimension" else "real",
                             name=nm, role=role, type=typ)
        etree.SubElement(c, "calculation", {"class": "tableau", "formula": "1"})
    res = ED.sort_by_measure(root, "Sheet", "country", "Tier", "desc")
    assert res["ok"]
    s = _view(root).find("shelf-sorts/shelf-sort-v2")
    assert s.get("measure-to-sort-by").endswith(":Calc_M:qk]")


def test_r32_sort_measure_being_dimension_is_error():
    from twkit import lint as L
    root = _root()
    v = _view(root)
    ss = etree.SubElement(v, "shelf-sorts")
    etree.SubElement(ss, "shelf-sort-v2", {"dimension-to-sort": "[federated.x].[none:country:nk]",
                                          "measure-to-sort-by": "[federated.x].[usr:Calc_D:nk]",
                                          "direction": "DESC", "shelf": "rows"})
    b = L.Book("x.twb", etree.tostring(root), root, False)
    v = [x for x in L.r32_manifest_gate(b) if "references dimension" in x.message]
    assert v and v[0].severity == "warn"


def test_r15_sort_by_field_off_sheet_is_error():
    from twkit import lint as L
    root = _root()
    ss = etree.SubElement(_view(root), "shelf-sorts")
    etree.SubElement(ss, "shelf-sort-v2", {"dimension-to-sort": "[federated.x].[none:no_such:nk]",
                                          "measure-to-sort-by": "[federated.x].[sum:GGR:qk]",
                                          "direction": "DESC", "shelf": "rows"})
    b = L.Book("x.twb", etree.tostring(root), root, False)
    msgs = [x.message for x in L.r15_orphan_filters(b)]
    assert any("sort (dimension-to-sort)" in m for m in msgs)


def test_manual_dimension_order_in_view():
    root = etree.fromstring(_WB)
    ED.order_members(root, "Sheet", "country", ["Spain", "Austria", "Spain"])
    view = root.find(".//worksheet/table/view")
    ms = view.find("manual-sort")
    assert ms.get("column") == "[federated.x].[none:country:nk]"
    assert [b.text for b in ms.iter("bucket")] == ['"Spain"', '"Austria"']
    tags = [c.tag for c in view]
    assert tags.index("filter") < tags.index("manual-sort") < tags.index("slices")
