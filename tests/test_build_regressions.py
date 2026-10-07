import os

import pytest

DB, TABLE = "reports", "partner_daily"


@pytest.fixture
def wb():
    from twkit.book import Book

    from twkit.schema import apply_to_workbook, fetch_schema
    from twkit import config
    e = Book()
    e.set_mysql_connection(server=config.get("host"), dbname=DB, username=config.get("user"),
                           table_name=TABLE, port=config.get("port"))
    apply_to_workbook(e, fetch_schema(DB, TABLE))
    return e


def _shelf(wb, sheet: str, tag: str) -> str:
    ws = next(w for w in wb.root.iter("worksheet") if w.get("name") == sheet)
    return " ".join((e.text or "").strip() for e in ws.iter(tag)).strip()


def test_measure_values_table_keeps_dimensions_on_rows(wb):
    wb.add_worksheet("t")
    wb.configure_chart("t", mark_type="Text",
                       rows=["traffic_source", "traffic_geo"],
                       measure_values=["ngr", "dep_sum", "ftd_count"])
    rows = _shelf(wb, "t", "rows")
    cols = _shelf(wb, "t", "cols")
    assert rows
    assert "traffic_source" in rows.lower() or ":nk]" in rows, rows
    assert ":Measure Names" in cols, cols


def test_measure_values_table_drops_measures_from_rows(wb):
    wb.add_worksheet("t2")
    wb.configure_chart("t2", mark_type="Text",
                       rows=["traffic_source", "ngr"],
                       measure_values=["ngr", "dep_sum"])
    rows = _shelf(wb, "t2", "rows")
    assert rows
    assert "sum:ngr" not in rows


def test_measure_values_without_rows_still_works(wb):
    wb.add_worksheet("t3")
    wb.configure_chart("t3", mark_type="Text", measure_values=["ngr", "dep_sum"])
    assert ":Measure Names" in _shelf(wb, "t3", "cols")


def test_numeric_measure_named_day_not_month():
    from twkit.fields import Field, derivation

    for dt in ("integer", "real"):
        f = Field("days_since_last_deposit", "days_since_last_deposit", "measure", dt, "quantitative")
        assert derivation("", f) == ("Sum", "qk"), "the number turned into a date"
    d = Field("order_date", "order_date", "dimension", "date", "ordinal")
    assert derivation("", d) == ("None", "ok"), "a date name must not turn into MONTH"
    assert derivation("MONTH", d) == ("Month", "ok")


def test_filter_with_field_key_reaches_sheet(wb):
    wb.add_worksheet("f1")
    wb.configure_chart("f1", mark_type="Bar", rows=["traffic_source"], columns=["ngr"],
                       filters=[{"field": "traffic_geo", "values": ["KE"]}])
    ws = next(w for w in wb.root.iter("worksheet") if w.get("name") == "f1")
    cols = [f.get("column") for f in ws.iter("filter")]
    assert cols
    assert any("traffic_geo" in (c or "") for c in cols), cols


def test_filter_zone_reference_matches_sheet_filter(wb):
    wb.add_worksheet("f2")
    wb.configure_chart("f2", mark_type="Bar", rows=["traffic_source"], columns=["ngr"],
                       filters=[{"field": "traffic_geo", "values": ["KE"]}])
    wb.add_dashboard("DF", width=1200, height=800, layout={
        "type": "container", "direction": "vertical", "children": [
            {"type": "filter", "worksheet": "f2", "field": "traffic_geo", "fixed_size": 60},
            {"type": "worksheet", "name": "f2", "weight": 8}]},
        worksheet_names=["f2"])
    zone_params = {z.get("param") for z in wb.root.iter("zone")
                   if z.get("type-v2") == "filter"}
    ws = next(w for w in wb.root.iter("worksheet") if w.get("name") == "f2")
    sheet_cols = {f.get("column") for f in ws.iter("filter")}
    assert zone_params
    assert zone_params == sheet_cols, (
        f"the zone references {zone_params}, and the sheet filters on {sheet_cols} — "
        "the control will render empty")


def test_filter_without_field_fails_loudly(wb):
    import pytest as _pytest

    wb.add_worksheet("f3")
    with _pytest.raises(ValueError, match="filter without a field"):
        wb.configure_chart("f3", mark_type="Bar", rows=["traffic_source"], columns=["ngr"],
                           filters=[{"values": ["organic"]}])


@pytest.fixture
def blank():
    from twkit.book import Book
    return Book()


def _objects(wb):
    return wb.root.findall(".//datasources/datasource/object-graph/objects/object")


