import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "mcp"))

import pytest
from lxml import etree

from twkit import edit as ED
from twkit import safexml
from _userdata import FIXTURES  # noqa: E402

REF = os.path.join(FIXTURES, "Transactions.REF.twbx")
pytestmark = pytest.mark.skipif(not os.path.exists(REF), reason="no reference workbook")


@pytest.fixture
def root():
    return safexml.from_twbx(REF)


def test_shelf_is_built_as_tableau_writes_it():
    toks = ["[ds].[a]", "[ds].[b]", "[ds].[c]"]
    assert ED.rebuild_shelf(toks) == "([ds].[a] / ([ds].[b] / [ds].[c]))"
    assert ED.rebuild_shelf(["[ds].[a]"]) == "[ds].[a]"
    assert ED.rebuild_shelf([]) == ""


def test_reference_does_not_confuse_similar_names():
    assert ED.mentions("[none:provider:ok]", "provider")
    assert not ED.mentions("[none:provider_id:ok]", "provider")
    assert ED.mentions("[campaign_id (Custom SQL Query1)]", "campaign_id")


def test_field_removal_cleans_attributes_and_texts(root):
    before = ED_count(root, "provider")
    assert before > 0, "the reference has the field, otherwise the test is meaningless"
    ED.drop_fields(root, ["provider"], keep_on_shelves="pay_system_name")
    assert ED_count(root, "provider") == 0


def ED_count(root, field: str) -> int:
    n = 0
    for el in root.iter():
        if el.getparent() is not None and el.getparent().tag == "metadata-record":
            continue
        for v in list(el.attrib.values()) + ([el.text] if el.text else []):
            if ED.mentions(v or "", field):
                n += 1
    return n


def test_field_repeat_on_shelf_is_removed(root):
    ws = next(w for w in root.iter("worksheet")
              if w.get("name") == "[A] transaction table")
    rows = ws.find(".//rows")
    toks = ED.shelf_tokens(rows.text or "")
    assert len(toks) != len(set(toks)), "the reference has a repeat (event_date twice)"
    assert ED.dedupe_shelves(root) >= 1
    toks = ED.shelf_tokens(ws.find(".//rows").text or "")
    assert len(toks) == len(set(toks))


def test_dual_axis_is_not_a_repeat(root):
    ws = next(w for w in root.iter("worksheet") if w.get("name") == "[C] SCR trend")
    before = (ws.find(".//rows").text or "").strip()
    assert "+" in before
    ED.dedupe_shelves(root)
    assert (ws.find(".//rows").text or "").strip() == before


def test_dashboard_copy_gets_own_window_and_clean_viewpoints(root):
    res = ED.clone_dashboard(root, "Providers", "TEST",
                             {"[P] provides tab": "[\u0421] CR tab",
                              "[P] Providers trend": None})
    assert res["window_uuid"]
    dash = next(d for d in root.find("dashboards").findall("dashboard")
                if d.get("name") == "TEST")
    win = next(w for w in root.find("windows").findall("window")
               if w.get("name") == "TEST")
    on_dash = {z.get("name") for z in dash.find("zones").iter("zone")
               if z.get("name") and z.get("type-v2") in (None, "")}
    vps = {v.get("name") for v in win.iter("viewpoint")}
    assert vps <= on_dash, f"extra viewpoints: {vps - on_dash}"
    assert dash.find("devicelayouts") is None, "the copy's phone layout is removed"
    ids = [z.get("id") for z in dash.iter("zone") if z.get("id")]
    assert len(ids) == len(set(ids)), "zone ids are unique"


def test_navigation_button_addresses_the_right_window(root):
    ED.clone_dashboard(root, "Providers", "TEST2", {"[P] provides tab": "[\u0421] CR tab"})
    added = ED.add_nav_buttons(root, ["TEST2"])
    assert added > 0
    uid = ED.window_uuid(root, "TEST2")
    found = [b for b in root.iter("button") if uid in (b.get("action") or "")]
    assert len(found) == added


def test_repeated_call_does_not_multiply_buttons(root):
    ED.clone_dashboard(root, "Providers", "TEST3", {"[P] provides tab": "[\u0421] CR tab"})
    first = ED.add_nav_buttons(root, ["TEST3"])
    assert first > 0
    assert ED.add_nav_buttons(root, ["TEST3"]) == 0


def test_filter_is_rebuilt_to_its_own_values(root):
    n = ED.retune_categorical_filter(root, "transaction_status",
                                     ["success", "cancel", "pending"])
    assert n >= 1
    for f in root.iter("filter"):
        if "transaction_status" not in (f.get("column") or ""):
            continue
        members = {(g.get("member") or "").strip('"') for g in f.iter("groupfilter")
                   if g.get("member")}
        if members:
            assert members == {"success", "cancel", "pending"}


def test_parameter_date_is_written_in_hashes(root):
    n = ED.set_param_value(root, "p_start_dt", "2026-06-01", quote="#")
    assert n >= 1
    vals = {c.get("value") for c in root.iter("column")
            if (c.get("caption") or "") == "p_start_dt"}
    assert vals == {"#2026-06-01#"}, f"values diverged: {vals}"


def test_controls_are_not_put_into_flow(root):
    dash = next(d for d in root.find("dashboards").findall("dashboard")
                if d.get("name") == "Conversion")
    out = ED.put_controls_over(dash, "[\u0421] CR tab", ["[Parameters].[Parameter 1]"])
    assert "cancelled" in out or "no zone" in out


def test_field_resolves_by_column_name_and_by_caption(root):
    got = ED.resolve_fields(root, ["pay_system_name", "Payment system"])
    assert got["not_found"] == []
    assert got["fields"] == ["Payment system", "Payment system"]


def test_measure_gets_aggregate_dimension_does_not(root):
    got = ED.resolve_fields(root, ["amount", "user_country"])
    assert got["fields"][0].startswith("SUM("), "Tableau does not accept a bare measure on a shelf"
    assert not got["fields"][1].startswith(("SUM(", "AVG(", "COUNT(")), \
        "a dimension is not wrapped in an aggregate"


def test_unfound_field_is_named_not_swallowed(root):
    got = ED.resolve_fields(root, ["no_such_field"])
    assert got["not_found"] == ["no_such_field"]
    assert got["fields"] == []


def test_width_is_written_to_header_not_cell(root):
    n = ED.set_column_width(root, "[\u0421] CR tab", "provider", 222)
    assert n >= 1
    ws = next(w for w in root.iter("worksheet") if w.get("name") == "[\u0421] CR tab")
    rule = next(r for r in ws.iter("style-rule") if r.get("element") == "header")
    widths = [f.get("value") for f in rule.findall("format") if f.get("attr") == "width"]
    assert "222" in widths


def test_number_format_is_set_by_caption(root):
    n = ED.set_number_format(root, "Turnover", "n#,##0")
    assert n >= 1
    cols = [c for c in root.iter("column") if (c.get("caption") or "") == "Turnover"]
    assert all(c.get("default-format") == "n#,##0" for c in cols)


def test_column_is_found_by_features_not_by_id(root):
    found = {}
    for dash in root.iter("dashboard"):
        cols = ED.left_column(dash)
        if cols:
            found[dash.get("name")] = [ED._role(z) for z in cols]
    assert len(found) >= 5, f"column found on only {len(found)} dashboards: {found}"
    assert all(r != "other" for rs in found.values() for r in rs)


def test_containers_nested_in_flow_are_not_taken(root):
    for dash in root.iter("dashboard"):
        for z in ED.left_column(dash):
            assert ED._parent_kind(z) in ED._ABS_PARENT


def test_alignment_removes_spread(root):
    before = ED.column_report(root)["spread"]
    assert any(v > 400 for v in before.values()), f"no drift in the reference: {before}"
    after = ED.align_left_column(root)["measured"]["spread"]
    assert all(v == 0 for v in after.values()), after


def test_minimal_width_is_taken_not_the_most_frequent(root):
    was = [ED._rect(z)[2] for d in root.iter("dashboard") for z in ED.left_column(d)]
    ED.align_left_column(root)
    now = {ED._rect(z)[2] for d in root.iter("dashboard") for z in ED.left_column(d)}
    assert now == {min(was)}


def test_roles_are_aligned_separately(root):
    ED.align_left_column(root)
    tops = {}
    for dash in root.iter("dashboard"):
        for z in ED.left_column(dash):
            tops.setdefault(ED._role(z), set()).add(ED._rect(z)[1])
    assert all(len(v) == 1 for v in tops.values()), tops
    assert len(tops) > 1, "the reference must have more than one role"
    assert len(set().union(*tops.values())) > 1, "roles must not collapse into one y"


def test_heights_that_do_not_fit_are_not_written(root):
    r = ED.align_left_column(root, heights={"dashboard-object": 400})
    assert any("do not fit" in n for n in r["notes"]), r["notes"]
    assert any("each fits" in n for n in r["notes"]), "a refusal without a number is useless"
    for dash in root.iter("dashboard"):
        for z in ED.left_column(dash):
            for k in z.iter("zone"):
                assert k.get("fixed-size") != "400"


def test_overlap_with_neighbour_is_rolled_back():
    from lxml import etree
    xml = """<workbook><dashboards>
      <dashboard name='A'><size minheight='800' minwidth='1100'/><zones>
        <zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>
          <zone id='2' type-v2='layout-flow' param='vert' x='0' y='0' w='10000' h='50000'>
            <zone id='3' type-v2='filter' x='0' y='0' w='10000' h='25000'/>
            <zone id='4' type-v2='filter' x='0' y='25000' w='10000' h='25000'/>
          </zone>
          <zone id='5' type-v2='layout-flow' param='vert' x='0' y='60000' w='9000' h='40000'>
            <zone id='6' type-v2='filter' x='0' y='60000' w='9000' h='20000'/>
            <zone id='7' type-v2='filter' x='0' y='80000' w='9000' h='20000'/>
          </zone>
          <zone id='8' type-v2='empty' x='0' y='50000' w='10000' h='10000'/>
        </zone></zones></dashboard></dashboards></workbook>"""
    root = safexml.from_bytes(etree.tostring(etree.fromstring(xml)))
    r = ED.align_left_column(root)
    assert any("rolled back" in x for x in r["refused"]), r


def _tree(xml: str):
    from lxml import etree
    return safexml.from_bytes(etree.tostring(etree.fromstring(xml)))


def test_dependent_calculations_are_found_through_the_chain():
    root = _tree("""<workbook><datasources><datasource>
      <column name='[GGR Real]' datatype='real'/>
      <column name='[PAU]'><calculation formula='COUNTD(IF [GGR Real] &lt;&gt; 0 THEN 1 END)'/></column>
      <column name='[ARPU]'><calculation formula='[PAU] / 2'/></column>
      <column name='[RTP]'><calculation formula='SUM([Wins total])'/></column>
    </datasource></datasources></workbook>""")
    got = ED.dependent_calcs(root, ["GGR Real"])
    assert got == ["PAU", "ARPU"], got
    assert "RTP" not in got


def test_parameter_item_is_dropped_together_with_default_value():
    root = _tree("""<workbook><datasources><datasource name='Parameters'>
      <column name='[p1]' param-domain-type='list' value='&quot;Aggregator&quot;'>
        <calculation formula='&quot;Aggregator&quot;'/>
        <members>
          <member value='&quot;Provider&quot;'/>
          <member value='&quot;Aggregator&quot;'/>
        </members>
      </column>
    </datasource></datasources></workbook>""")
    r = ED.drop_param_members(root, ["Aggregator"])
    assert r["members_dropped"] == 1
    assert r["defaults_reset"] == 1
    col = root.find(".//column")
    assert col.get("value") == '"Provider"'
    assert col.find("calculation").get("formula") == '"Provider"'
    assert [m.get("value") for m in col.iter("member")] == ['"Provider"']


