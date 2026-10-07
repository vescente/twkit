import pytest
from lxml import etree

from twkit import edit as ED

USER_NS = "http://www.tableausoftware.com/xml/user"
DS = "federated.aaaa"

BOOK = f"""<workbook xmlns:user="{USER_NS}">
  <datasources>
    <datasource caption="Flow" name="{DS}">
      <connection class="federated"/>
      <column datatype="string" name="[segment]" role="dimension" type="nominal"/>
      <column-instance column="[segment]" derivation="None" name="[none:segment:nk]"
                       pivot="key" type="nominal"/>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name="flow"><table><view>
      <datasources><datasource caption="Flow" name="{DS}"/></datasources>
      <datasource-dependencies datasource="{DS}">
        <column datatype="string" name="[segment]" role="dimension" type="nominal"/>
        <column-instance column="[segment]" derivation="None" name="[none:segment:nk]"
                         pivot="key" type="nominal"/>
      </datasource-dependencies>
      <aggregation value="true"/>
    </view>
    <rows>[{DS}].[none:segment:nk]</rows></table></worksheet>
  </worksheets>
</workbook>"""


def _book():
    return etree.fromstring(BOOK.encode("utf-8"))


def test_exclusion_adds_group_to_source_and_filter_to_sheet():
    root = _book()

    res = ED.exclude_members(root, "flow", "segment", ["Pre-segment"])

    assert res["ok"] and res["excluded"] == 1
    group = root.find(f'.//datasource[@name="{DS}"]/group')
    assert group.get("name") == "[Exclusions (segment)]"
    assert group.get("hidden") == "true"
    assert group.get(f"{{{USER_NS}}}auto-column") == "exclude"
    assert group.find("groupfilter[@function='crossjoin']/"
                      "groupfilter[@function='level-members']") is not None

    filt = root.find(f'.//filter[@column="[{DS}].[Exclusions (segment)]"]')
    exc = filt.find("groupfilter")
    assert exc.get("function") == "except"
    assert exc.get(f"{{{USER_NS}}}ui-enumeration") == "exclusive"
    mem = filt.find(".//groupfilter[@function='member']")
    assert mem.get("member") == '"Pre-segment"'


def test_several_values_collected_in_union():
    root = _book()

    ED.exclude_members(root, "flow", "segment", ["A", "B", "C"])

    union = root.find(".//groupfilter[@function='union']")
    assert union is not None
    assert len(union.findall("groupfilter[@function='member']")) == 3


def test_single_value_without_union():
    root = _book()

    ED.exclude_members(root, "flow", "segment", ["A"])

    assert root.find(".//groupfilter[@function='union']") is None


def test_numbers_and_booleans_unquoted():
    assert ED._member_literal("Europe") == '"Europe"'
    assert ED._member_literal(2019) == "2019"
    assert ED._member_literal(True) == "true"
    assert ED._member_literal("1", datatype="integer") == "1"


def test_filter_in_slices_not_duplicated():
    root = _book()

    ED.exclude_members(root, "flow", "segment", ["A"])
    ED.exclude_members(root, "flow", "segment", ["B"])

    view = root.find(".//view")
    cols = [c.text for c in view.find("slices").findall("column")]
    assert cols.count(f"[{DS}].[Exclusions (segment)]") == 1
    assert len(view.findall("filter")) == 1
    mem = view.find(".//groupfilter[@function='member']")
    assert mem.get("member") == '"B"'
    ds = root.find(f'.//datasource[@name="{DS}"]')
    assert len(ds.findall("group")) == 1


def test_empty_list_refused_not_zero():
    root = _book()

    res = ED.exclude_members(root, "flow", "segment", [])

    assert res["ok"] is False and "excluded 0" in res["why"]
    assert root.find(".//group") is None


def test_dry_run_sees_exclusion(tmp_path):
    import shutil
    import zipfile

    from lxml import etree

    from twkit import dryrun, safexml
    from tests.test_dryrun_two_extracts import _book

    src = _book(tmp_path)
    before = {r.sheet: r for r in dryrun.dry_run(src, limit=100)}
    assert before["flow sheet"].rows == 2

    root = safexml.from_twbx(src)
    ED.exclude_members(root, "flow sheet", "segment", ["Dormant"])
    body = etree.tostring(root, xml_declaration=True, encoding="utf-8", standalone=True)
    dst = str(tmp_path / "excluded.twbx")
    with zipfile.ZipFile(src) as z, zipfile.ZipFile(dst, "w") as o:
        inner = [n for n in z.namelist() if n.endswith(".twb")][0]
        for n in z.namelist():
            o.writestr(n, body if n == inner else z.read(n))

    after = {r.sheet: r for r in dryrun.dry_run(dst, limit=100)}
    assert after["flow sheet"].status == "ok"
    assert after["flow sheet"].rows == 1, after["flow sheet"].sql
    assert "NOT (" in after["flow sheet"].sql


def test_tuple_exclusion_translated_to_not_on_two_fields():
    from lxml import etree

    from twkit.dryrun import Translator, _except_conditions

    xml = """<filter class='categorical' column='[ds].[Exclusions (a,b)]'>
      <groupfilter function='except'>
        <groupfilter function='crossjoin'>
          <groupfilter function='level-members' level='[none:a:nk]'/>
          <groupfilter function='level-members' level='[none:b:nk]'/>
        </groupfilter>
        <groupfilter function='reorder-dimensionality'>
          <groupfilter function='crossjoin'>
            <groupfilter function='member' level='[none:a:nk]' member='"x"'/>
            <groupfilter function='union'>
              <groupfilter function='member' level='[none:b:nk]' member='"p"'/>
              <groupfilter function='member' level='[none:b:nk]' member='"q"'/>
            </groupfilter>
          </groupfilter>
        </groupfilter>
      </groupfilter>
    </filter>"""
    tr = Translator({}, {}, {}, {"a", "b"}, dialect="hyper")

    got = _except_conditions(etree.fromstring(xml), tr)

    assert got == "(NOT (a IN ('x') AND b IN ('p', 'q')))"


def test_unknown_level_not_translated():
    from lxml import etree

    from twkit.dryrun import Translator, _except_conditions

    xml = """<filter class='categorical' column='[ds].[Exclusions (ghost)]'>
      <groupfilter function='except'>
        <groupfilter function='reorder-dimensionality'>
          <groupfilter function='member' level='[none:ghost:nk]' member='"x"'/>
        </groupfilter>
      </groupfilter>
    </filter>"""
    tr = Translator({}, {}, {}, {"a"}, dialect="hyper")

    assert _except_conditions(etree.fromstring(xml), tr) == ""