def test_extract_does_not_drag_superstore(blank):
    blank.set_hyper_connection("/tmp/x.hyper", tables=[
        {"name": "RFM", "columns": ["user_id", "rfm_segment"]},
        {"name": "Monthly", "columns": ["user_id", "month", "dep_sum"]}])
    captions = {o.get("caption") for o in _objects(blank)}
    assert "Orders" not in captions
    leftovers = [c.get("name") for o in _objects(blank)
                 for c in o.iter("column")
                 if c.get("name") in {"Sales", "Profit", "Category", "Order Date"}]
    assert not leftovers


def test_second_extract_table_gets_own_object(blank):
    blank.set_hyper_connection("/tmp/x.hyper", tables=[
        {"name": "RFM", "columns": ["user_id", "rfm_segment"]},
        {"name": "Monthly", "columns": ["user_id", "month", "dep_sum"]}])
    captions = [o.get("caption") for o in _objects(blank)]
    assert captions == ["RFM", "Monthly"], captions
    tables = {o.find("properties/relation").get("table") for o in _objects(blank)}
    assert tables == {"[Extract].[RFM]", "[Extract].[Monthly]"}, tables


def test_extract_tables_joined_on_shared_column(blank):
    blank.set_hyper_connection("/tmp/x.hyper", tables=[
        {"name": "RFM", "columns": ["user_id", "rfm_segment"]},
        {"name": "Monthly", "columns": ["user_id", "month", "dep_sum"]}])
    rels = blank.root.findall(
        ".//datasources/datasource/object-graph/relationships/relationship")
    assert len(rels) == 1
    ops = [e.get("op") for e in rels[0].find("expression").findall("expression")]
    assert ops == ["[user_id]", "[user_id (Monthly)]"], ops
    ends = {rels[0].find("first-end-point").get("object-id"),
            rels[0].find("second-end-point").get("object-id")}
    assert ends == {o.get("id") for o in _objects(blank)}, ends


def test_single_extract_table_named(blank):
    blank.set_hyper_connection("/tmp/x.hyper", table_name="Extract")
    captions = [o.get("caption") for o in _objects(blank)]
    assert captions == ["Extract"], captions


def test_dry_run_knows_multitable_suffix_names():
    from lxml import etree

    from twkit.dryrun import Translator, column_aliases

    root = etree.fromstring(
        b"""<workbook><datasources><datasource><connection><cols>
             <map key="[user_id]" value="[RFM].[user_id]"/>
             <map key="[month]" value="[Monthly].[month]"/>
             <map key="[user_id (Monthly)]" value="[Monthly].[user_id]"/>
           </cols></connection></datasource></datasources></workbook>""")
    aliases = column_aliases(root)
    assert aliases == {"user_id (Monthly)": "user_id"}, aliases

    tr = Translator({}, {}, {}, {"user_id", "month"}, dialect="hyper", aliases=aliases)
    sql, why = tr.to_sql("COUNTD([user_id (Monthly)])")
    assert not why, why
    assert "user_id (Monthly)" not in sql, sql
    assert "user_id" in sql, sql


def test_time_axis_can_be_continuous(blank):
    blank.set_hyper_connection("/tmp/x.hyper", tables=[
        {"name": "RFM", "columns": ["user_id"]},
        {"name": "Monthly", "columns": ["user_id", "month", "dep_sum"]}])
    blank.add_worksheet("tr")
    blank.configure_chart("tr", mark_type="Line", columns=["MONTHTRUNC(month)"],
                          rows=["SUM(dep_sum)"])
    ws = next(w for w in blank.root.iter("worksheet") if w.get("name") == "tr")
    cols = " ".join((e.text or "") for e in ws.iter("cols"))
    assert "tmn:" in cols and ":qk]" in cols, cols
    assert "mn:month:ok" not in cols, cols
    ci = [c for c in blank.root.iter("column-instance")
          if (c.get("name") or "").startswith("[tmn:")]
    assert ci and ci[0].get("derivation") == "Month-Trunc", \
        [(c.get("name"), c.get("derivation")) for c in ci]


def test_canon_sees_metric_through_calculation_chain():
    from twkit.canon import check_formulas, expand_refs

    by_name = {"Calculation_CM": "SUM(IF [month] = X THEN [ggr] END)",
               "Calculation_PM": "SUM(IF [month] = Y THEN [ggr] END)"}
    raw = "([Calculation_CM] - [Calculation_PM]) / ABS([Calculation_PM])"

    assert "ggr" not in raw.lower()
    assert check_formulas([("GGR Δ", raw)])

    expanded = expand_refs(raw, by_name)
    assert "ggr" in expanded.lower(), expanded
    assert not check_formulas([("GGR Δ", expanded)])