def test_case_branch_and_in_item_are_removed_from_formula():
    root = _tree("""<workbook><datasources><datasource>
      <column name='[a]'><calculation formula="CASE [p] WHEN 'Aggregator' THEN [Aggregator] WHEN 'Provider' THEN [Provider] END"/></column>
      <column name='[b]'><calculation formula="CASE TRUE WHEN [p] IN ('GGR', 'Real GGR', 'PAU') THEN 'x' END"/></column>
      <column name='[c]'><calculation formula="CASE [p] WHEN 'GGR' THEN 1 WHEN 'Real GGR' THEN 2 END"/></column>
    </datasource></datasources></workbook>""")
    r = ED.drop_case_branches(root, ["Aggregator", "Real GGR"])
    assert r["branches_removed"] == 2 and r["in_items_removed"] == 1
    f = {c.get("name"): c.find("calculation").get("formula") for c in root.iter("column")}
    assert "Aggregator" not in f["[a]"] and "Provider" in f["[a]"]
    assert f["[b]"] == "CASE TRUE WHEN [p] IN ('GGR', 'PAU') THEN 'x' END"
    assert "Real GGR" not in f["[c]"] and "WHEN 'GGR' THEN 1" in f["[c]"]


def test_last_in_item_is_removed_without_dangling_comma():
    root = _tree("""<workbook><datasources><datasource>
      <column name='[a]'><calculation formula="[p] IN ('GGR', 'Real GGR')"/></column>
    </datasource></datasources></workbook>""")
    ED.drop_case_branches(root, ["Real GGR"])
    assert root.find(".//calculation").get("formula") == "[p] IN ('GGR')"


def test_elseif_branch_is_removed_too_and_first_is_promoted_to_if():
    root = _tree("""<workbook><datasources><datasource>
      <column name='[g]'><calculation formula="IF [p] = 'Aggregator' THEN [Aggregator]&#10;ELSEIF [p] = 'Game' THEN [Game]&#10;ELSEIF [p] = 'Campaign' THEN [Campaign]&#10;ELSE ''&#10;END"/></column>
    </datasource></datasources></workbook>""")
    r = ED.drop_case_branches(root, ["Aggregator", "Campaign"])
    f = root.find(".//calculation").get("formula")
    assert r["branches_removed"] == 2, r
    assert "Aggregator" not in f and "Campaign" not in f
    assert f.lstrip().startswith("IF [p] = 'Game'"), f
    assert f.rstrip().endswith("END")


def test_live_connection_drops_extract_and_does_not_break_sql():
    root = _tree("""<workbook><datasources>
      <datasource name='Parameters'><column name='[p]'/></datasource>
      <datasource name='federated.x' caption='D'>
        <connection class='federated'>
          <named-connections><named-connection name='textscan.1'/></named-connections>
          <relation name='f.csv' type='table'><columns><column name='a'/></columns></relation>
          <metadata-records><metadata-record class='column'><remote-name>a</remote-name></metadata-record></metadata-records>
        </connection>
        <extract><connection class='hyper'/></extract>
      </datasource></datasources></workbook>""")
    sql = "SELECT 1 WHERE dateDiff('day', a, b) <= 30 AND x >= 1"
    r = ED.to_live_sql(root, sql, [{"name": "Date", "datatype": "date"},
                                   {"name": "GGR", "datatype": "real"}],
                       server="10.0.0.1", port="3306", dbname="marts", username="tableau")
    assert r["sources_switched"] == 1 and r["schema_column_count"] == 2, r

    ds = [d for d in root.findall("./datasources/datasource") if d.get("name") != "Parameters"][0]
    assert ds.find("extract") is None, "the extract must go, otherwise the workbook is live only in looks"
    rel = ds.find("./connection/relation")
    assert rel.get("type") == "text" and rel.text == sql
    inner = ds.find("./connection/named-connections/named-connection/connection")
    assert inner.get("class") == "mysql" and inner.get("username") == "tableau"

    from lxml import etree
    again = safexml.from_bytes(etree.tostring(root))
    assert again.find(".//relation[@type='text']").text == sql

    recs = ds.findall("./connection/metadata-records/metadata-record")
    assert [r.findtext("remote-name") for r in recs] == ["Date", "GGR"]
    assert [r.findtext("parent-name") for r in recs] == ["[Custom SQL Query]"] * 2
    assert [r.findtext("local-type") for r in recs] == ["date", "real"]


def _three_sources():
    def ds(name, caption):
        return (f"<datasource name='{name}' caption='{caption}'><connection class='federated'>"
                f"<relation name='f.csv' type='table'/></connection>"
                f"<extract><connection class='hyper'/></extract></datasource>")
    return _tree("<workbook><datasources>"
                 "<datasource name='Parameters'><column name='[p]'/></datasource>"
                 + ds("federated.a", "VIP") + ds("federated.b", "Cohort data")
                 + ds("federated.c", "Churn segment") + "</datasources></workbook>")


def test_live_connection_switches_ONLY_the_named_source():
    root = _three_sources()
    r = ED.to_live_sql(root, "SELECT 1", [{"name": "a", "datatype": "real"}],
                       server="h", port="3306", dbname="marts", username="tableau",
                       datasource="Cohort data")
    assert r["sources_switched"] == 1, r

    by_caption = {d.get("caption"): d for d in root.findall("./datasources/datasource")
                  if d.get("name") != "Parameters"}
    tgt = by_caption["Cohort data"]
    assert tgt.find("extract") is None
    assert tgt.find("./connection/relation").get("type") == "text"
    for other in ("VIP", "Churn segment"):
        o = by_caption[other]
        assert o.find("extract") is not None, f"{other} was not touched, the extract must stay"
        assert o.find("./connection/relation").get("type") == "table", other


def test_live_connection_finds_source_by_internal_name_too():
    root = _three_sources()
    r = ED.to_live_sql(root, "SELECT 1", [{"name": "a", "datatype": "real"}],
                       server="h", port="3306", dbname="marts", username="tableau",
                       datasource="federated.c")
    assert r["sources_switched"] == 1, r


def test_nonexistent_source_is_an_error_not_a_silent_zero():
    import pytest
    root = _three_sources()
    with pytest.raises(ValueError) as e:
        ED.to_live_sql(root, "SELECT 1", [{"name": "a", "datatype": "real"}],
                       server="h", port="3306", dbname="marts", username="tableau",
                       datasource="Cohort")
    assert "Cohort data" in str(e.value), "the error must list what exists"


def test_sheet_rename_does_not_touch_same_named_field():
    root = _tree("""<workbook>
      <datasources><datasource>
        <column name='[RTP]' caption='RTP'><calculation formula='SUM([Wins])/SUM([Bets])'/></column>
      </datasource></datasources>
      <worksheets><worksheet name='RTP'/><worksheet name='Other'/></worksheets>
      <dashboards><dashboard name='Viz'><zones><zone name='RTP'/></zones>
        <actions><action name='a'><source dashboard='Viz' worksheet='RTP'/>
          <target dashboard='Viz' worksheet='Other'/></action></actions></dashboard></dashboards>
      <windows><window class='worksheet' name='RTP'/>
        <window class='dashboard' name='Viz'><viewpoints><viewpoint name='RTP'/></viewpoints></window>
      </windows></workbook>""")
    r = ED.rename_worksheet(root, "RTP", "RTP trend")
    assert r["renamed"] == 5, r
    names = {w.get("name") for w in root.iter("worksheet")}
    assert names == {"RTP trend", "Other"}
    assert {z.get("name") for z in root.iter("zone")} == {"RTP trend"}
    assert root.find(".//viewpoint").get("name") == "RTP trend"
    assert root.find(".//source").get("worksheet") == "RTP trend"
    col = root.find(".//column")
    assert col.get("name") == "[RTP]" and col.get("caption") == "RTP"
    assert "SUM([Wins])" in col.find("calculation").get("formula")


def test_caption_changes_but_column_name_does_not():
    root = _tree("""<workbook><datasources><datasource>
      <column name='[Parameter 3]' caption='p_measute' param-domain-type='list'/>
    </datasource></datasources></workbook>""")
    assert ED.set_caption(root, "p_measute", "Metric") == 1
    c = root.find(".//column")
    assert c.get("caption") == "Metric"
    assert c.get("name") == "[Parameter 3]", "the column name must not change: the workbook references it"


def test_aggregate_calculation_is_not_wrapped_in_a_second_aggregate():
    root = _tree("""<workbook><datasources><datasource name='ds'>
      <column name='[GGR]' caption='GGR' role='measure' datatype='real'/>
      <column name='[c1]' caption='ARPU' role='measure'>
        <calculation formula='SUM([GGR])/COUNTD([User ID])'/></column>
      <column name='[c2]' caption='Active users' role='measure'>
        <calculation formula='COUNTD([User ID])'/></column>
      <column name='[c3]' caption='Share' role='measure'>
        <calculation formula='SUM([GGR]) / SUM({ FIXED : SUM([GGR]) })'/></column>
      <column name='[c4]' caption='Doubled' role='measure'>
        <calculation formula='[GGR] * 2'/></column>
      <column name='[Game]' caption='Game' role='dimension' datatype='string'/>
    </datasource></datasources></workbook>""")
    got = ED.resolve_fields(root, ["GGR", "ARPU", "Active users", "Share",
                                   "Doubled", "Game"])["fields"]
    assert got == ["SUM([GGR])",
                   "ARPU",
                   "Active users",
                   "Share",
                   "SUM([Doubled])",
                   "Game"], got


def test_aggregate_in_formula_is_recognized():
    assert ED.is_aggregated("SUM([x])")
    assert ED.is_aggregated("countd([User ID])")
    assert ED.is_aggregated("{ FIXED [a] : MAX([b]) }")
    assert not ED.is_aggregated("[a] * 2")
    assert not ED.is_aggregated("IF [a] > 0 THEN [b] END")
    assert not ED.is_aggregated("[SUMMARY] + 1")


def test_field_is_visible_even_without_column_declaration():
    root = _tree("""<workbook><datasources><datasource name='ds'>
      <column name='[GGR]' caption='GGR' role='measure' datatype='real'/>
      <connection class='federated'><metadata-records>
        <metadata-record class='column'><local-name>[Provider]</local-name>
          <local-type>string</local-type></metadata-record>
        <metadata-record class='column'><local-name>[Bets total]</local-name>
          <local-type>real</local-type></metadata-record>
      </metadata-records></connection>
    </datasource></datasources></workbook>""")
    idx = ED.field_index(root)
    assert "Provider" in idx and "Bets total" in idx
    got = ED.resolve_fields(root, ["Provider", "Bets total", "GGR"])
    assert got["not_found"] == []
    # the role is derived from the type: a string is a dimension, a number is a measure with an aggregate
    assert got["fields"] == ["Provider", "SUM([Bets total])", "SUM([GGR])"], got["fields"]


def test_dashboard_is_renamed_in_all_nodes():
    root = _tree("""<workbook>
      <actions>
        <action name='[A1]'>
          <source dashboard='Viz' type='sheet' worksheet='Top players'/>
          <command command='tsc:tsl-filter'>
            <param name='special-fields' value='all'/>
            <param name='target' value='Viz'/>
          </command>
        </action>
      </actions>
      <dashboards>
        <dashboard name='Viz'><zones><zone id='1'><button action='tabdoc:goto-sheet window-id="{U}"'/>
          <caption>Viz</caption></zone></zones></dashboard>
      </dashboards>
      <windows><window class='dashboard' name='Viz'/></windows>
    </workbook>""")
    got = ED.rename_dashboard(root, "Viz", "Trends")
    assert got["dashboard"] == 1 and got["window"] == 1
    assert got["action"] == 2, got
    assert got["button"] == 1
    assert "Viz" not in etree.tostring(root, encoding="unicode")


