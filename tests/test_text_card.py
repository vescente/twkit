import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED
from twkit import lint as LN

DS = "federated.test"


def _book():
    return etree.fromstring(f"""
<workbook>
  <datasources>
    <datasource caption='T' name='{DS}'>
      <column caption='Group' datatype='string' name='[grp]' role='dimension' type='nominal'/>
      <column caption='Roi' datatype='real' name='[roi]' role='measure' type='quantitative'/>
      <column caption='Net' datatype='real' name='[net]' role='measure' type='quantitative'/>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Cards'>
      <table>
        <view>
          <datasources><datasource caption='T' name='{DS}'/></datasources>
          <datasource-dependencies datasource='{DS}'/>
        </view>
        <panes><pane><mark class='Bar'/></pane></panes>
        <rows/><cols/>
      </table>
    </worksheet>
  </worksheets>
</workbook>""")


def _card(root, **kw):
    return ED.text_card(root, "Cards", "grp", [
        {"field": "[roi]", "size": "18", "bold": True, "color": "#2c3a47"},
        {"field": "[net]", "size": "9", "color": "#6b7a8c", "caption": "Net "},
    ], **kw)


def test_dimension_to_columns_no_rows():
    root = _book()
    out = _card(root)
    assert out["line_count"] == 2
    table = root.find(".//worksheet/table")
    assert table.find("cols").text == f"[{DS}].[none:grp:nk]"
    assert not (table.find("rows").text or "")


def test_measures_on_text_individually():
    root = _card_root = _book()
    _card(root)
    enc = root.find(".//pane/encodings")
    assert [t.get("column") for t in enc.findall("text")] == [
        f"[{DS}].[usr:roi:qk]", f"[{DS}].[usr:net:qk]"]
    assert "Measure Names" not in etree.tostring(_card_root, encoding="unicode")


def test_caption_and_newline_live_in_label():
    root = _book()
    _card(root)
    runs = root.findall(".//customized-label/formatted-text/run")
    assert runs[0].get("fontsize") == "18" and runs[0].get("bold") == "true"
    assert runs[0].text.endswith("\n")
    assert runs[1].text == "Net "
    assert not runs[-1].text.endswith("\n")


def test_text_mark_and_no_color_encoding():
    root = _book()
    _card(root)
    pane = root.find(".//pane")
    assert pane.find("mark").get("class") == "Text"
    assert pane.find("encodings/color") is None


def test_alignment_applied_to_all_elements():
    root = _book()
    _card(root, align="center")
    aligns = {f.get("value") for f in root.findall(".//table/style//format")
              if f.get("attr") == "text-align"}
    assert aligns == {"center"}


def test_lint_flags_color_overriding_label_lines():
    root = _book()
    _card(root)

    class _B:
        pass

    b = _B()
    b.root = root
    assert LN.r38_label_color_overridden(b) == []

    c = etree.SubElement(root.find(".//pane/encodings"), "color")
    c.set("column", f"[{DS}].[none:grp:nk]")
    (v,) = LN.r38_label_color_overridden(b)
    assert v.rule == "R38" and "colors the whole label" in v.message


def test_tail_after_value_in_own_run_with_newline():
    root = _book()
    ED.text_card(root, "Cards", "grp", [
        {"field": "[roi]", "size": "18"},
        {"field": "[net]", "caption": "ACROSS ", "suffix": " ACTIVES", "size": "9"},
        {"field": "[roi]", "suffix": " HIGH RISK", "size": "9"},
    ])
    runs = [r.text for r in root.findall(".//customized-label/formatted-text/run")]
    assert runs[0].endswith("\n")
    assert runs[1] == "ACROSS "
    assert runs[2].startswith("<") and not runs[2].endswith("\n")
    assert runs[3] == " ACTIVES\n"
    assert runs[-1] == " HIGH RISK"


def test_file_column_declared_bracketed_with_role():
    root = etree.fromstring(f"""
<workbook>
  <datasources>
    <datasource caption='T' name='{DS}'>
      <connection class='textscan'><columns header='yes'>
        <column datatype='string' name='dim_1' ordinal='2'/>
        <column datatype='real' name='value' ordinal='3'/>
      </columns></connection>
      <column caption='Roi' datatype='real' name='[roi]' role='measure' type='quantitative'/>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Cards'>
      <table>
        <view>
          <datasources><datasource caption='T' name='{DS}'/></datasources>
          <datasource-dependencies datasource='{DS}'/>
        </view>
        <panes><pane><mark class='Bar'/></pane></panes>
        <rows/><cols/>
      </table>
    </worksheet>
  </worksheets>
</workbook>""")
    ED.text_card(root, "Cards", "dim_1", [{"field": "[roi]", "size": "18"}])
    dep = root.find(".//datasource-dependencies")
    names = {c.get("name"): c for c in dep.findall("column")}
    assert "[dim_1]" in names and "dim_1" not in names
    assert names["[dim_1]"].get("role") == "dimension" and names["[dim_1]"].get("type") == "nominal"
    assert root.find(".//columns/column").get("name") == "dim_1"
