import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED

_PARAM = """
      <column caption='p_view' datatype='string' name='[p_view]'
              param-domain-type='list' role='measure' type='nominal' value='&quot;Actual&quot;'>
        <calculation class='tableau' formula='&quot;Actual&quot;' />
        <members>
          <member value='&quot;Actual&quot;' />
          <member value='&quot;Plan &amp; Actual&quot;' />
          <member value='&quot;MoM change&quot;' />
        </members>
      </column>
"""

_WB = f"""<workbook version='18.1'>
  <datasources>
    <datasource hasconnection='false' inline='true' name='Parameters' version='18.1'>
      {_PARAM}
    </datasource>
    <datasource name='federated.x'>
      <column datatype='real' name='[Money]' role='measure' type='quantitative' />
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='A'><table><view>
      <datasource-dependencies datasource='Parameters'>{_PARAM}</datasource-dependencies>
    </view></table></worksheet>
    <worksheet name='B'><table><view>
      <datasource-dependencies datasource='Parameters'>{_PARAM}</datasource-dependencies>
    </view></table></worksheet>
  </worksheets>
  <dashboards>
    <dashboard name='D'>
      <datasource-dependencies datasource='Parameters'>{_PARAM}</datasource-dependencies>
    </dashboard>
  </dashboards>
</workbook>
"""


def _root():
    return etree.fromstring(_WB.encode("utf-8"))


def test_value_set_in_all_declarations():
    root = _root()
    assert ED.set_parameter_value(root, "p_view", "Plan & Actual") == 4
    vals = {c.get("value") for c in root.iter("column") if c.get("param-domain-type")}
    assert vals == {'"Plan & Actual"'}
    forms = {c.find("calculation").get("formula")
             for c in root.iter("column") if c.get("param-domain-type")}
    assert forms == {'"Plan & Actual"'}


def test_parameter_members_read_unquoted():
    assert ED.parameter_members(_root(), "p_view") == [
        "Actual", "Plan & Actual", "MoM change"]


def test_foreign_parameter_untouched():
    root = _root()
    assert ED.set_parameter_value(root, "p_detail", "Totals only") == 0
    assert {c.get("value") for c in root.iter("column")
            if c.get("param-domain-type")} == {'"Actual"'}


def test_regular_columns_untouched():
    root = _root()
    ED.set_parameter_value(root, "p_view", "Plan")
    money = [c for c in root.iter("column") if c.get("name") == "[Money]"][0]
    assert money.get("value") is None


def test_color_census_counts_only_colored(tmp_path):
    from PIL import Image

    from twkit import shot as SHOT

    im = Image.new("RGB", (40, 40), (245, 245, 245))
    for x in range(0, 20):
        for y in range(0, 40):
            im.putpixel((x, y), (0, 255, 0))
    p = tmp_path / "probe.png"
    im.save(p)
    res = SHOT.color_census(str(p), {"lime": "#00ff00", "magenta": "#ff00ff"})
    assert res["ok"]
    assert res["pixels"]["lime"] > 100
    assert res["pixels"]["magenta"] == 0


def _fake_book(tmp_path):
    import zipfile
    p = tmp_path / "S.twbx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("S.twb", _WB)
    return str(p)


def test_empty_in_one_state_not_blocker(tmp_path, monkeypatch):
    from twkit import dryrun as DR

    calls = {"n": 0}

    def fake_dry_run(path, db="", table="", limit=5, sample_rows=3, **kw):
        calls["n"] += 1
        first = calls["n"] == 1
        return [DR.SheetResult(sheet="A", status="empty" if first else "ok", rows=0),
                DR.SheetResult(sheet="B", status="ok" if first else "empty", rows=1)]

    monkeypatch.setattr(DR, "dry_run", fake_dry_run)
    res = DR.dry_run_states(_fake_book(tmp_path))
    assert res["states"] == 3
    assert res["empty_in_all_states"] == []
    assert res["ok"] is True


def test_sheet_empty_in_all_states_is_blocker(tmp_path, monkeypatch):
    from twkit import dryrun as DR

    monkeypatch.setattr(DR, "dry_run", lambda path, db="", table="", limit=5,
                        sample_rows=3, **kw: [
                            DR.SheetResult(sheet="A", status="empty", rows=0),
                            DR.SheetResult(sheet="B", status="ok", rows=1)])
    res = DR.dry_run_states(_fake_book(tmp_path))
    assert res["empty_in_all_states"] == ["A"]
    assert res["ok"] is False


def test_source_pseudo_sheet_not_defect(tmp_path, monkeypatch):
    from twkit import dryrun as DR

    monkeypatch.setattr(DR, "dry_run", lambda path, db="", table="", limit=5,
                        sample_rows=3, **kw: [
                            DR.SheetResult(sheet="(source)", status="empty")])
    assert DR.dry_run_states(_fake_book(tmp_path))["empty_in_all_states"] == []


def test_states_do_not_write_package(tmp_path, monkeypatch):
    from twkit import dryrun as DR
    from twkit import safexml

    def no_write(*a, **kw):
        raise AssertionError("the states channel must not write the package to disk")

    monkeypatch.setattr(safexml, "to_twbx", no_write)
    monkeypatch.setattr(DR, "dry_run",
                        lambda path, db="", table="", limit=5, sample_rows=3, **kw: [
                            DR.SheetResult(sheet="A", status="ok", rows=1)])
    res = DR.dry_run_states(_fake_book(tmp_path))
    assert res["states"] >= 1


def test_unpacked_extract_from_cache(tmp_path):
    import zipfile

    from twkit import dryrun as DR
    book = tmp_path / "Book.twbx"
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("Book.twb", "<workbook/>")
        z.writestr("Data/Extracts/x.hyper", b"not a real hyper")
    a = DR._unpack_member(str(book), "Data/Extracts/x.hyper")
    b = DR._unpack_member(str(book), "Data/Extracts/x.hyper")
    assert a == b
    c = DR._unpack_member(str(book), "Data/Extracts/x.hyper", fresh=True)
    assert c != a