def test_dashboard_rename_does_not_break_button_address():
    root = _tree("""<workbook><dashboards>
        <dashboard name='Report'><zones><zone id='1'>
          <button action='tabdoc:goto-sheet window-id=&quot;{ABC}&quot;'/></zone></zones></dashboard>
      </dashboards><windows><window class='dashboard' name='Report'/></windows></workbook>""")
    ED.rename_dashboard(root, "Report", "Performance")
    assert root.find(".//button").get("action") == 'tabdoc:goto-sheet window-id="{ABC}"'


def test_tab_order_follows_windows():
    root = _tree("""<workbook>
      <dashboards><dashboard name='A'/><dashboard name='B'/><dashboard name='C'/></dashboards>
      <windows><window class='dashboard' name='A'/><window class='worksheet' name='ws'/>
               <window class='dashboard' name='B'/><window class='dashboard' name='C'/></windows>
    </workbook>""")
    got = ED.reorder_pages(root, ["C", "A"])
    assert got["order"] == 2
    wins = [w.get("name") for w in root.find("windows")]
    assert wins[:2] == ["C", "A"], wins
    assert "ws" in wins
    assert [d.get("name") for d in root.find("dashboards")] == ["C", "A", "B"]


def _heat_book():
    return _tree("""<workbook><worksheets><worksheet name='Provider indicators'><table>
      <view><datasources><datasource name='ds'/></datasources></view>
      <panes><pane><mark class='Text'/>
        <encodings><text column='[ds].[Multiple Values]'/></encodings>
        <style><style-rule element='mark'/></style>
      </pane></panes>
      <rows>[ds].[none:Provider:nk]</rows><cols>[ds].[:Measure Names]</cols>
    </table></worksheet></worksheets></workbook>""")


def test_heat_fill_gives_a_separate_scale_per_measure():
    root = _heat_book()
    assert ED.heat_columns(root, "Provider indicators")["loaded"] == 1
    color = root.find(".//pane/encodings/color")
    assert color.get("separate-domains") == "true", "otherwise all measures are colored on one scale"
    assert color.get("column") == "[ds].[Multiple Values]"
    assert root.find(".//pane/mark").get("class") == "Square"
    assert list(root.find(".//pane/encodings"))[0].tag == "color"


def test_heat_fill_second_time_breaks_nothing():
    root = _heat_book()
    ED.heat_columns(root, "Provider indicators")
    assert ED.heat_columns(root, "Provider indicators")["loaded"] == 0
    assert len(root.findall(".//pane/encodings/color")) == 1


def _combo_book():
    return _tree("""<workbook><datasources><datasource name='ds'>
        <column name='[KPI Margin]' caption='Margin' datatype='real' role='measure'>
          <calculation class='tableau' formula='1-SUM([Wins])/SUM([Bets])'/></column>
      </datasource></datasources>
      <worksheets><worksheet name='GGR by period'><table>
        <view><datasources><datasource name='ds'/></datasources>
          <datasource-dependencies datasource='ds'>
            <column name='[GGR]' datatype='real' role='measure'/>
            <column-instance column='[GGR]' derivation='Sum' name='[sum:GGR:qk]' pivot='key'/>
          </datasource-dependencies></view>
        <panes><pane><mark class='Bar'/>
          <encodings><text column='[ds].[sum:GGR:qk]'/></encodings>
          <style><style-rule element='mark'>
            <format attr='mark-labels-show' value='true'/></style-rule></style>
        </pane></panes>
        <rows>[ds].[sum:GGR:qk]</rows><cols>[ds].[none:Period:ok]</cols>
      </table></worksheet></worksheets></workbook>""")


def test_dual_axis_on_a_pane_without_encodings_keeps_node_order():
    root = _combo_book()
    pane = root.find(".//pane")
    pane.remove(pane.find("encodings"))
    ED.dual_axis(root, "GGR by period", "KPI Margin")
    for p in root.iter("pane"):
        tags = [c.tag for c in p]
        assert tags.index("encodings") < tags.index("style"), tags


def test_second_axis_is_written_with_parentheses_and_plus():
    root = _combo_book()
    got = ED.dual_axis(root, "GGR by period", "KPI Margin", mark="Line", color="#4071f4")
    assert got["axis"] == 1
    rows = root.find(".//rows").text
    assert rows == "([ds].[sum:GGR:qk] + [ds].[usr:KPI Margin:qk])", rows
    panes = root.findall(".//panes/pane")
    assert len(panes) == 3
    assert panes[0].get("id") is None and panes[0].get("y-axis-name") is None
    assert panes[1].get("id") == "1"
    assert panes[1].get("y-axis-name") == "[ds].[sum:GGR:qk]"
    assert panes[1].find("mark").get("class") == "Bar"
    assert panes[2].get("y-axis-name") == "[ds].[usr:KPI Margin:qk]"
    assert panes[2].find("mark").get("class") == "Line"
    assert all(p.get("y-index") is None for p in panes)
    assert panes[2].find("encodings/text") is None


def test_second_axis_declares_the_field_otherwise_sheet_is_dropped():
    root = _combo_book()
    ED.dual_axis(root, "GGR by period", "KPI Margin")
    dep = root.find(".//datasource-dependencies")
    assert dep.find("column[@name='[KPI Margin]']") is not None
    assert dep.find("column[@name='[KPI Margin]']/calculation") is not None
    ci = dep.find("column-instance[@name='[usr:KPI Margin:qk]']")
    assert ci is not None and ci.get("derivation") == "User"


def test_second_axis_is_not_duplicated():
    root = _combo_book()
    ED.dual_axis(root, "GGR by period", "KPI Margin")
    assert ED.dual_axis(root, "GGR by period", "KPI Margin")["axis"] == 0
    assert len(root.findall(".//panes/pane")) == 3


def test_second_axis_refuses_without_field_declaration():
    root = _combo_book()
    got = ED.dual_axis(root, "GGR by period", "No such")
    assert got["axis"] == 0 and "no declaration" in got["why"]


def test_second_axis_finds_field_by_caption():
    root = _combo_book()
    got = ED.dual_axis(root, "GGR by period", "Margin")
    assert got["axis"] == 1
    assert got["measure"] == "[ds].[usr:KPI Margin:qk]", got


def _kpi_book():
    return _tree("""<workbook><datasources><datasource name='ds'>
        <column name='[KPI GGR]' caption='GGR, EUR' datatype='real' role='measure'>
          <calculation class='tableau' formula='SUM([GGR])'/></column>
      </datasource></datasources>
      <worksheets><worksheet name='GGR'><table>
        <view><datasources><datasource name='ds'/></datasources>
          <datasource-dependencies datasource='ds'/></view>
        <panes><pane><mark class='Text'/>
          <encodings><text column='[ds].[usr:KPI GGR:qk]'/></encodings>
          <style><style-rule element='mark'/></style>
        </pane></panes>
      </table></worksheet></worksheets>
      <dashboards><dashboard name='Overview'><zones>
        <zone id='1' name='GGR'/></zones></dashboard></dashboards></workbook>""")


def test_kpi_tile_gives_big_number_and_small_caption():
    root = _kpi_book()
    assert ED.kpi_tile(root, "GGR", "GGR, USD")["tile_count"] == 1
    lab = root.find(".//pane/customized-label/formatted-text")
    runs = list(lab)
    assert [r.get("fontsize") for r in runs] == ["22", None, "9"], "value big, caption small"
    assert runs[-1].text == "GGR, USD"
    assert "[ds].[usr:KPI GGR:qk]" in runs[0].text, "the value is inserted as a field reference"
    pane = root.find(".//pane")
    tags = [c.tag for c in pane]
    assert tags.index("customized-label") == tags.index("encodings") + 1


def test_kpi_tile_can_put_caption_on_top_and_does_not_duplicate():
    root = _kpi_book()
    ED.kpi_tile(root, "GGR", "GGR, USD", caption_below=False)
    runs = list(root.find(".//pane/customized-label/formatted-text"))
    assert runs[0].text == "GGR, USD"
    ED.kpi_tile(root, "GGR", "GGR, USD")
    assert len(root.findall(".//pane/customized-label")) == 1


def test_block_color_is_set_and_reset():
    root = _kpi_book()
    assert ED.set_mark_color(root, "GGR", "#4e79a7") == 1
    ED.set_mark_color(root, "GGR", "#59a14f")
    fmts = root.findall(".//pane/style/style-rule[@element='mark']/format")
    assert [f.get("value") for f in fmts if f.get("attr") == "mark-color"] == ["#59a14f"]


def test_zone_title_is_switched_off_on_dashboard():
    root = _kpi_book()
    assert ED.show_zone_title(root, "Overview", ["GGR"]) == 1
    assert root.find(".//dashboard/zones/zone").get("show-title") == "false"


def _measure_book():
    return _tree("""<workbook><datasources><datasource name='ds'>
        <column name='[GGR]' datatype='real' role='measure'/>
        <column name='[Bets total]' datatype='real' role='measure'/>
        <column name='[Margin]' caption='Margin %' datatype='real' role='measure'>
          <calculation class='tableau' formula='SUM([GGR])/SUM([Bets total])'/></column>
      </datasource></datasources>
      <worksheets><worksheet name='Provider indicators'><table>
        <view><datasources><datasource name='ds'/></datasources>
          <datasource-dependencies datasource='ds'>
            <column name='[GGR]' datatype='real' role='measure'/>
            <column-instance column='[GGR]' derivation='Sum' name='[sum:GGR:qk]'
                             pivot='key' type='quantitative'/>
          </datasource-dependencies>
          <filter class='categorical' column='[ds].[:Measure Names]'>
            <groupfilter function='union'>
              <groupfilter function='member' level='[:Measure Names]'
                           member='"[ds].[sum:GGR:qk]"'/>
            </groupfilter></filter>
        </view>
        <panes><pane><mark class='Text'/>
          <encodings><text column='[ds].[Multiple Values]'/></encodings></pane></panes>
        <rows>[ds].[none:Provider:nk]</rows><cols>[ds].[:Measure Names]</cols>
      </table></worksheet></worksheets></workbook>""")


def test_measure_is_added_to_measure_names_filter_not_to_shelf():
    root = _measure_book()
    assert ED.add_measure(root, "Provider indicators", "Bets total")["added"] == 1
    members = [g.get("member") for g in root.iter("groupfilter") if g.get("member")]
    assert '"[ds].[sum:Bets total:qk]"' in members
    inst = [c.get("name") for c in root.iter("column-instance")]
    assert "[sum:Bets total:qk]" in inst, "without a column-instance Tableau takes the sheet down"
    assert ED.add_measure(root, "Provider indicators", "Bets total")["added"] == 0


def test_calculation_is_added_by_caption_with_derivation_user():
    root = _measure_book()
    ED.add_measure(root, "Provider indicators", "Margin %", "User")
    members = [g.get("member") for g in root.iter("groupfilter") if g.get("member")]
    assert '"[ds].[usr:Margin:qk]"' in members
    dep = root.find(".//datasource-dependencies")
    assert any(c.get("name") == "[Margin]" and c.find("calculation") is not None
               for c in dep.findall("column")), "the formula must move into the sheet"


def test_column_order_otherwise_tableau_sorts_alphabetically():
    root = _measure_book()
    got = ED.order_measures(root, "Provider indicators",
                            ["GGR", "Bets total", "Margin %"], ["Sum", "Sum", "User"])
    assert got["ordered_column_count"] == 3
    buckets = [b.text for b in root.iter("bucket")]
    assert buckets == ['"[ds].[sum:GGR:qk]"', '"[ds].[sum:Bets total:qk]"',
                       '"[ds].[usr:Margin:qk]"']
    ED.order_measures(root, "Provider indicators", ["GGR"], ["Sum"])
    assert len(root.findall(".//datasource/default-sorts")) == 1, "one order per datasource"