def test_aggregate_behind_reference_not_wrapped_twice(blank):
    blank.set_hyper_connection("/tmp/x.hyper", tables=[
        {"name": "Monthly", "columns": ["month", "dep_sum"]}])
    blank.add_calculated_field("LTV CM", "SUM(IF [month] = #2026-01-01# THEN [dep_sum] END)",
                               datatype="real", role="measure")
    blank.add_calculated_field("KPI LTV", "[LTV CM]", datatype="real", role="measure")
    blank.add_worksheet("ban")
    blank.configure_chart("ban", mark_type="Text", label="KPI LTV")

    ci = [c for c in blank.root.iter("column-instance")
          if (c.get("caption") or "") == "" and "KPI" not in (c.get("name") or "")]
    kpi = [c for c in blank.root.iter("column")
           if (c.get("caption") or "") == "KPI LTV"]
    assert kpi
    internal = kpi[0].get("name")
    inst = [c for c in blank.root.iter("column-instance")
            if c.get("column") == internal]
    assert inst
    assert inst[0].get("derivation") == "User", (
        f"derivation={inst[0].get('derivation')}: aggregate wrapped in a second aggregate, "
        "the sheet will open empty")


def test_text_with_color_writes_color_map_to_source(blank):
    blank.set_hyper_connection("/tmp/x.hyper", tables=[
        {"name": "T", "columns": ["month", "flag", "value"]}])
    blank.add_worksheet("rk")
    blank.configure_chart("rk", mark_type="Text", rows=["month"], label="SUM(value)",
                          color="flag", color_map={"1": "#59a14f", "REST": "#1f1f1f"})
    enc = [e for e in blank.root.iter("encoding")
           if e.get("attr") == "color" and ":flag:" in (e.get("field") or "")]
    assert enc
    assert not enc[0].get("field").startswith("[federated"), enc[0].get("field")
    got = {(m.findtext("bucket") or "").strip('"'): m.get("to") for m in enc[0].findall("map")}
    assert got == {"1": "#59a14f", "REST": "#1f1f1f"}, got
    ds_inst = [c.get("name") for ds in blank.root.iter("datasource")
               for c in ds.findall("column-instance")]
    assert enc[0].get("field") in ds_inst, ds_inst


def test_pie_with_color_writes_color_map_to_source(blank):
    blank.set_hyper_connection("/tmp/x.hyper", tables=[
        {"name": "T", "columns": ["device", "value"]}])
    blank.add_worksheet("pie")
    blank.configure_chart("pie", mark_type="Pie", color="device", wedge_size="SUM(value)",
                          color_map={"mobile": "#59a14f", "desktop": "#ffbe7d"})
    enc = [e for e in blank.root.iter("encoding")
           if e.get("attr") == "color" and ":device:" in (e.get("field") or "")]
    assert enc
    got = {(m.findtext("bucket") or "").strip('"'): m.get("to") for m in enc[0].findall("map")}
    assert got == {"mobile": "#59a14f", "desktop": "#ffbe7d"}, got


def _csv_book(tmp_path):
    import _matrix_book as M
    from twkit.book import Book
    e = Book()
    e.set_csv_connection(M.write_csv(str(tmp_path / "sales.csv")), fields=[dict(f) for f in M.FIELDS])
    return e


def test_calculated_field_refuses_a_caption_already_taken(tmp_path):
    e = _csv_book(tmp_path)
    e.add_calculated_field("Margin", "1", datatype="real")
    with pytest.raises(ValueError, match="R42"):
        e.add_calculated_field("Margin", "2", datatype="real")
    e.add_calculated_field("Margin​", "2", datatype="real")
    caps = [c.get("caption") for c in e.root.iter("column") if c.get("caption", "").startswith("Margin")]
    assert caps == ["Margin", "Margin​"]


def test_a_field_may_share_its_name_with_the_table_object(tmp_path):
    from lxml import etree
    e = _csv_book(tmp_path)
    e.datasource.append(etree.fromstring(
        "<column caption='Orders' datatype='table' name='[__tableau_internal_object_id__].[Orders_1]' "
        "role='measure' type='quantitative'/>"))
    e.add_calculated_field("Orders", "1", datatype="real")


def test_removing_a_calculation_a_sheet_uses_is_refused(tmp_path):
    import _matrix_book as M
    from twkit.book import Book
    e = Book.open(M.build(str(tmp_path)))
    said = e.remove_calculated_field("Margin")
    assert "Table" in said and "used" in said
    assert any(c.get("caption") == "Margin" for c in e.datasource.findall("column"))
    e.add_calculated_field("Spare", "1", datatype="real")
    assert e.remove_calculated_field("Spare").startswith("Removed")
