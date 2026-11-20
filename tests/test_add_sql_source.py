import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED
from twkit import extract as EX
from twkit import safexml
from twkit.book import Book

_TWB = """<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1'>
  <datasources>
    <datasource hasconnection='false' inline='true' name='Parameters' version='18.1'>
      <column caption='Period End' datatype='date' name='[Parameter 1]' param-domain-type='any'
              role='measure' type='quantitative' value='#2026-09-30#'>
        <calculation class='tableau' formula='#2026-09-30#' />
      </column>
    </datasource>
    <datasource caption='Main' inline='true' name='federated.main' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='h' name='mysql.main'>
            <connection class='mysql' dbname='marts' port='3306' server='h' username='tableau' />
          </named-connection>
        </named-connections>
        <relation connection='mysql.main' name='Custom SQL Query' type='text'>SELECT 1 AS a</relation>
      </connection>
      <column datatype='integer' name='[a]' role='measure' type='quantitative' />
      <column caption='Total' datatype='real' name='[Calculation_1]' role='measure' type='quantitative'>
        <calculation class='tableau' formula='SUM([a])' />
      </column>
    </datasource>
  </datasources>
</workbook>
"""

COLUMNS = [{"name": "event_date", "datatype": "date"},
           {"name": "user_id", "datatype": "integer"},
           {"name": "ggr", "datatype": "real"}]


def _book(tmp_path):
    p = tmp_path / "Book.twbx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Book.twb", _TWB)
        z.writestr("Data/Extracts/main.hyper", b"main")
    return str(p)


def _add(root):
    return ED.add_sql_source(root, "Second", "SELECT event_date, user_id, ggr FROM t", COLUMNS,
                             server="h", port="3306", dbname="marts", username="tableau")


def test_second_source_leaves_the_first_alone(tmp_path):
    book = Book.open(_book(tmp_path))
    main_before = etree.tostring(book.source("Main"))
    res = _add(book.root)
    new = book.source("Second")
    assert res["caption"] == "Second" and new.get("name") == res["source"]
    rel = new.find("connection/relation[@type='text']")
    assert rel is not None and "FROM t" in rel.text
    assert [r.findtext("remote-name") for r in new.findall(
        "connection/metadata-records/metadata-record")] == ["event_date", "user_id", "ggr"]
    assert {c.get("name") for c in new.findall("column")} >= {"[event_date]", "[user_id]", "[ggr]"}
    assert new.find("object-graph/objects/object/properties/relation").get("type") == "text"
    main = book.source("Main")
    assert etree.tostring(main) == main_before


def test_calculation_goes_to_the_named_source(tmp_path):
    book = Book.open(_book(tmp_path))
    _add(book.root)
    book.add_calculated_field("GGR", "SUM([ggr])", datasource="Second")
    book.add_calculated_field("Before End", "[event_date] <= [Parameters].[Period End]",
                              datatype="boolean", datasource="Second")
    book.add_calculated_field("GGR Twice", "[GGR] * 2", datasource="Second")
    second = {c.get("caption"): c for c in book.source("Second").findall("column")}
    main = {c.get("caption") for c in book.source("Main").findall("column")}
    assert {"GGR", "Before End", "GGR Twice"} <= set(second) and "GGR" not in main
    assert "[Parameters].[Parameter 1]" in second["Before End"].find("calculation").get("formula")
    assert second["GGR"].get("name") in second["GGR Twice"].find("calculation").get("formula")


def test_extract_of_one_source_keeps_the_others(tmp_path, monkeypatch):
    book = Book.open(_book(tmp_path))
    _add(book.root)
    path = str(tmp_path / "Two.twbx")
    safexml.write_twbx(book.root, path, "Two.twb", book.members)
    built = []

    def fake_hyper(sql, out, table, types=None):
        built.append(sql)
        open(out, "wb").write(b"hyper")
        return {"rows": 3, "columns": 3}

    monkeypatch.setattr(EX, "build_hyper_from_sql", fake_hyper)
    out = str(tmp_path / "Two (extract).twbx")
    res = EX.to_extract(path, out, only=["Second"])
    assert res["ok"] and [s["source"] for s in res["sources"]] == ["Second"]
    assert len(built) == 1 and "FROM t" in built[0]
    root = safexml.from_twbx(out)
    dss = {d.get("caption"): d for d in root.findall("datasources/datasource")}
    assert dss["Second"].find("extract") is not None and dss["Main"].find("extract") is None
    names = zipfile.ZipFile(out).namelist()
    assert "Data/Extracts/main.hyper" in names
    assert "Two.twb" in names, "the workbook inside keeps its name, not the output file's"
    assert not EX.to_extract(path, out, only=["Nope"])["ok"]


def test_aggregate_text_calculation_colors_as_a_dimension(tmp_path):
    book = Book.open(_book(tmp_path))
    _add(book.root)
    book.add_calculated_field("Status", "IF SUM([ggr]) > 0 THEN 'Up' ELSE 'Down' END",
                              datatype="string", datasource="Second")
    col = next(c for c in book.source("Second").findall("column") if c.get("caption") == "Status")
    assert (col.get("role"), col.get("type")) == ("measure", "nominal")
    book.add_worksheet("S")
    book.configure_chart("S", mark_type="Square", rows=["user_id"], color="Status",
                         color_map={"Up": "#59a14f", "Down": "#e15759"}, datasource="Second")
    enc = book.sheet("S").find(".//pane/encodings/color")
    assert enc.get("column").endswith(":nk]") and "[usr:" in enc.get("column")
    rule = book.source("Second").find("style/style-rule/encoding")
    assert [m.get("to") for m in rule.findall("map")] == ["#59a14f", "#e15759"]


def test_total_label_written_like_desktop(tmp_path):
    from twkit import frame as FR
    book = Book.open(_book(tmp_path))
    _add(book.root)
    book.add_calculated_field("Segment", "IF [ggr] > 0 THEN 'A' ELSE 'B' END", datatype="string",
                              role="dimension", datasource="Second")
    book.add_worksheet("T")
    book.configure_chart("T", mark_type="Text", rows=["Segment"], label="ggr", datasource="Second")
    assert ED.set_total_label(book.root, "T", "Segment", "Total") == 1
    f = next(f for f in book.sheet("T").iter("format") if f.get("attr") == "total-label")
    assert (f.get("data-class"), f.get("value")) == ("total", "Total")
    assert f.getparent().get("element") == "header"
    assert FR.total_label(book.sheet("T")) == "Total"


def test_text_zone_line_break_is_a_run_of_its_own_and_r49_catches_the_old_form(tmp_path):
    from twkit import lint as L
    book = Book.open(_book(tmp_path))
    book.add_dashboard("P", layout={"type": "container", "direction": "vertical",
                                    "children": [{"type": "text", "text": "One.\nTwo."}]})
    runs = [r.text for r in book.root.iter("run")]
    assert runs == ["One.", "Æ\n", "Two."], runs
    assert not L.r49_line_break_inside_run(book)
    next(r for r in book.root.iter("run")).text = "One.Æ\nTwo."
    assert L.r49_line_break_inside_run(book)[0].rule == "R49"