def _page_book():
    return _tree("""<workbook><datasources><datasource name='ds'>
        <column name='[Provider]' datatype='string' role='dimension'/>
        <column name='[_period]' datatype='boolean' role='dimension'>
          <calculation class='tableau' formula='[Date]&gt;=[Parameters].[p1]'/></column>
      </datasource></datasources>
      <worksheets>
        <worksheet name='GGR'><table><view>
          <datasources><datasource name='ds'/></datasources>
          <datasource-dependencies datasource='ds'/></view>
          <panes><pane><mark class='Bar'/></pane></panes></table></worksheet>
        <worksheet name='Users'><table><view>
          <datasources><datasource name='ds'/></datasources>
          <datasource-dependencies datasource='ds'/></view>
          <panes><pane><mark class='Bar'/></pane></panes></table></worksheet>
      </worksheets>
      <dashboards><dashboard name='Overview'><zones>
        <zone id='1' x='0' y='0' w='100000' h='100000' type-v2='layout-flow' param='vert'>
          <zone id='2' x='0' y='0' w='100000' h='50000' name='GGR'/>
          <zone id='3' x='0' y='50000' w='100000' h='50000' name='Users'/>
        </zone></zones></dashboard></dashboards></workbook>""")


def test_filter_is_put_in_each_sheet_not_once_per_dashboard():
    root = _page_book()
    got = ED.apply_filter(root, ["GGR", "Users"], "_period", member="true", context=True)
    assert got["sheet_count"] == 2
    for name in ("GGR", "Users"):
        ws = ED._sheet(root, name)
        f = ws.find(".//filter")
        assert f.get("column") == "[ds].[none:_period:nk]"
        assert f.get("context") == "true"
        assert f.find("groupfilter").get("member") == "true"
        assert any(c.get("name") == "[_period]" and c.find("calculation") is not None
                   for c in ws.find(".//datasource-dependencies")), "the formula must move"
        assert [c.text for c in ws.findall(".//slices/column")] == ["[ds].[none:_period:nk]"]
    assert ED.apply_filter(root, ["GGR"], "_period", member="true")["sheet_count"] == 0


def test_control_column_changes_structure_not_coordinates():
    root = _page_book()
    dash = root.find(".//dashboard")
    got = ED.add_control_column(dash, ["[Parameters].[p1]", "GGR|[ds].[none:Provider:nk]"])
    assert got["control_count"] == 2
    row = dash.find("zones/zone")
    assert row.get("param") == "horz", "a horizontal parent appeared"
    kids = list(row)
    assert kids[0].get("param") == "vert" and kids[0].get("id") == "1", "the dashboard body is on the left"
    assert int(kids[0].get("w")) + int(kids[1].get("w")) == 100000, "columns share the width"
    ctrl = list(kids[1])
    assert [z.get("type-v2") for z in ctrl] == ["paramctrl", "filter"]
    assert ctrl[1].get("name") == "GGR", "the filter card is bound to the sheet"
    assert ctrl[1].get("mode") == "checkdropdown", "otherwise a sheet of checkboxes"
    assert ctrl[0].get("mode") == "compact"
    assert ED.add_control_column(dash, ["[Parameters].[p1]"])["column"] == 0


def test_node_goes_to_its_schema_position_not_to_the_end():
    view = etree.fromstring(
        b"<view><datasource-dependencies/><aggregation value='true'/>"
        b"<calcs-on-densified-marks/></view>")
    ED.insert_in_order(view, etree.Element("filter"), ED._VIEW_ORDER)
    ED.insert_in_order(view, etree.Element("slices"), ED._VIEW_ORDER)
    assert [c.tag for c in view] == ["datasource-dependencies", "filter", "slices",
                                     "aggregation", "calcs-on-densified-marks"]


def test_default_sorts_goes_after_style_not_before():
    ds = etree.fromstring(b"<datasource><column/><layout/><style/>"
                          b"<datasource-dependencies/></datasource>")
    ED.insert_in_order(ds, etree.Element("default-sorts"), ED._DS_ORDER)
    assert [c.tag for c in ds] == ["column", "layout", "style", "default-sorts",
                                   "datasource-dependencies"]


def test_sheet_stretch_lives_in_window_not_in_dashboard_zone():
    root = _tree("""<workbook><worksheets>
        <worksheet name='GGR'><table/></worksheet></worksheets>
        <windows><window class='worksheet' name='GGR'><cards/><simple-id/></window>
        </windows></workbook>""")
    assert ED.set_sheet_fit(root, ["GGR"]) == 1
    w = root.find(".//window")
    assert w.find("viewpoint/zoom").get("type") == "entire-view"
    assert [c.tag for c in w] == ["cards", "viewpoint", "simple-id"]
    ED.set_sheet_fit(root, ["GGR"], "standard")
    assert w.find("viewpoint") is None, "Standard is the absence of zoom, not a value"


def test_stretch_in_dashboard_ZONE_lives_in_the_dashboard_window():
    root = _tree("""<workbook><worksheets>
        <worksheet name='GGR'><table/></worksheet></worksheets>
        <dashboards><dashboard name='By segment'><zones>
        <zone name='GGR' id='1'/></zones></dashboard></dashboards>
        <windows>
        <window class='worksheet' name='GGR'><viewpoint><zoom type='fit-width'/></viewpoint></window>
        <window class='dashboard' name='By segment'><viewpoints>
        <viewpoint name='GGR'/></viewpoints></window>
        </windows></workbook>""")
    dash_vp = root.find(".//window[@class='dashboard']/viewpoints/viewpoint")
    assert dash_vp.find("zoom") is None, "Standard initially"
    assert ED.set_sheet_fit(root, ["GGR"], "stretch") == 1
    assert dash_vp.find("zoom") is None, "the sheet window does not fix the dashboard zone"

    assert ED.set_zone_fit(root, "By segment", ["GGR"], "stretch") == 1
    assert dash_vp.find("zoom").get("type") == "entire-view"
    ED.set_zone_fit(root, "By segment", ["GGR"], "standard")
    assert dash_vp.find("zoom") is None, "Standard is the absence of zoom, not a value"
    assert ED.set_zone_fit(root, "Other dashboard", ["GGR"]) == 0, "another dashboard is not touched"


def test_sheet_zone_padding_does_not_go_to_the_filter_card():
    root = _tree("""<workbook><dashboards><dashboard name='By segment'><zones>
        <zone id='1' type-v2='filter' name='GGR' param='[ds].[region]'/>
        <zone id='2' type-v2='NONE' name='GGR'/>
        </zones></dashboard></dashboards></workbook>""")
    assert ED.set_zone_style(root, "By segment", ["GGR"], {"margin": "4"}) == 1
    by_id = {z.get("id"): z for z in root.iter("zone")}
    assert by_id["1"].find("zone-style") is None, "the filter card is not touched"
    assert by_id["2"].find("zone-style/format").get("value") == "4"
    assert ED.set_zone_style(root, "By segment", ["GGR"], {"margin": "4"},
                             controls=True) == 2, "on explicit request, controls too"


def test_repeated_style_rule_silently_drops_the_second():
    root = _tree("""<workbook><worksheets><worksheet name='KPI'><table><style>
        <style-rule element='table'><format attr='background-color' value='#ffffff'/></style-rule>
        <style-rule element='worksheet' scope='cols'><format attr='display-field-labels' value='false'/></style-rule>
        <style-rule element='worksheet' scope='rows'><format attr='display-field-labels' value='false'/></style-rule>
        <style-rule element='table'><format attr='background-color' value='#f5f1f0'/>
                                    <format attr='band-size' value='1'/></style-rule>
        </style></table></worksheet></worksheets></workbook>""")
    assert ED.dedupe_style_rules(root, ["KPI"]) == {"KPI": 1}
    st = root.find(".//style")
    tables = [r for r in st.findall("style-rule") if r.get("element") == "table"]
    assert len(tables) == 1, "one rule per element"
    fmt = {f.get("attr"): f.get("value") for f in tables[0].findall("format")}
    assert fmt == {"background-color": "#f5f1f0", "band-size": "1"}, "the last value wins"
    assert len([r for r in st.findall("style-rule")
                if r.get("element") == "worksheet"]) == 2, "scope is a legitimate repeat, not touched"


def test_tile_without_caption_gets_no_empty_line():
    root = _kpi_book()
    ED.kpi_tile(root, "GGR", "", value_size="28")
    runs = root.findall(".//customized-label/formatted-text/run")
    assert len(runs) == 1, "one run, the value only"
    assert runs[0].get("fontsize") == "28"
    ED.kpi_tile(root, "GGR", "GGR, USD", value_size="28")
    assert len(root.findall(".//customized-label/formatted-text/run")) == 3


def _kpi_grid():
    return _tree("""<workbook><dashboards><dashboard name='Old Users'><zones>
        <zone id='17' type-v2='layout-flow' param='horz' fixed-size='140' is-fixed='true'>
          <zone id='18' type-v2='layout-flow' param='vert'>
            <zone id='19' type-v2='text' fixed-size='30' is-fixed='true'/>
            <zone id='20' name='KPI A'/>
            <zone-style><format attr='background-color' value='#ffffff'/></zone-style>
          </zone>
          <zone id='21' type-v2='layout-flow' param='vert'>
            <zone id='22' type-v2='text' fixed-size='30' is-fixed='true'/>
            <zone id='23' name='KPI B'/>
          </zone>
          <zone-style><format attr='border-style' value='none'/></zone-style>
        </zone></zones></dashboard></dashboards></workbook>""")


def test_grid_transpose_moves_size_from_element_to_row():
    root = _kpi_grid()
    out = ED.transpose_flow(root, "Old Users", 17)
    assert out["expanded"] == 2
    outer = next(z for z in root.iter("zone") if z.get("id") == "17")
    assert outer.get("param") == "vert", "the outer flow turned over"
    rows = outer.findall("zone")
    assert [r.get("param") for r in rows] == ["horz", "horz"]
    assert rows[0].get("fixed-size") == "30" and rows[0].get("is-fixed") == "true"
    assert [z.get("id") for z in rows[0].findall("zone")] == ["19", "22"]
    assert [z.get("id") for z in rows[1].findall("zone")] == ["20", "23"]
    assert rows[0].findall("zone")[0].get("fixed-size") is None, "the size moved to the row"
    assert rows[1].get("fixed-size") is None, "the value row stretches itself"
    assert [c.tag for c in outer] == ["zone", "zone", "zone-style"]
    ids = [z.get("id") for z in root.iter("zone")]
    assert len(ids) == len(set(ids))
    assert out["columns_removed"][0]["background"] == "#ffffff", "the column background was named aloud"


def test_transpose_refuses_on_uneven_grid():
    root = _kpi_grid()
    col = next(z for z in root.iter("zone") if z.get("id") == "21")
    col.remove(col.findall("zone")[1])
    out = ED.transpose_flow(root, "Old Users", 17)
    assert out["expanded"] == 0 and "different item counts" in out["why"]
    assert next(z for z in root.iter("zone") if z.get("id") == "17").get("param") == "horz"


