import zipfile

import pytest

from twkit import lint


def _book(tmp_path, layout_zones, auto="true", name="phone.twbx"):
    inner = "".join(f'<zone id="{i + 50}" name="{z}" w="100000" h="100000" x="0" y="0"/>'
                    for i, z in enumerate(layout_zones))
    xml = f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook xmlns:user="http://www.tableausoftware.com/xml/user" version="18.1">
  <worksheets>
    <worksheet name="A"><table><view/></table></worksheet>
    <worksheet name="B"><table><view/></table></worksheet>
  </worksheets>
  <dashboards>
    <dashboard name="Page">
      <size maxheight="800" maxwidth="1200" minheight="800" minwidth="1200"
            sizing-mode="fixed"/>
      <zones>
        <zone h="100000" id="1" param="vert" type-v2="layout-flow" w="100000" x="0" y="0">
          <zone h="50000" id="2" name="A" w="100000" x="0" y="0"/>
          <zone h="50000" id="3" name="B" w="100000" x="0" y="50000"/>
        </zone>
      </zones>
      <devicelayouts>
        <devicelayout auto-generated="{auto}" name="Phone">
          <size maxheight="700" minheight="700" sizing-mode="vscroll"/>
          <zones>{inner}</zones>
        </devicelayout>
      </devicelayouts>
    </dashboard>
  </dashboards>
</workbook>"""
    path = str(tmp_path / name)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("book.twb", xml)
    return path


def _r36(path):
    return [v for v in lint.lint(path) if v.rule == "R36"]


def test_matching_layout_silent(tmp_path):
    assert _r36(_book(tmp_path, ["A", "B"])) == []


def test_layout_subset_of_page_is_fine(tmp_path):
    assert _r36(_book(tmp_path, ["A"])) == []


def test_sheet_removed_from_page_left_in_phone_layout(tmp_path):
    found = _r36(_book(tmp_path, ["A", "B", "C"]))

    assert len(found) == 1
    assert found[0].severity == lint.WARN
    assert "C" in found[0].message and "Desktop" in found[0].fix


def test_manual_layout_is_error(tmp_path):
    found = _r36(_book(tmp_path, ["A", "B", "C"], auto="false"))

    assert len(found) == 1 and found[0].severity == lint.ERROR
    assert "edit it" in found[0].fix


def test_dashboard_without_phone_layout_ignored(tmp_path):
    xml = """<?xml version='1.0' encoding='utf-8' ?>
<workbook xmlns:user="http://www.tableausoftware.com/xml/user" version="18.1">
  <worksheets><worksheet name="A"><table><view/></table></worksheet></worksheets>
  <dashboards><dashboard name="Page">
    <size maxheight="800" maxwidth="1200" minheight="800" minwidth="1200" sizing-mode="fixed"/>
    <zones><zone h="100000" id="1" name="A" w="100000" x="0" y="0"/></zones>
  </dashboard></dashboards>
</workbook>"""
    path = str(tmp_path / "plain.twbx")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("book.twb", xml)

    assert _r36(path) == []
