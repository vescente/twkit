from twkit import dryrun as D


def _tr(calcs=None, params=None):
    t = D.Translator(calcs or {}, {}, params or {}, {"Sales", "Region", "Order Date"},
                     dialect="hyper")
    t.lod_table = '"Extract"."T"'
    return t


def test_table_scoped_lod_is_scalar_subquery():
    sql, why = _tr().to_sql("[Sales] / { SUM([Sales]) }")
    assert not why
    assert '(SELECT SUM("Sales") FROM "Extract"."T" AS _lod1)' in sql


def test_fixed_lod_correlates_on_dims():
    tr = _tr()
    sql, why = tr.to_sql("{FIXED [Region] : SUM([Sales])}")
    assert not why
    assert '_lod1."Region" IS NOT DISTINCT FROM "Extract"."T"."Region"' in sql
    assert tr.last_lod["pure"] and tr.last_lod["dims"] == {"Region"}


def test_nested_lod_substituted_fully():
    sql, why = _tr().to_sql("{ MAX({FIXED [Region] : SUM([Sales])}) }")
    assert not why and "__lod" not in sql


def test_include_exclude_honestly_skipped():
    assert _tr().to_sql("{INCLUDE [Region] : SUM([Sales])}")[1]


def test_no_table_no_lod():
    t = _tr()
    t.lod_table = None
    assert t.to_sql("{ MAX([Order Date]) }")[1]


def test_param_only():
    tr = _tr(calcs={"tgt": "[Parameters].[P4]", "one": "1", "mix": "[Sales]/[Parameters].[P4]"},
             params={"P4": "1000000"})
    assert tr.param_only(tr.calcs["tgt"])
    assert not tr.param_only(tr.calcs["one"])
    assert not tr.param_only(tr.calcs["mix"])


def test_lod_measure_rule():
    m = ["SUM(x)"]
    assert D._lod_measures(m, [(0, "SUM", "x", {"Region"}, "f")], {"Region", "State"}) == ""
    assert m == ["MIN(x)"]
    assert D._lod_measures(["SUM(x)"], [(0, "SUM", "x", {"Customer"}, "f")], {"Region"})


def test_plus_inside_literal_is_not_concat():
    assert D._concat_literals("CASE WHEN x>0 THEN '+' ELSE '-' END") == \
        "CASE WHEN x>0 THEN '+' ELSE '-' END"
    assert D._concat_literals("'W ' + y") == "'W ' || y"
    assert "+" in D._concat_literals("DATE '2026-01-01' + n")