def test_sign_color_gives_each_measure_its_own_scale():
    root = _tree("""<workbook><worksheets><worksheet name='T'><table>
        <view><datasources><datasource name='federated.x'/></datasources></view>
        <style><style-rule element='mark'>
          <encoding attr='color' field='[federated.x].[:Measure Names]' type='palette'>
            <map to='#4a7ba7'><bucket>"a"</bucket></map></encoding>
        </style-rule></style>
        <panes><pane><encodings>
          <color column='[federated.x].[:Measure Names]'/>
          <text column='[federated.x].[Multiple Values]'/>
        </encodings></pane></panes></table></worksheet></worksheets></workbook>""")
    out = ED.sign_color(root, ["T"], {"usr:P1:qk": "Just black",
                                      "usr:D:qk": "red_green_diverging_10_0"})
    assert out == {"T": 2}
    col = root.find(".//pane/encodings/color")
    assert col.get("column") == "[federated.x].[Multiple Values]", \
        "Measure VALUES are on Color, otherwise the encoding is categorical"
    assert col.get("separate-domains") == "true", \
        "\"Use Separate Legends\": without it measures share a scale and everything comes out dull"
    encs = root.findall(".//style-rule[@element='mark']/encoding")
    assert len(encs) == 3, "an umbrella on [Multiple Values] + an encoding per measure"
    assert encs[0].get("field").endswith("[Multiple Values]"), "the umbrella comes first"
    encs = encs[1:]
    assert not root.findall(".//map"), "categorical coloring by columns is removed"
    e = encs[1]
    assert e.get("type") == "interpolated" and e.get("palette") == "red_green_diverging_10_0"
    assert e.find("color-palette") is None, "an inline palette at measure level does not work"
    assert e.get("center") == "0", "the middle of a diverging scale sits on zero"
    assert encs[0].get("palette") == "Just black" and encs[0].get("center") is None