def test_date_units_on_hyper():
    import pytest
    hp = pytest.importorskip("tableauhyperapi")
    tr = _tr()
    cases = {
        "DATEADD('month', 1, #2024-01-31#)": "2024-02-29",
        "DATEADD('quarter', 2, #2024-01-31#)": "2024-07-31",
        "DATEDIFF('month', #2023-12-31#, #2024-03-01#)": "3",
        "DATEDIFF('year', #2023-12-31#, #2024-01-01#)": "1",
        "DATEDIFF('week', #2026-09-26#, #2026-10-04#)": "2",
        "DATEPART('weekday', #2026-10-04#)": "1",
        "DATEPART('quarter', #2026-10-04#)": "4",
        "DATETRUNC('day', DATEADD('day', DATEDIFF('day', #2026-01-01#, TODAY()), #2026-01-01#))": None,
    }
    with hp.HyperProcess(hp.Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as p, \
            hp.Connection(p.endpoint) as c:
        for f, want in cases.items():
            sql, why = tr.to_sql(f)
            assert not why, f
            got = str(c.execute_scalar_query(f"SELECT {sql}"))
            if want is not None:
                assert got.startswith(want) or got.rstrip("0").rstrip(".") == want, (f, sql, got)


def test_non_iso_date_literal():
    sql, _ = _tr().to_sql("IF [Order Date] = #25/12/2025# THEN 1 END")
    assert "DATE '2025-12-25'" in sql and "NULLIF" not in sql
    assert D._dmy("3", "4", "2026") == "2026-03-04"


def test_split_three_args():
    assert "SPLIT_PART(" in _tr().to_sql('SPLIT([Region], " ", 1)')[0]


def test_object_id_counter_pattern():
    assert D._OBJECT_ID.search("Hospitality.csv_FCECB5DFE2154D7591D4523AD48CE39E")
    assert not D._OBJECT_ID.search("Sales")


def test_superstore_top_states_matches_public():
    import os
    import pytest
    from _userdata import INSPIRATION
    path = os.path.join(INSPIRATION, "Superstore Sales Overview_v2026.1.twbx")
    if not os.path.exists(path):
        pytest.skip("inspiration corpus not available")
    r = next(x for x in D.dry_run(path, limit=8, sample_rows=8) if x.sheet == "Top States")
    assert r.status == "ok"
    assert {row[0] for row in r.sample} == {"California", "New York", "Washington",
                                            "Texas", "Pennsylvania"}


def test_date_plus_number_is_days():
    dc = {'"Order Date"', '"Ship Date"'}
    assert D.date_plus('"Order Date" + 7', dc) == "\"Order Date\" + (7) * INTERVAL '1 day'"
    assert D.date_plus('"Order Date" - "Ship Date"', dc) == '"Order Date" - "Ship Date"'
    assert D.date_plus('"Sales" + 1', dc) == '"Sales" + 1'
    same = "(\"Order Date\" + 1 * INTERVAL '1 day')"
    assert D.date_plus(same, dc) == same
    assert "INTERVAL" in D.date_plus("\"Order Date\"+((DATE_PART('day', x)))", dc)


def test_date_filter_members():
    assert D._PART_SQL["yr"] == "year"


def test_mid_find_initials_on_hyper():
    import pytest
    hp = pytest.importorskip("tableauhyperapi")
    sql, _ = _tr().to_sql('LEFT("Danielle Baffin",1)+MID("Danielle Baffin",FIND("Danielle Baffin"," ")+1,1)')
    with hp.HyperProcess(hp.Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as p, \
            hp.Connection(p.endpoint) as c:
        assert c.execute_scalar_query(f"SELECT {sql}") == "DB"


def test_str_drops_numeric_scale_on_hyper():
    import pytest
    hp = pytest.importorskip("tableauhyperapi")
    tr = _tr()
    with hp.HyperProcess(hp.Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as p, \
            hp.Connection(p.endpoint) as c:
        for f, want in (("STR(AVG(4))", "4"), ("STR(100)", "100"), ("STR(4.5)", "4.5")):
            assert c.execute_scalar_query("SELECT " + tr.to_sql(f)[0]) == want


def test_group_formula_and_inch_quotes():
    import xml.etree.ElementTree as ET  # noqa: S405
    calc = ET.fromstring(  # noqa: S314
        "<calculation class='categorical-bin' column='[Product Name]'>"
        "<bin value='&quot;3M&quot;'><value>\"3M Lamp\"</value><value>\"20\"\" Monitor\"</value></bin>"
        "</calculation>")
    f = D.group_formula(calc)
    assert f == "CASE WHEN [Product Name] IN ('3M Lamp', '20\" Monitor') THEN '3M' ELSE [Product Name] END"
    sql, why = _tr().to_sql(f)
    assert not why and "'20\" Monitor'" in sql


def test_division_on_own_line_is_guarded():
    assert "NULLIF((COUNT(b)), 0)" in D.guard_division("(COUNT(a))\n/\n(COUNT(b))")


def test_nested_calc_trailing_comment_keeps_paren():
    tr = D.Translator({"cy": "IF [a] = 1\r\nTHEN [b]\r\nEND\r\n// comment closes line"}, {}, {},
                      {"a", "b"}, dialect="hyper")
    sql, why = tr.to_sql("AVG([cy]) + 1")
    assert not why and sql.count("(") == sql.count(")")


def test_fixed_on_calc_dimension_correlates_on_expression():
    tr = D.Translator({"Mon": "DATETRUNC('month',[ts])"}, {}, {}, {"ts", "cat", "v"},
                      dialect="hyper")
    tr.lod_table = '"Extract"."T"'
    sql, why = tr.to_sql("{FIXED [Mon], [cat] : SUM([v])}")
    assert not why
    assert "_lod1.cat IS NOT DISTINCT FROM \"Extract\".\"T\".cat" in sql
    assert "DATE_TRUNC('month', \"Extract\".\"T\".ts)" in sql
    assert "_lod1.ts IS NOT DISTINCT" not in sql


def test_lod_dim_parts_keep_commas_in_names():
    assert D._lod_dim_parts("[a, b (%)], (DATETRUNC('month',[ts])\n)") == \
        ["[a, b (%)]", "DATETRUNC('month',[ts])"]


def test_nested_table_calc_direction_from_instance():
    import xml.etree.ElementTree as ET  # noqa: S405
    ws = ET.fromstring(  # noqa: S314
        "<worksheet><column-instance name='[usr:Title:nk:9]'>"
        "<table-calc ordering-type='Columns' />"
        "<table-calc field='[ds].[Rank]' ordering-field='[ds].[advisor_name]' ordering-type='Field' />"
        "</column-instance></worksheet>")
    tr = _tr(calcs={"Rank": "RANK(SUM([Sales]))", "Title": "STR([Rank]) + ' of 4'"})
    tagged = D._tc_nested(ws, "[usr:Title:nk:9]", tr)
    (tag, spec), = tagged.items()
    assert spec["ordering"] == "Field" and spec["fields"] == ["advisor_name"]
    assert D._tc_spec(ws, "[usr:Title:nk:9]", "Title")["ordering"] == "Columns"
    tr.allow_tc = True
    sql, why = tr.to_sql(tr.calcs["Title"])
    assert not why and f"RANK({tag}," in sql


def test_object_id_counter_three_part_ref():
    col = "[fed.1].[__tableau_internal_object_id__].[cnt:Hosp.csv_FCECB5DFE2154D7591D4523AD48CE39E:qk]"
    assert D.inst_refs(col) == ["[cnt:Hosp.csv_FCECB5DFE2154D7591D4523AD48CE39E:qk]"]
    assert D.inst_refs("([a].[none:x:nk] / [a].[sum:y:qk])") == ["[none:x:nk]", "[sum:y:qk]"]


def test_object_id_in_formula_and_double_equals():
    sql, why = _tr().to_sql(
        "IF COUNT([__tableau_internal_object_id__].[Hosp.csv_FCECB5DFE2154D7591D4523AD48CE39E])"
        " == 3 THEN 'a==b' END")
    assert not why
    assert "COUNT(1)" in sql and "== 3" not in sql and "= 3" in sql
    assert "'a==b'" in sql


def test_marks_dims_address_in_table_modes():
    import types
    import xml.etree.ElementTree as ET  # noqa: S405
    ws = ET.fromstring("<worksheet><table><rows>[ds].[none:a:nk]</rows><cols/></table>"  # noqa: S314
                       "</worksheet>")
    tgt = types.SimpleNamespace(table='"T"')
    for ot in ("Columns", "Rows"):
        sql = D._tc_query(ws, ["a", "b"], ["SUM(x) / TOTAL(SUM(x))"], ["[none:a:nk]", "[none:b:nk]"],
                          [("m", 0, {"ordering": ot, "fields": [], "ok": True})], [], [], tgt)
        part = sql.split("OVER (", 1)[1].split(")", 1)[0]
        assert ("_d1" not in part) and (("_d0" in part) == (ot == "Rows")), (ot, part)


def test_fixed_finer_than_view_sums_present_tuples():
    import pytest
    hp = pytest.importorskip("tableauhyperapi")
    tr = D.Translator({}, {}, {}, {"p", "m", "r"}, dialect="hyper")
    tr.lod_table = "t"
    sql, why = tr.to_sql("{FIXED [p] : COUNT([r])}")
    assert not why and tr.last_lod["dim_sql"] == ["p"]
    fine = D._fine_lod("SUM", sql, tr.last_lod, ["m"], [], tr)
    with hp.HyperProcess(hp.Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as p, \
            hp.Connection(p.endpoint) as c:
        c.execute_command("CREATE TEMPORARY TABLE t (p TEXT, m INT, r INT)")
        c.execute_command("INSERT INTO t VALUES ('a',1,1), ('a',1,2), ('a',2,3), ('b',2,4)")
        got = c.execute_list_query(f"SELECT m, {fine} FROM t GROUP BY 1 ORDER BY 1")
    assert [(r[0], int(r[1])) for r in got] == [(1, 3), (2, 4)]


def test_caption_does_not_shadow_physical_column():
    import xml.etree.ElementTree as ET  # noqa: S405
    tr = D.Translator({"Calculation_1": "AVG(0.00)"}, {"Segment": "Calculation_1"}, {},
                      {"Segment", "Sales"}, dialect="hyper")
    tr.lod_table = '"T"'
    ws = ET.fromstring(  # noqa: S314
        "<worksheet name='w'><table><view/><panes><pane><mark class='Bar'/><encodings/>"
        "</pane></panes><rows>[ds].[none:Segment:nk]</rows><cols>[ds].[sum:Sales:qk]</cols>"
        "</table></worksheet>")
    import types
    r = D._run_sheet(ws, tr, types.SimpleNamespace(table='"T"', execute=lambda sql: []), 5)
    assert r.dim_exprs == ['"Segment"'] and "AVG(0.00)" not in r.sql


def test_fixed_dim_with_nested_lod_has_no_markers():
    tr = D.Translator({"Coh": "DATETRUNC('month', DATE({ FIXED [u] : MIN([d]) }))"}, {}, {},
                      {"u", "d"}, dialect="hyper")
    tr.lod_table = '"T"'
    sql, why = tr.to_sql("{ FIXED [Coh] : COUNTD([u]) }")
    assert not why and "__lod" not in sql
    assert tr.last_lod["dim_sql"] and not any("__lod" in d for d in tr.last_lod["dim_sql"])


def test_member_list_types():
    tr = _tr()
    got = D._member_list(['"a' + "'" + 'b"', "#2025-01-01 00:00:00#", "3"], tr)
    assert got == "'a''b', TIMESTAMP '2025-01-01 00:00:00', 3"
    assert D._member_list(["%null%"], tr) == ""


def test_datediff_day_counts_date_boundaries_on_hyper():
    import pytest
    hp = pytest.importorskip("tableauhyperapi")
    q = D.date_diff_sql("hyper", "day", "TIMESTAMP '2026-01-01 23:00:00'",
                        "TIMESTAMP '2026-01-02 01:00:00'")
    with hp.HyperProcess(hp.Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as p, \
            hp.Connection(p.endpoint) as c:
        assert c.execute_scalar_query("SELECT " + q) == 1


def test_proper_set_membership_and_text_concat():
    import xml.etree.ElementTree as ET  # noqa: S405
    g = ET.fromstring(  # noqa: S314
        "<group name='[Order Month Set]'><groupfilter function='member' "
        "level='[none:Order Month:ok]' member='#2025-03-01#'/></group>")
    assert D.set_formula(g) == "[Order Month] IN (#2025-03-01#)"
    tr = D.Translator({"Order Month Set": D.set_formula(g)}, {}, {},
                      {"Order Month", "Order ID", "Product ID", "Name"}, dialect="hyper")
    tr.sets = {"Order Month Set"}
    tr.text_cols = {"Order ID", "Product ID", "Name"}
    sql, why = tr.to_sql("IF [Order Month] IN [Order Month Set] THEN 1 END")
    assert not why and "IN (DATE '2025-03-01')" in sql and "IN (\"Order Month\" IN" not in sql
    sql, why = tr.to_sql("[Order ID] + [Product ID]")
    assert not why and '"Order ID" || "Product ID"' in sql
    assert "INITCAP(\"Name\")" in tr.to_sql("PROPER([Name])")[0]


def test_relationship_side_with_datepart():
    f = {"Creation Date": ("A", "Creation Date"), "segment": ("B", "segment")}
    assert D._rel_side("[segment]", f) == ("B", "segment", None)
    oid, col, tpl = D._rel_side("DATEPART('hour',[Creation Date])", f)
    assert (oid, col) == ("A", "Creation Date") and "HOUR" in tpl.format('r0."Creation Date"')


def test_instance_parts_strip_visual_totals_and_forecast():
    assert D._instance_parts("[sum:Sales:vtnone:qk]") == ("sum", "Sales")
    assert D._instance_parts("[fVal:sum:Sales:qk]") == ("sum", "Sales")


def test_alias_falls_back_to_existing_column():
    tr = D.Translator({}, {}, {}, {"Req_ID"}, dialect="hyper", aliases={"Req_ID": "Req_ID1"})
    assert tr.quote_ident("Req_ID") == '"Req_ID"'
    tr2 = D.Translator({}, {}, {}, {"Req_ID1"}, dialect="hyper", aliases={"Req_ID": "Req_ID1"})
    assert tr2.quote_ident("Req_ID") == '"Req_ID1"'


def test_combined_field_and_constant_relationship():
    import xml.etree.ElementTree as ET  # noqa: S405
    g = ET.fromstring(  # noqa: S314
        "<group xmlns:user='http://www.tableausoftware.com/xml/user' name='[A &amp; B (Combined)]' "
        "user:ui-builder='nest-group'><groupfilter function='crossjoin'>"
        "<groupfilter function='level-members' level='[A]'/>"
        "<groupfilter function='level-members' level='[B]'/></groupfilter></group>")
    assert D.set_formula(g) == 'STR([A]) + ", " + STR([B])'
    assert D._rel_side("1", {}) == ("", "", "1")


def test_previous_value_is_honest_skip():
    tr = _tr()
    tr.allow_tc = True
    sql, why = tr.to_sql("IF SUM([Sales]) > 0 THEN PREVIOUS_VALUE(0) END")
    assert why and "PREVIOUS_VALUE" in why


def test_dynamic_parameter_takes_field_formula():
    import xml.etree.ElementTree as ET  # noqa: S405
    root = ET.fromstring(  # noqa: S314
        "<workbook><datasources><datasource name='Parameters'>"
        "<column name='[P20]' param-domain-type='list' value='#2024-12-01#' "
        "default-value-field='[ds].[Cur]'><calculation formula='#2024-12-01#'/></column>"
        "</datasource><datasource name='ds'><column name='[Cur]'>"
        "<calculation class='tableau' formula=\"DATETRUNC('month',TODAY())\"/></column>"
        "</datasource></datasources></workbook>")
    calcs, _caps, params, _sets = D._book_dicts(root)
    assert "TODAY()" in params["P20"] and "2024" not in params["P20"]