def test_sharp_transition_palette_gives_no_muddy_middle():
    p = ED.palette_stops(("#c4813c", "#4f8a5b"))
    assert len(p) == ED.PALETTE_STOPS
    assert set(p) == {"#c4813c", "#4f8a5b"}, "no intermediate mixtures"
    breaks = [i for i in range(1, len(p)) if p[i] != p[i - 1]]
    assert breaks == [len(p) // 2], "exactly one break, exactly in the middle"


def test_constant_color_does_not_fade():
    assert set(ED.palette_stops("#1f4e79")) == {"#1f4e79"}
    assert set(ED.palette_stops(("#1f4e79", "#1f4e79"))) == {"#1f4e79"}


def test_gradient_passes_through_the_given_colors():
    g = ED.interpolate_colors(["#000000", "#ffffff"], 3)
    assert g == ["#000000", "#808080", "#ffffff"]
    g3 = ED.palette_stops(["#c4813c", "#d9d9d9", "#4f8a5b"])
    assert g3[0] == "#c4813c" and g3[-1] == "#4f8a5b"
    assert len(set(g3)) > 10, "this is a gradient, not two bins"


def test_coloring_is_copied_from_the_donor_sheet_as_is():
    def sheet_xml(name, colors=None):
        pal = ""
        if colors:
            pal = ("<color-palette custom='true' name='' type='ordered-diverging'>"
                   + "".join(f"<color>{c}</color>" for c in colors) + "</color-palette>")
        enc = (f"<encoding attr='color' field='[federated.x].[usr:P1:qk]' "
               f"type='custom-interpolated'>{pal}</encoding>") if colors else ""
        return (f"<worksheet name='{name}'><table>"
                "<view><datasources><datasource name='federated.x'/></datasources></view>"
                f"<style><style-rule element='mark'>{enc}"
                "<format attr='mark-labels-show' value='true'/></style-rule></style>"
                "<panes><pane><encodings>"
                + ("<color column='[federated.x].[Multiple Values]' separate-domains='true'/>"
                   if colors else "")
                + "<text column='[federated.x].[Multiple Values]'/>"
                "</encodings></pane></panes></table></worksheet>")

    root = _tree("<workbook><worksheets>"
                 + sheet_xml("donor", ["#2b5c8a", "#d9d9d9", "#2b5c8a"])
                 + sheet_xml("target") + "</worksheets></workbook>")
    out = ED.copy_color_encoding(root, "donor", ["target"])
    assert out["moved"] == 1
    target_ws = next(w for w in root.iter("worksheet") if w.get("name") == "target")
    col = target_ws.find("table/panes/pane/encodings/color")
    assert col is not None and col.get("separate-domains") == "true"
    e = target_ws.find("table/style/style-rule/encoding")
    assert [c.text for c in e.findall("color-palette/color")] == ["#2b5c8a", "#d9d9d9", "#2b5c8a"], \
        "the measure's own palette is copied whole, not rebuilt"
    ED.copy_color_encoding(root, "donor", ["target"])
    assert len(target_ws.findall("table/style/style-rule/encoding")) == 1
    assert ED.copy_color_encoding(root, "no such", ["target"])["moved"] == 0


def test_stepped_color_removes_the_middle_tone():
    root = _tree("""<workbook><worksheets><worksheet name='T'><table>
        <style><style-rule element='mark'>
          <encoding attr='color' field='[ds].[a]' type='custom-interpolated'/>
          <encoding attr='color' field='[ds].[b]' palette='red_green_diverging_10_0'
                    center='0' type='interpolated'/>
          <format attr='mark-labels-show' value='true'/>
        </style-rule></style></table></worksheet></worksheets></workbook>""")
    out = ED.set_color_steps(root, ["T"], 2)
    assert out == {"sheet_count": 1, "steps": 2, "encodings_per_sheet": [2]}
    steps = [e.get("num-steps") for e in root.findall(".//style-rule/encoding")]
    assert steps == ["2", "2"], "steps are set on ALL color encodings of the sheet"
    assert root.find(".//format").get("attr") == "mark-labels-show", "the format is not touched"
    ED.set_color_steps(root, ["T"], 0)
    assert [e.get("num-steps") for e in root.findall(".//style-rule/encoding")] == [None, None], \
        "0 means remove steps, not set zero bins"


def test_second_measure_label_shows_ITS_value_not_the_first():
    root = _combo_book()
    ED.dual_axis(root, "GGR by period", "KPI Margin", labels=True)
    panes = root.findall(".//panes/pane")
    assert panes[1].find("encodings/text").get("column") == "[ds].[sum:GGR:qk]"
    assert panes[2].find("encodings/text").get("column") == "[ds].[usr:KPI Margin:qk]"


def test_tile_gets_a_card_not_bare_digits():
    root = _kpi_book()
    assert ED.set_zone_style(root, "Overview", ["GGR"], ED.KPI_CARD) == 1
    z = next(z for z in root.iter("zone") if z.get("name") == "GGR")
    fmt = {f.get("attr"): f.get("value") for f in z.findall("zone-style/format")}
    assert fmt["background-color"] == "#f6f6f4" and fmt["padding"] == "12"
    ED.set_zone_style(root, "Overview", ["GGR"], {"padding": "20"})
    assert len(z.findall("zone-style")) == 1
    assert z.find("zone-style/format[@attr='padding']").get("value") == "20"


def test_fill_scale_is_one_per_table_not_per_measure():
    root = _measure_book()
    ED.add_measure(root, "Provider indicators", "Bets total")
    ED.heat_columns(root, "Provider indicators")
    encs = root.findall("./worksheets/worksheet/table/style/style-rule[@element='mark']/encoding")
    fields = [e.get("field") for e in encs]
    assert fields[0] == "[ds].[Multiple Values]", fields
    assert encs[0].get("type") == "custom-interpolated"
    assert encs[0].get("symmetric") == "false"
    assert "[ds].[sum:GGR:qk]" in fields and "[ds].[sum:Bets total:qk]" in fields
    per = [e for e in encs[1:]]
    assert all(e.get("type") == "interpolated" for e in per), \
        "at measure level a custom palette is not applied; Tableau colors with its own dark one"
    assert all(e.get("palette") for e in per)
    assert root.find(".//pane/encodings/color").get("separate-domains") == "true"


def test_heat_fill_is_reachable_by_the_other_color_tools():
    root = _measure_book()
    ED.heat_columns(root, "Provider indicators")
    assert root.find(".//pane/style/style-rule/encoding") is None
    assert root.find(".//pane/style/style-rule/format[@attr='mark-labels-show']") is not None
    assert ED.set_color_range(root, ["Provider indicators"])["encodings"] >= 2
    assert ED.set_color_steps(root, ["Provider indicators"], 2)["sheet_count"] == 1


def test_second_axis_is_marked_by_space_encoding_with_fold():
    root = _combo_book()
    ED.dual_axis(root, "GGR by period", "KPI Margin")
    e = root.find(".//style/style-rule[@element='axis']/encoding")
    assert e.get("attr") == "space" and e.get("scope") == "rows"
    assert e.get("fold") == "true" and e.get("field-type") == "quantitative"
    assert e.get("field") == "[ds].[usr:KPI Margin:qk]"


def test_second_axis_adds_color_by_measure_names_to_each_pane():
    root = _combo_book()
    ED.dual_axis(root, "GGR by period", "KPI Margin")
    panes = root.findall(".//panes/pane")
    assert len(panes) == 3
    for pane in panes:
        col = pane.find("encodings/color")
        assert col is not None and col.get("column") == "[ds].[:Measure Names]"


def test_passport_turns_shelf_references_into_human_names():
    from twkit import docs

    caps = {"Calculation_BBD497": "Margin", "GGR": "GGR"}
    assert docs._plain("[federated.x].[sum:GGR:qk]", caps) == "SUM(GGR)"
    assert docs._plain("[federated.x].[ctd:User ID:qk]", caps) == "COUNTD(User ID)"
    assert docs._plain("[federated.x].[usr:Calculation_BBD497:qk]", caps) == "Margin"
    assert docs._plain("[federated.x].[tdy:Date:ok]", caps) == "Date (day)"
    assert docs._plain("[federated.x].[usr:Calculation_BBD497:ok:1]", caps) == "Margin"
    assert docs._plain("[:Measure Names]", caps) == "Measure Names"


def test_field_role_comes_from_the_prefix_not_from_the_caption_look():
    from twkit import docs

    got = docs._shelf("[federated.x].[tdy:Date:ok] / [federated.x].[sum:GGR:qk]", {})
    assert got == [("Date (day)", "dimension"), ("SUM(GGR)", "measure")]


def test_human_written_report_description_survives_rebuild(tmp_path):
    from twkit import docs

    md = tmp_path / "r.md"
    md.write_text("# Report\n\nComputes the deposit funnel for managers.\n\n"
                  "## Report sections\n\nold\n", encoding="utf-8")
    assert docs.keep_description(str(md)) == "Computes the deposit funnel for managers."
    md.write_text("# Report\n\n> _Report description: ..._\n\n## Report sections\n", encoding="utf-8")
    assert docs.keep_description(str(md)) == "", "a placeholder is not accepted as a description"


def test_description_is_not_lost_when_the_guide_is_rebuilt(tmp_path):
    from twkit import docs

    md = tmp_path / "R.md"
    md.write_text("# R\n\nComputes the deposit funnel.\n\n## Report sections\n\nold\n",
                  encoding="utf-8")
    was = docs.keep_description(str(md))
    text = docs.render({"book": "R", "source": {}, "parameters": [],
                        "pages": [], "sheets": {}, "formulas": []}, description=was)
    md.write_text(text, encoding="utf-8")
    assert "Computes the deposit funnel." in md.read_text(encoding="utf-8")
    assert docs.keep_description(str(md)) == "Computes the deposit funnel."


def test_diff_of_two_books_shows_the_idiom_of_one_action(tmp_path):
    import zipfile

    from twkit import idiom

    def book(path, extra):
        xml = ("<?xml version='1.0' encoding='utf-8' ?>\n<workbook version='18.1'>"
               "<worksheets><worksheet name='bar'><table><panes>"
               f"<pane><mark class='Bar'/>{extra}</pane>"
               "</panes><rows>[ds].[sum:GGR:qk]</rows></table>"
               "<simple-id uuid='{CHANGES}'/></worksheet></worksheets></workbook>")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("b.twb", xml)
        return str(path)

    a = book(tmp_path / "before.twbx", "")
    b = book(tmp_path / "after.twbx",
             "<encodings><color column='[ds].[Multiple Values]' "
             "separate-domains='true'/></encodings>")
    got = idiom.diff_books(a, b)
    assert "differences" in got["verdict"]
    appeared = " ".join(str(x) for x in got["appeared"])
    assert "separate-domains" in appeared and "Multiple Values" in appeared
    assert "uuid" not in (appeared + str(got["changed"]))

    assert idiom.diff_books(a, a)["appeared"] == []


def test_column_width_is_fitted_for_distinctness(root):
    from twkit import dryrun as DR
    from twkit import layoutmodel as LM

    sheet = "[D] CR full tab"
    labels = ["Affiliates_Anton_traffic", "Affiliates_Asankha_traffic", "Visa"]

    got = ED.fit_column_width(root, sheet, "provider", labels, max_px=400)
    assert got["width"] > 0, got["verdict"]

    ws = next(w for w in root.iter("worksheet") if w.get("name") == sheet)
    pt, family, _ = LM.sheet_font(ws)
    assert not DR.indistinct_after_truncation(
        labels, got["width"] - DR.CELL_PADDING_PX, pt, family)
    assert DR.indistinct_after_truncation(
        labels, got["width"] - 1 - DR.CELL_PADDING_PX, pt, family), \
        "the width is not minimal: the column is bloated beyond need"

    assert str(got["width"]) in etree.tostring(ws, encoding="unicode")


def test_fit_never_squeezes_short_labels_below_what_tableau_keeps(root):
    labels = ["Germany", "France", "Spain", "Italy", "Poland", "Austria"]
    got = ED.fit_column_width(root, "[D] CR full tab", "provider", labels, max_px=400)
    from twkit import layoutmodel as LM
    ws = next(w for w in root.iter("worksheet") if w.get("name") == "[D] CR full tab")
    pt, family, _ = LM.sheet_font(ws)
    full = max(LM.text_width(x, pt, family) for x in labels)
    assert got["width"] >= min(full, ED.ROW_HEADER_FLOOR_PX), got["verdict"]


def test_duplicate_labels_do_not_break_the_fit(root):
    got = ED.fit_column_width(root, "[D] CR full tab", "provider",
                              ["Visa", "Visa", "Mastercard"], max_px=400)
    assert got["width"] > 0, got["verdict"]
    assert got["width"] < 100, "repeats bloated the column: they were counted as a conflict"


def test_one_label_is_no_reason_to_set_a_width(root):
    got = ED.fit_column_width(root, "[D] CR full tab", "provider", ["Visa"], max_px=400)
    assert got["width"] == 0
    assert "no edit needed" in got["verdict"]


def test_width_does_not_lie_when_it_exceeds_the_limit(root):
    long_a = "Affiliates_" + "x" * 60 + "_A"
    long_b = "Affiliates_" + "x" * 60 + "_B"
    got = ED.fit_column_width(root, "[D] CR full tab", "provider",
                              [long_a, long_b], max_px=100)
    assert got["width"] == 0
    assert got["needed"] > 100
    assert "100 allowed" in got["verdict"]


def test_total_is_enabled_by_shelf_attributes(root):
    sheet = "[D] CR full tab"
    got = ED.set_grand_total(root, sheet, rows=True, cols=True, on_top=True)
    assert got["shelf_count"] > 0, got["verdict"]

    ws = next(w for w in root.iter("worksheet") if w.get("name") == sheet)
    rows_el = ws.find(".//rows")
    cols_el = ws.find(".//cols")
    assert rows_el.get("total") == "true"
    assert rows_el.get("onTop") == "true", "convention: the row total is on top"
    assert cols_el.get("total") == "true"
    assert cols_el.get("onLeft") is None


def test_bottom_total_leaves_no_onTop(root):
    sheet = "[D] CR full tab"
    ED.set_grand_total(root, sheet, rows=True, on_top=True)
    ED.set_grand_total(root, sheet, rows=True, on_top=False)
    rows_el = next(w for w in root.iter("worksheet")
                   if w.get("name") == sheet).find(".//rows")
    assert rows_el.get("total") == "true"
    assert rows_el.get("onTop") is None


def test_total_on_nonexistent_sheet_is_not_silent(root):
    got = ED.set_grand_total(root, "no such sheet", rows=True)
    assert got["shelf_count"] == 0
    assert "no sheet" in got["verdict"]


def test_use_full_color_range_is_written_as_an_inverted_attribute():
    root = _tree("""<workbook><worksheets><worksheet name='T'><table>
        <style><style-rule element='mark'>
          <encoding attr='color' field='[ds].[a]' type='interpolated'/>
          <encoding attr='color' field='[ds].[b]' type='interpolated' reverse='true'/>
        </style-rule></style></table></worksheet></worksheets></workbook>""")
    out = ED.set_color_range(root, ["T"], full_range=True)
    assert out["sheets"] == 1 and out["encodings"] == 2
    encs = root.findall(".//style-rule/encoding")
    assert [e.get("symmetric") for e in encs] == ["false", "false"], \
        "the checkbox is ON, which means symmetric='false'"
    assert encs[1].get("reverse") == "true", "reversed is left alone until asked"

    ED.set_color_range(root, ["T"], full_range=False, reversed_scale=False)
    encs = root.findall(".//style-rule/encoding")
    assert [e.get("symmetric") for e in encs] == ["true", "true"]
    assert all(e.get("reverse") is None for e in encs), "a cleared reversed is removed entirely"


def test_parameter_item_is_appended_and_not_doubled():
    root = _tree("""<workbook><datasources><datasource name='Parameters'>
      <column caption='Level 1' name='[p1]' param-domain-type='list' value='&quot;Country&quot;'>
        <calculation formula='&quot;Country&quot;'/>
        <members>
          <member value='&quot;Country&quot;'/>
        </members>
      </column>
      <column caption='Metric' name='[p2]' param-domain-type='list' value='&quot;GGR&quot;'>
        <members><member value='&quot;GGR&quot;'/></members>
      </column>
    </datasource></datasources></workbook>""")
    r = ED.add_param_members(root, ["Level 1"], ["VIP", "RFM segment"])
    assert r["members_added"] == 2, r
    vals = [m.get("value") for m in root.find(".//column[@caption='Level 1']/members")]
    assert vals == ['"Country"', '"VIP"', '"RFM segment"'], vals
    assert len(root.find(".//column[@caption='Metric']/members")) == 1
    again = ED.add_param_members(root, ["Level 1"], ["VIP"])
    assert again["members_added"] == 0 and again["skipped_existing"] == 1


def test_case_branch_is_appended_before_end():
    root = _tree("""<workbook><datasources><datasource name='ds'>
      <column caption=' Level 1' name='[L1]'>
        <calculation formula="CASE [Parameters].[p1]&#10;WHEN 'Country' THEN [country_user]&#10;END"/>
      </column>
      <column caption='Deposits' name='[D]'><calculation formula='SUM([dep_sum])'/></column>
    </datasource></datasources></workbook>""")
    r = ED.add_case_branches(root, [" Level 1"], {"VIP": "[vip_status]"})
    assert r["branches_added"] == 1, r
    f = root.find(".//column[@caption=' Level 1']/calculation").get("formula")
    assert f.endswith("WHEN 'VIP' THEN [vip_status]\nEND"), f
    assert root.find(".//column[@caption='Deposits']/calculation").get("formula") == "SUM([dep_sum])"
    assert ED.add_case_branches(root, [" Level 1"], {"VIP": "[vip_status]"})["branches_added"] == 0


def test_zone_goes_behind_button_with_descendants():
    root = _tree("""<workbook><dashboards><dashboard name='Relative Dates'><zones>
      <zone id='5' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>
        <zone id='31' name='table' x='0' y='18000' w='35000' h='80000'/>
        <zone id='28' name='chart1' x='36000' y='18000' w='52000' h='80000'>
          <zone id='99' name='inner' x='36000' y='18000' w='52000' h='80000'/>
        </zone>
        <zone id='29' name='legend' type-v2='color' x='89000' y='18000' w='11000' h='80000'/>
      </zone>
    </zones></dashboard></dashboards>
    <windows><window class='dashboard' name='Relative Dates'/></windows></workbook>""")
    r = ED.zone_hide_button(root, "Relative Dates", ["chart1", "legend:color"], ["table"])
    row = root.find(f".//zone[@id='{r['container']}']")
    assert row.get("type-v2") == "layout-flow" and row.get("param") == "horz"
    box = root.find(f".//zone[@id='{r['collapsed_container']}']")
    assert box.get("hidden-by-user") == "true"
    assert [z.get("name") for z in box.findall("zone")] == ["chart1", "legend"]
    assert root.find(".//zone[@id='99']").get("hidden-by-user") == "true"
    assert root.find(".//zone[@name='table']").getparent() is row
    assert root.find(".//zone[@name='table']").get("hidden-by-user") is None


def test_button_refuses_to_wrap_zones_from_different_containers():
    root = _tree("""<workbook><dashboards><dashboard name='D'><zones>
      <zone id='1' type-v2='layout-basic' x='0' y='0' w='100' h='100'>
        <zone id='2' type-v2='layout-flow' x='0' y='0' w='50' h='100'>
          <zone id='3' name='a' x='0' y='0' w='50' h='100'/>
        </zone>
        <zone id='4' name='b' x='50' y='0' w='50' h='100'/>
      </zone>
    </zones></dashboard></dashboards>
    <windows><window class='dashboard' name='D'/></windows></workbook>""")
    with pytest.raises(ValueError, match="different containers"):
        ED.zone_hide_button(root, "D", ["a"], ["b"])


def test_button_does_not_confuse_a_sheet_with_its_filter_card():
    root = _tree("""<workbook><dashboards><dashboard name='D'><zones>
      <zone id='1' type-v2='layout-basic' x='0' y='0' w='100' h='100'>
        <zone id='2' type-v2='filter' name='chart1' x='0' y='0' w='50' h='10'/>
        <zone id='3' name='chart1' x='0' y='10' w='50' h='90'/>
        <zone id='4' name='table' x='50' y='10' w='50' h='90'/>
      </zone>
    </zones></dashboard></dashboards>
    <windows><window class='dashboard' name='D'/></windows></workbook>""")
    r = ED.zone_hide_button(root, "D", ["chart1"], ["table"])
    box = root.find(f".//zone[@id='{r['collapsed_container']}']")
    assert [z.get("id") for z in box.findall("zone")] == ["3"]
    assert root.find(".//zone[@id='2']").get("hidden-by-user") is None


def test_button_refuses_when_there_is_no_zone():
    root = _tree("""<workbook><dashboards><dashboard name='D'><zones>
      <zone id='1' type-v2='layout-basic' x='0' y='0' w='100' h='100'>
        <zone id='3' name='chart1' x='0' y='0' w='50' h='100'/>
      </zone>
    </zones></dashboard></dashboards>
    <windows><window class='dashboard' name='D'/></windows></workbook>""")
    with pytest.raises(ValueError, match="no zone"):
        ED.zone_hide_button(root, "D", ["chart1"], ["nosuch"])


def test_caption_with_edge_space_is_still_found():
    root = _tree("""<workbook><datasources><datasource name='ds'>
      <column caption=' Level 1' name='[L1]'>
        <calculation formula="CASE [p]&#10;WHEN 'Country' THEN [country_user]&#10;END"/>
      </column>
      <column caption='lable' name='[lbl]'>
        <calculation formula="CASE [p4]&#10;WHEN 'Margin %' THEN '%'&#10;ELSE ''&#10;END"/>
      </column>
    </datasource></datasources></workbook>""")
    r = ED.add_case_branches(root, ["Level 1"], {"VIP": "[vip_status]"})
    assert r["branches_added"] == 1, r
    assert "VIP" not in root.find(".//column[@caption='lable']/calculation").get("formula")


def test_button_creates_a_floating_zone_with_toggle_action():
    root = _tree("""<workbook><dashboards><dashboard name='D'><zones>
      <zone id='1' type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>
        <zone id='3' name='chart1' x='40000' y='18000' w='55000' h='80000'/>
        <zone id='4' name='table' x='0' y='18000' w='40000' h='80000'/>
      </zone>
    </zones></dashboard></dashboards>
    <windows><window class='dashboard' name='D'><simple-id uuid='{ABC}'/></window></windows></workbook>""")
    r = ED.zone_hide_button(root, "D", ["chart1"], ["table"])
    btn = root.find(f".//zone[@id='{r['button']}']")
    assert btn.get("type-v2") == "dashboard-object"
    assert btn.getparent().tag == "zones"
    act = btn.find("button/toggle-action").text
    assert 'window-id="{ABC}"' in act, act
    assert f'zone-id="{r["button"]}"' in act and f'zone-ids=[{r["collapsed_container"]}]' in act, act
    assert btn.find("button").get("active-visual-state-index") == "1"
    assert len(btn.findall("button/button-visual-state")) == 2


def test_button_can_start_expanded():
    root = _tree("""<workbook><dashboards><dashboard name='D'><zones>
      <zone id='1' type-v2='layout-basic' x='0' y='0' w='100' h='100'>
        <zone id='3' name='chart1' x='50' y='0' w='50' h='100'/>
        <zone id='4' name='table' x='0' y='0' w='50' h='100'/>
      </zone>
    </zones></dashboard></dashboards>
    <windows><window class='dashboard' name='D'/></windows></workbook>""")
    r = ED.zone_hide_button(root, "D", ["chart1"], ["table"], hidden=False)
    assert root.find(".//zone[@id='3']").get("hidden-by-user") is None
    assert root.find(f".//zone[@id='{r['collapsed_container']}']").get("hidden-by-user") is None
    assert root.find(f".//zone[@id='{r['button']}']/button").get("active-visual-state-index") is None
    assert root.find(".//windows/window/simple-id").get("uuid").startswith("{")


def test_dropping_is_addressed_by_parameter_and_formula():
    root = _tree(r"""<workbook><datasources><datasource name='ds'>
      <column caption='Level 1' name='[p1]' param-domain-type='list' value='&quot;Country&quot;'>
        <members><member value='&quot;Country&quot;'/><member value='&quot;first day RTP \%&quot;'/></members>
      </column>
      <column caption='Metric' name='[p4]' param-domain-type='list' value='&quot;GGR&quot;'>
        <members><member value='&quot;GGR&quot;'/><member value='&quot;first day RTP \%&quot;'/></members>
      </column>
      <column caption=' Level 1' name='[L1]'>
        <calculation formula="CASE [p1]&#10;WHEN 'Country' THEN [c]&#10;WHEN 'first day RTP \%' THEN [r]&#10;END"/>
      </column>
      <column caption='Metric switch' name='[M]'>
        <calculation formula="CASE [p4]&#10;WHEN 'GGR' THEN SUM([ggr])&#10;WHEN 'first day RTP \%' THEN [r]&#10;END"/>
      </column>
    </datasource></datasources></workbook>""")
    ED.drop_param_members(root, ["first day RTP \\%"], ["Level 1"])
    ED.drop_case_branches(root, ["first day RTP \\%"], [" Level 1"])
    assert len(root.find(".//column[@caption='Level 1']/members")) == 1
    assert len(root.find(".//column[@caption='Metric']/members")) == 2
    assert "first day RTP" not in root.find(".//column[@caption=' Level 1']/calculation").get("formula")
    assert "first day RTP" in root.find(".//column[@caption='Metric switch']/calculation").get("formula")


def test_button_declares_format_capabilities_in_the_manifest():
    root = _tree("""<workbook><document-format-change-manifest><CascadingFilters/></document-format-change-manifest>
    <dashboards><dashboard name='D'><zones>
      <zone id='1' type-v2='layout-basic' x='0' y='0' w='100' h='100'>
        <zone id='3' name='chart1' x='50' y='0' w='50' h='100'/>
        <zone id='4' name='table' x='0' y='0' w='50' h='100'/>
      </zone>
    </zones></dashboard></dashboards>
    <windows><window class='dashboard' name='D'/></windows></workbook>""")
    ED.zone_hide_button(root, "D", ["chart1"], ["table"])
    have = {e.tag for e in root.find("document-format-change-manifest")}
    assert {"BasicButtonObject", "CollapsiblePane", "ZoneVisibilityControl"} <= have, have
    assert "CascadingFilters" in have


def test_button_keeps_the_order_of_visible_zones():
    root = _tree("""<workbook><dashboards><dashboard name='D'><zones>
      <zone id='1' type-v2='layout-basic' x='0' y='0' w='100' h='100'>
        <zone id='2' name='table' x='0' y='0' w='40' h='100'/>
        <zone id='3' name='chart' x='40' y='0' w='40' h='100'/>
        <zone id='4' name='chart' type-v2='color' x='80' y='0' w='20' h='100'/>
      </zone>
    </zones></dashboard></dashboards>
    <windows><window class='dashboard' name='D'/></windows></workbook>""")
    r = ED.zone_hide_button(root, "D", ["chart"], ["table", "chart:color"])
    row = root.find(f".//zone[@id='{r['container']}']")
    assert [z.get("id") for z in row.findall("zone")] == ["2", "4", str(r["collapsed_container"])]


def test_zone_text_is_rewritten_with_line_breaks():
    root = _tree("""<workbook><dashboards><dashboard name='Description'><zones>
      <zone id='4' type-v2='layout-basic' x='0' y='0' w='100' h='100'>
        <zone id='3' type-v2='text' x='0' y='0' w='100' h='100'>
          <formatted-text><run>previous text</run></formatted-text>
          <zone-style><format attr='margin' value='4'/></zone-style>
        </zone>
      </zone>
    </zones></dashboard></dashboards></workbook>""")
    r = ED.zone_text(root, "Description", "# Cohort\nmonth FTD\n\ntail")
    assert r["zone"] == "3" and r["headings"] == 1, r
    ft = root.find(".//zone[@id='3']/formatted-text")
    runs = list(ft)
    assert runs[0].get("bold") == "true" and runs[0].text == "Cohort"
    assert "previous text" not in etree.tostring(ft, encoding="unicode")
    assert sum(1 for x in runs if x.text == "\u00c6\n") == 3
    assert [x.text for x in runs if x.get("fontsize")] == ["Cohort", "month FTD", "tail"]
    assert list(root.find(".//zone[@id='3']"))[0].tag == "formatted-text"


def test_zone_text_refuses_to_choose_for_us():
    root = _tree("""<workbook><dashboards><dashboard name='D'><zones>
      <zone id='1' type-v2='layout-basic' x='0' y='0' w='100' h='100'>
        <zone id='2' type-v2='text' x='0' y='0' w='50' h='100'/>
        <zone id='3' type-v2='text' x='50' y='0' w='50' h='100'/>
      </zone>
    </zones></dashboard></dashboards></workbook>""")
    with pytest.raises(ValueError, match="zone_id is required"):
        ED.zone_text(root, "D", "text")
    assert ED.zone_text(root, "D", "text", zone_id="3")["zone"] == "3"


def _two_fields():
    return _tree("""<workbook><datasources><datasource name='ds'>
      <column name='[Calculation_111]' caption='Deposits'><calculation formula='SUM([dep_sum])'/></column>
      <column name='[Calculation_222]' caption='GGR'><calculation formula='[Calculation_111] * 2'/></column>
    </datasource></datasources>
    <worksheets><worksheet name='w'><rows>[ds].[usr:Calculation_111:qk]</rows></worksheet></worksheets>
    </workbook>""")


def test_batch_rename_edits_formulas_and_shelves():
    root = _two_fields()
    r = ED.rename_fields(root, {"Calculation_111": "Deposits", "Calculation_222": "GGR"})
    assert r["field_count"] == 2 and r["replacements"] > 0, r
    blob = etree.tostring(root, encoding="unicode")
    assert "Calculation_111" not in blob and "Calculation_222" not in blob
    assert "[ds].[usr:Deposits:qk]" in blob
    assert "[Deposits] * 2" in blob


def test_rename_refuses_on_nested_names():
    root = _tree("""<workbook><datasources><datasource name='ds'>
      <column name='[Level 1]'><calculation formula='1'/></column>
      <column name='[ Level 1]'><calculation formula='2'/></column>
    </datasource></datasources></workbook>""")
    with pytest.raises(ValueError, match="substring"):
        ED.rename_fields(root, {"Level 1": "A", " Level 1": "B"})


def test_rename_refuses_on_taken_name_and_on_missing_one():
    root = _two_fields()
    with pytest.raises(ValueError, match="already taken"):
        ED.rename_fields(root, {"Calculation_111": "Calculation_222"})
    with pytest.raises(ValueError, match="is not in the workbook"):
        ED.rename_fields(root, {"Calculation_999": "X"})
    assert "Calculation_111" in etree.tostring(root, encoding="unicode")


def test_formula_changes_in_all_declaration_copies():
    root = _tree("""<workbook><datasources><datasource name='ds'>
      <column name='[Bonus]' caption='Bonus'><calculation formula='SUM([ggr_real])-SUM([ngr])'/></column>
    </datasource></datasources>
    <worksheets><worksheet name='w'><datasource-dependencies>
      <column name='[Bonus]' caption='Bonus'><calculation formula='SUM([ggr_real])-SUM([ngr])'/></column>
    </datasource-dependencies></worksheet></worksheets></workbook>""")
    r = ED.set_formula(root, "Bonus", "[GGR] - [NGR]")
    assert r["declarations_edited"] == 2, r
    blob = etree.tostring(root, encoding="unicode")
    assert "ggr_real" not in blob and blob.count("[GGR] - [NGR]") == 2


def test_formula_refuses_on_nonexistent_field():
    root = _tree("<workbook><datasources><datasource name='ds'/></datasources></workbook>")
    with pytest.raises(ValueError, match="is not in the workbook"):
        ED.set_formula(root, "Bonus", "1")


def test_control_title_is_set_and_marks_the_zone():
    root = _tree("""<workbook><dashboards><dashboard name='D'><zones>
      <zone id='1' type-v2='layout-basic' x='0' y='0' w='100' h='100'>
        <zone id='21' type-v2='filter' name='chart' x='0' y='0' w='50' h='10'>
          <formatted-text><run>previous text</run></formatted-text>
        </zone>
        <zone id='22' type-v2='filter' name='chart' x='50' y='0' w='50' h='10'/>
      </zone>
    </zones></dashboard></dashboards></workbook>""")
    r = ED.zone_title(root, "D", {"21": "Filter Level 1", 22: "Filter Level 2"})
    assert r["titled"] == {"21": "Filter Level 1", "22": "Filter Level 2"}
    for zid, want in (("21", "Filter Level 1"), ("22", "Filter Level 2")):
        z = root.find(f".//zone[@id='{zid}']")
        assert z.get("custom-title") == "true"
        assert z.find("formatted-text/run").text == want
        assert list(z)[0].tag == "formatted-text"
    assert "previous text" not in etree.tostring(root, encoding="unicode")


def test_control_title_refuses_on_foreign_id():
    root = _tree("""<workbook><dashboards><dashboard name='D'><zones>
      <zone id='1' type-v2='layout-basic' x='0' y='0' w='10' h='10'/>
    </zones></dashboard></dashboards></workbook>""")
    with pytest.raises(ValueError, match="no zones"):
        ED.zone_title(root, "D", {"99": "X"})


def test_line_labels_at_the_end_only():
    root = etree.fromstring(
        "<workbook><worksheets><worksheet name='l'><table><panes><pane><style>"
        "<style-rule element='mark'><format attr='mark-labels-show' value='false'/>"
        "<format attr='mark-labels-cull' value='true'/></style-rule>"
        "</style></pane></panes></table></worksheet></worksheets></workbook>")
    assert ED.line_end_labels(root, ["l"]) == 1
    got = {f.get("attr"): f.get("value") for f in root.iter("format")}
    assert got["mark-labels-show"] == "true"
    assert got["mark-labels-mode"] == "line-ends"
    assert got["mark-labels-line-first"] == "false"
    assert ED.line_end_labels(root, ["l"]) == 1
    assert len([f for f in root.iter("format") if f.get("attr") == "mark-labels-mode"]) == 1


def test_hidden_dimension_header():
    root = etree.fromstring(
        "<workbook><worksheets><worksheet name='t'><table><style>"
        "<style-rule element='header'><format attr='width' value='9'/></style-rule>"
        "<style-rule element='worksheet'><format attr='x' value='1'/></style-rule>"
        "</style><panes/><rows>([ds].[none:Player ID + Casino:nk] / [ds].[none:Player_ID:nk])</rows>"
        "<cols>[ds].[:Measure Names]</cols></table></worksheet></worksheets></workbook>")
    assert ED.hide_header(root, "t", "Player ID + Casino") == 1
    rules = [r.get("element") for r in root.iter("style-rule")]
    assert rules == ["header", "label", "worksheet"]
    f = next(f for f in root.iter("format") if f.get("attr") == "display")
    assert f.get("field") == "[ds].[none:Player ID + Casino:nk]"
    assert f.get("value") == "false" and f.get("scope") is None and f.get("class") is None
    assert ED.hide_header(root, "t", "Player ID + Casino") == 0


def test_title_carries_color_key():
    from twkit import frame as FR
    root = etree.fromstring("<workbook><worksheets><worksheet name='s'><table/></worksheet>"
                            "</worksheets></workbook>")
    assert ED.set_sheet_title(root, "s", "Actives", size="15", bold=False,
                              legend={"New": "#4e79a7", "Retained": "#edc948"}) == 1
    runs = list(root.iter("run"))
    assert [r.text for r in runs] == ["Actives", "Æ\n", "\u25a0 ", "New   ", "\u25a0 ", "Retained   "]
    assert runs[2].get("fontcolor") == "#4e79a7" and runs[3].get("fontcolor") == "#555555"
    html = FR._title_html(root.find(".//worksheet"), "s", {}, {})
    assert "color:#edc948" in html and "Retained" in html


def test_sparkline_hides_measure_axis_and_date_header():
    from twkit import frame as FR
    root = etree.fromstring(
        "<workbook><worksheets><worksheet name='s'><table><panes/>"
        "<rows>[ds].[usr:NGR:qk]</rows><cols>[ds].[none:Day:ok]</cols></table></worksheet>"
        "<worksheet name='other'><table><panes/><rows>[ds].[usr:NGR:qk]</rows></table>"
        "</worksheet></worksheets></workbook>")
    assert ED.hide_axes(root, ["s"]) == 1
    ws = root.find(".//worksheet[@name='s']")
    axis = next(f for r in ws.iter("style-rule") if r.get("element") == "axis"
                for f in r.findall("format"))
    assert (axis.get("class"), axis.get("scope"), axis.get("value")) == ("0", "rows", "false")
    assert FR.axis_hidden(ws, "[usr:NGR:qk]")
    assert "[none:Day:ok]" in FR._hidden_headers(ws)
    assert ws.find("table/style").getnext().tag == "panes"
    assert ED.hide_axes(root, ["s"]) == 0
    assert root.find(".//worksheet[@name='other']/table/style") is None


def test_hidden_header_by_calculation_caption():
    root = etree.fromstring(
        "<workbook><datasources><datasource name='ds'>"
        "<column caption='Player ID + Casino' name='[Calculation_1]' role='dimension'/>"
        "</datasource></datasources><worksheets><worksheet name='t'><table><panes/>"
        "<rows>[ds].[none:Calculation_1:nk]</rows><cols/></table></worksheet></worksheets></workbook>")
    assert ED.hide_header(root, "t", "Player ID + Casino") == 1
    rule = next(root.iter("style-rule"))
    assert rule.get("element") == "label"
    assert rule.getparent().getnext().tag == "panes"


def test_column_width_by_calculation_caption():
    root = etree.fromstring(
        "<workbook><datasources><datasource name='ds'>"
        "<column caption='Provider' name='[Calculation_7]' role='dimension'/>"
        "</datasource></datasources><worksheets><worksheet name='t'><table><style/><panes/>"
        "<rows>[ds].[none:Calculation_7:nk]</rows><cols/></table></worksheet></worksheets></workbook>")
    assert ED.set_column_width(root, "t", "Provider", 140) == 1
    f = next(f for f in root.iter("format") if f.get("attr") == "width")
    assert (f.get("field"), f.get("value")) == ("[ds].[none:Calculation_7:nk]", "140")


def test_sheet_title_in_two_lines():
    root = etree.fromstring("<workbook><worksheets><worksheet name='w'><table/></worksheet></worksheets></workbook>")
    assert ED.set_sheet_title(root, "w", "7 Week\nAvg", size="11") == 1
    runs = [r.text for r in root.iter("run")]
    assert runs == ["7 Week", "Æ\n", "Avg"]
    assert all(r.get("bold") == "true" and r.get("fontsize") == "11" for r in root.iter("run"))


def test_top_n_by_internal_name_and_into_slices():
    root = etree.fromstring(
        "<workbook><datasources><datasource name='ds'>"
        "<column caption='stag' name='[Calculation_1]' role='dimension' datatype='string'/>"
        "<column caption=\"FTD's #\" name='[Calculation_2]' role='measure' datatype='real'>"
        "<calculation class='tableau' formula=\"SUM(IF [measure] = 'x' THEN [value] END)\"/></column>"
        "<column caption='qty' name='[qty]' role='measure' datatype='real'/>"
        "</datasource></datasources><worksheets><worksheet name='t'><table><view>"
        "<datasources/></view><rows>[ds].[none:Calculation_1:nk]</rows><cols/></table></worksheet>"
        "</worksheets></workbook>")
    r = ED.top_n_filter(root, "t", "stag", "FTD's #", 10)
    assert r["ok"], r
    order = next(g for g in root.iter("groupfilter") if g.get("function") == "order")
    assert order.get("expression") == "[Calculation_2]"
    assert not list(root.iter("slices"))
    assert ED._order_expression(root, "qty") == "SUM([qty])"


def test_empty_title_line_is_not_an_empty_run():
    root = etree.fromstring("<workbook><worksheets><worksheet name='w'><table/></worksheet></worksheets></workbook>")
    ED.set_sheet_title(root, "w", "Yesterday\n ")
    assert [r.text for r in root.iter("run")] == ["Yesterday", "Æ\n", "\u00a0"]


def test_fit_mode_by_synonyms_and_refusal_on_unknown():
    assert ED.fit_value("width") == ED.fit_value("Fit Width") == "fit-width"
    assert ED.fit_value("Entire View") == ED.fit_value("stretch") == "entire-view"
    assert ED.fit_value("standard") == ED.fit_value("Standard") == ""
    with pytest.raises(ValueError, match="unknown"):
        ED.fit_value("wide")


def test_order_expression_finds_plain_column_by_caption():
    root = etree.fromstring(
        "<workbook><datasources><datasource name='ds'>"
        "<column name='[payment_system]' caption='Payment system' datatype='string' role='dimension'/>"
        "</datasource></datasources></workbook>")
    assert ED._order_expression(root, "Payment system") != "[Payment system]"


def test_set_header_height_on_measure_names():
    root = safexml.from_bytes(
        b"<workbook><worksheets><worksheet name='T'><table><view/>"
        b"<rows/><cols>[ds].[:Measure Names]</cols></table></worksheet></worksheets></workbook>")
    assert ED.set_header_height(root, "T", ":Measure Names", 52) == 1
    f = root.find(".//style-rule[@element='header']/format")
    assert f.get("attr") == "height" and f.get("field") == "[ds].[:Measure Names]" and f.get("value") == "52"


def test_row_height_is_a_cell_height_on_the_innermost_row_field():
    root = safexml.from_bytes(
        b"<workbook><datasources><datasource name='ds'><column name='[g]' caption='Game'/></datasource>"
        b"</datasources><worksheets><worksheet name='T'><table><view/>"
        b"<rows>([ds].[none:p:nk] / [ds].[none:g:nk])</rows><cols>[ds].[:Measure Names]</cols>"
        b"</table></worksheet></worksheets></workbook>")
    assert ED.set_row_height(root, "T", 35) == 1
    f = root.find(".//style-rule[@element='cell']/format")
    assert (f.get("attr"), f.get("field"), f.get("value")) == ("height", "[ds].[none:g:nk]", "35")


def _side_by_side_tables():
    sheet = ("<worksheet name='{n}'><layout-options><title><formatted-text><run>{t}</run>"
             "</formatted-text></title></layout-options><table><view/><rows>[ds].[none:partner:nk]</rows>"
             "<cols>[ds].[:Measure Names]</cols></table></worksheet>")
    return safexml.from_bytes((
        "<workbook><datasources><datasource name='ds'>"
        "<column name='[partner]' caption='Partner' datatype='string' role='dimension'/>"
        "</datasource></datasources><worksheets>" +
        sheet.format(n="A", t="Daily first deposits by partner top ten") + sheet.format(n="B", t="B") +
        "</worksheets><dashboards><dashboard name='D'><size maxwidth='1200' maxheight='800'/><zones>"
        "<zone name='A' x='0' y='10000' w='50000' h='60000'/>"
        "<zone name='B' x='50000' y='10000' w='50000' h='60000'/>"
        "</zones></dashboard></dashboards></workbook>").encode())


def test_fit_tables_once_equal_header_bands_and_title_room():
    from twkit import contentfit as CF
    root = _side_by_side_tables()
    needs = {"A": {"head_lines": 3, "cols": [40, 60]}, "B": {"head_lines": 2, "cols": [400, 60]}}
    got = ED.fit_tables_once(root, needs)
    assert got["header_px"] == {"A": CF.header_px(3), "B": CF.header_px(3)}
    assert set(got["title_px"]) == {"A"} and got["title_px"]["A"] > 40
    again = ED.fit_tables_once(root, needs)
    assert again == {"header_px": {}, "title_px": {}, "row_px": {}}


def test_fit_tables_once_shares_a_tall_row_with_the_neighbour():
    root = _side_by_side_tables()
    ED.set_row_height(root, "A", 35)
    got = ED.fit_tables_once(root, {"A": {"cols": [200, 60]}, "B": {"cols": [200, 60]}})
    assert got["row_px"] == {"B": 35}, "rows of tables side by side drift apart (critic R1)"


def test_fit_tables_once_shares_a_set_band_and_keeps_multiline_titles():
    root = _side_by_side_tables()
    ED.set_header_height(root, "B", ":Measure Names", 52)
    for run in root.iter("run"):
        if run.text.startswith("Daily"):
            run.text = "Daily first deposits by partner top ten\n■ Casino ■ Sport"
    got = ED.fit_tables_once(root, {"A": {"head_lines": 2, "cols": [40, 60]},
                                    "B": {"head_lines": 2, "cols": [400, 60]}})
    assert got == {"header_px": {"A": 52}, "title_px": {}, "row_px": {}}
