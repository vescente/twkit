import json
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "mcp"))

import pytest
from lxml import etree

from twkit import owner as OW
from twkit import safexml


def _book(path, sheets=("A", "B"), calcs=("Turnover",), dashes=("Report",)):
    ws = "".join(f"<worksheet name='{s}'/>" for s in sheets)
    ds = "".join(f"<dashboard name='{d}'><zones><zone name='{d} z1'/></zones></dashboard>"
                 for d in dashes)
    cs = "".join(f"<column name='[{c}]'><calculation formula='SUM([x])'/></column>"
                 for c in calcs)
    xml = (f"<workbook><datasources><datasource name='ds'>"
           f"<column name='[x]' datatype='real'/>{cs}</datasource></datasources>"
           f"<worksheets>{ws}</worksheets><dashboards>{ds}</dashboards></workbook>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("b.twb", xml)
    return path


@pytest.fixture
def book(tmp_path):
    return _book(str(tmp_path / "Book.twbx"))


def test_inventory_counts_names_not_quantities(book):
    inv = OW.inventory(safexml.from_twbx(book))
    assert inv["sheets"] == ["A", "B"]
    assert inv["pages"] == ["Report"]
    assert inv["calculations"] == ["Turnover"]
    assert inv["fields"] == ["x"]
    assert inv["zones"] == ["Report::Report z1"]


def test_undeclared_loss_visible_declared_not():
    was = {"sheets": ["A", "B"], "fields": ["x", "Aggregator"]}
    now = {"sheets": ["A"], "fields": ["x"]}
    assert OW.regressions(was, now) == {"sheets": ["B"], "fields": ["Aggregator"]}
    assert OW.regressions(was, now, allowed=["Aggregator"]) == {"sheets": ["B"]}


def test_install_refuses_to_roll_back_owner_work(tmp_path):
    owner_book = _book(str(tmp_path / "Owner.twbx"), sheets=("A", "B", "THEIR NEW"))
    built = _book(str(tmp_path / "built.twbx"), sheets=("A", "B"))
    before = OW.inventory(safexml.from_twbx(owner_book))
    after = OW.inventory(safexml.from_twbx(built))
    md5_was = OW.md5(owner_book)

    with pytest.raises(OW.Refused) as e:
        OW.install(built, owner_book, inventory_before=before, inventory_after=after)
    assert "THEIR NEW" in str(e.value)
    assert OW.md5(owner_book) == md5_was
    snaps = os.listdir(os.path.join(str(tmp_path), OW.SNAP_DIR_NAME, "Owner"))
    assert len(snaps) == 1


def test_declared_loss_passes_and_is_recorded(tmp_path):
    owner_book = _book(str(tmp_path / "Owner.twbx"), calcs=("Turnover", "RTP Bonus"))
    built = _book(str(tmp_path / "built.twbx"), calcs=("Turnover",))
    before = OW.inventory(safexml.from_twbx(owner_book))
    after = OW.inventory(safexml.from_twbx(built))

    r = OW.install(built, owner_book, allowed_losses=["RTP Bonus"],
                   inventory_before=before, inventory_after=after)
    assert r["losses"] == {}
    assert OW.md5(owner_book) == OW.md5(built)
    rec = OW.last_install(owner_book)
    assert rec["deliberately_removed"] == ["RTP Bonus"]


def test_owner_edit_after_us_visible(tmp_path):
    owner_book = _book(str(tmp_path / "Owner.twbx"))
    built = _book(str(tmp_path / "built.twbx"))
    assert OW.owner_touched(owner_book) is True

    OW.install(built, owner_book)
    assert OW.owner_touched(owner_book) is False
    assert OW.guard_source(owner_book)["owner_edited_since_install"] is False

    _book(owner_book, sheets=("A", "B", "they added"))
    assert OW.owner_touched(owner_book) is True
    assert "ON TOP" in OW.guard_source(owner_book)["reading"]


def test_snapshots_accumulate(tmp_path):
    owner_book = _book(str(tmp_path / "Owner.twbx"))
    first = OW.snapshot(owner_book)
    _book(owner_book, sheets=("A", "B", "C"))
    second = OW.snapshot(owner_book)
    assert first != second
    assert OW.inventory(safexml.from_twbx(first))["sheets"] == ["A", "B"]
    assert OW.inventory(safexml.from_twbx(second))["sheets"] == ["A", "B", "C"]


def test_screenshots_next_to_book(tmp_path):
    owner_book = _book(str(tmp_path / "Owner.twbx"))
    snap = OW.snapshot(owner_book)
    assert os.path.dirname(os.path.dirname(snap)) == \
        os.path.join(str(tmp_path), OW.SNAP_DIR_NAME)


def test_prune_removes_old_but_not_marked(tmp_path):
    book = _book(str(tmp_path / "Owner.twbx"))
    for i in range(5):
        _book(book, sheets=tuple(f"S{j}" for j in range(i + 1)))
        OW.snapshot(book, tag=f"n{i}")
    d = os.path.join(str(tmp_path), OW.SNAP_DIR_NAME, "Owner")
    old = sorted(os.listdir(d))[0]
    os.rename(os.path.join(d, old), os.path.join(d, old.replace(".twbx", "-keep.twbx")))

    r = OW.prune(book, keep=2)
    left = sorted(os.listdir(d))
    assert len(left) == 3, left
    assert any("keep" in f for f in left)
    assert len(r["deleted"]) == 2


def test_rename_not_a_loss():
    before = {"pages": ["Viz", "Report"],
              "zones": ["Viz::Top players", "Report::Legend"],
              "sheets": ["Top players"]}
    after = {"pages": ["Trends", "Report"],
             "zones": ["Trends::Top players", "Report::Legend"],
             "sheets": ["Top players"]}
    assert OW.regressions(before, after) != {}
    assert OW.regressions(before, after, renames={"Viz": "Trends"}) == {}


def test_loss_next_to_rename_still_visible():
    before = {"pages": ["Viz", "Report"], "sheets": ["Top players", "RTP trend"]}
    after = {"pages": ["Trends", "Report"], "sheets": ["Top players"]}
    got = OW.regressions(before, after, renames={"Viz": "Trends"})
    assert got == {"sheets": ["RTP trend"]}, got


def test_rename_updates_composite_zone_key():
    got = OW.apply_renames({"zones": ["Viz::horz", "Viz::[Parameters].[P1]"]},
                           {"Viz": "Trends"})
    assert got["zones"] == ["Trends::[Parameters].[P1]", "Trends::horz"]


def test_install_refuses_when_book_open(tmp_path, monkeypatch):
    import subprocess as _sp

    import pytest

    from twkit import owner

    class _Held:
        stdout = "COMMAND PID\nTableau 123"

    monkeypatch.setattr(_sp, "run", lambda *a, **k: _Held())

    built = tmp_path / "b.twbx"
    book = tmp_path / "Report.twbx"
    built.write_bytes(b"new")
    book.write_bytes(b"old")
    lock = tmp_path / ".~Report__8251.twbr"
    lock.write_bytes(b"")

    assert owner.opened_in_tableau(str(book)).endswith("__8251.twbr")
    with pytest.raises(OW.Refused, match="open in Tableau"):
        owner.install(str(built), str(book))
    assert book.read_bytes() == b"old"

    lock.unlink()
    assert owner.opened_in_tableau(str(book)) == ""
    owner.install(str(built), str(book))
    assert book.read_bytes() == b"new"


def test_capture_opens_copy_not_owner_file(tmp_path):
    from twkit import shot

    src = tmp_path / "Book.twbx"
    src.write_bytes(b"data")
    copy = shot.work_copy(str(src))
    assert os.path.abspath(copy) != os.path.abspath(src)
    assert open(copy, "rb").read() == b"data"


def test_capture_comparison_catches_view_change(tmp_path):
    from PIL import Image

    from twkit import shot

    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    img = Image.new("RGB", (40, 20), "white")
    img.save(a)
    img.save(b)
    assert shot.compare(str(a), str(b))["changed_share"] == 0.0

    img2 = Image.new("RGB", (40, 20), "white")
    for x in range(10):
        for y in range(10):
            img2.putpixel((x, y), (0, 0, 0))
    img2.save(b)
    got = shot.compare(str(a), str(b), out_path=str(tmp_path / "d.png"))
    assert got["changed_share"] == 0.125
    assert got["change_area"] == (0, 0, 10, 10)
    assert os.path.exists(got["diff_map"])


def test_capture_compared_zero_diff_is_signal(tmp_path):
    from PIL import Image

    from twkit import shot

    cur = tmp_path / "book.png"
    Image.new("RGB", (40, 20), "white").save(cur)

    assert shot._keep_previous(str(tmp_path / "missing.png")) == ""

    prev = shot._keep_previous(str(cur))
    assert prev and os.path.exists(prev)

    same = shot.changed_since(prev, str(cur))
    assert same["changed_share"] == 0.0
    assert "did NOT change" in same["verdict"]

    img = Image.new("RGB", (40, 20), "white")
    for x in range(10):
        for y in range(10):
            img.putpixel((x, y), (0, 0, 0))
    img.save(cur)
    diff = shot.changed_since(prev, str(cur))
    assert diff["changed_share"] == 0.125
    assert "changed" in diff["verdict"]
    assert diff["reference"] == prev


def test_broken_reference_does_not_break_channel(tmp_path):
    from PIL import Image

    from twkit import shot

    cur = tmp_path / "ok.png"
    Image.new("RGB", (10, 10), "white").save(cur)
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not a png")

    res = shot.changed_since(str(bad), str(cur))
    assert "failed" in res["verdict"]


def test_refusal_caught_as_regular_exception():
    assert issubclass(OW.Refused, Exception)
    assert not issubclass(OW.Refused, SystemExit)


def test_one_ai_folder_at_workbooks_root(tmp_path):
    from twkit import owner as O
    root = tmp_path / "Workbooks"
    book = root / "Demo" / "site" / "v3" / "Churn.twbx"
    book.parent.mkdir(parents=True)
    book.write_bytes(b"old")
    built = tmp_path / "built.twbx"
    built.write_bytes(b"new")
    r = O.install(str(built), str(book))
    assert r["snapshot"].startswith(str(root / "_ai" / "Demo" / "site" / "v3" / "Churn"))
    assert not (book.parent / "_ai").exists()
    assert O.last_install(str(book))["md5"] == O.md5(str(book))
    assert O.book_key(str(book)) == "Demo/site/v3/Churn.twbx"


def _suggest_book(calcs: str, params: str = "", sheets: str = "", zones: str = "", extra: str = ""):
    return safexml.from_bytes((
        "<workbook><datasources><datasource name='Parameters'>" + params + "</datasource>"
        "<datasource name='ds'><connection><relation><columns><column name='v'/></columns></relation>"
        "</connection>" + calcs + extra + "</datasource></datasources><worksheets>" + sheets +
        "</worksheets><dashboards><dashboard name='P'><zones>" + zones +
        "</zones></dashboard></dashboards></workbook>").encode())


def test_suggest_derives_renames_from_facts_and_applies_nothing():
    calc = "<column name='[c{n}]' caption='{cap}'><calculation formula='{f}'/></column>"
    par = "<column name='[p]' caption='{cap}' param-domain-type='list'><member value='1'/><member value='2'/></column>"
    ws = "<worksheet name='{n}'><table><view><filter column='[ds].[none:id:nk]' member='{k}'/></view></table></worksheet>"
    before = _suggest_book(calc.format(n=1, cap="Profit Ratio", f="SUM([a])/SUM([b])") +
                   calc.format(n=2, cap="Old helper", f="1"),
                   par.format(cap="Metric"), ws.format(n="Old name", k="A"),
                   "<zone name='Old name'/><zone param='horz'/>",
                   "<column name='[Down]' datatype='string'/>")
    after = _suggest_book(calc.format(n=9, cap="Profit ratio", f="SUM([a]) / SUM([b])"),
                  par.format(cap="Metric switch"), ws.format(n="New name", k="A"),
                          "<zone name='New name'/>")
    key = lambda w: next((f.get("member") for f in w.iter("filter")), None)
    got = OW.suggest(before, after, sheet_key=key)
    assert got["renames"] == {"Profit Ratio": "Profit ratio", "Metric": "Metric switch",
                              "Old name": "New name", "P::Old name": "P::New name"}
    assert set(got["harmless"]) == {"Old helper", "Down", "horz"}
    assert all(got["harmless"].values())
    ib, ia = OW.inventory(before), OW.inventory(after)
    assert OW.regressions(ib, ia, got["harmless"], got["renames"]) == {}
    assert OW.regressions(ib, ia), "suggest changes nothing by itself: the guard still refuses"


def test_suggest_keeps_spaces_inside_string_literals():
    calc = "<column name='[c{n}]' caption='{cap}'><calculation formula=\"{f}\"/></column>"
    before = _suggest_book(calc.format(n=1, cap="City", f="IF [x] = 'New York' THEN 1 END"))
    after = _suggest_book(calc.format(n=2, cap="Town", f="IF [x]='NewYork' THEN 1 END"))
    assert "City" not in OW.suggest(before, after)["renames"]
    after = _suggest_book(calc.format(n=2, cap="Town", f="IF [x]='New York' THEN 1 END"))
    assert OW.suggest(before, after)["renames"] == {"City": "Town"}


def test_an_installed_book_is_written_only_through_install(tmp_path):
    owner_book = _book(str(tmp_path / "Owner.twbx"))
    built = _book(str(tmp_path / "built.twbx"))
    inv = OW.inventory(safexml.from_twbx(owner_book))
    OW.install(built, owner_book, inventory_before=inv, inventory_after=inv)
    with pytest.raises(PermissionError, match="owner_install"):
        safexml.to_twbx(owner_book, safexml.from_twbx(owner_book), owner_book)
    safexml.to_twbx(built, safexml.from_twbx(built), str(tmp_path / "copy.twbx"))


def test_protected_folder_with_writable_exceptions(tmp_path, monkeypatch):
    from twkit import config
    root, free = tmp_path / "Workbooks", tmp_path / "Workbooks" / "_ai"
    free.mkdir(parents=True)
    monkeypatch.setattr(config, "_section", lambda name: {"protected": [str(root)], "writable": [str(free)]}
                        if name == "guard" else {})
    assert OW.protected(str(root / "Demo" / "x.twbx"))
    assert OW.protected(str(free / "v3next" / "x.twbx")) == ""
    assert OW.protected(str(tmp_path / "elsewhere.twbx")) == ""


def test_save_workbook_refuses_the_owners_book(tmp_path):
    import asyncio
    pytest.importorskip("mcp")
    import _matrix_book as M
    from twkit.server.app import register_all
    server = register_all()
    built = M.build(str(tmp_path))
    owner_book = str(tmp_path / "Owner.twbx")
    shutil.copy2(built, owner_book)
    inv = OW.inventory(safexml.from_twbx(owner_book))
    OW.install(built, owner_book, inventory_before=inv, inventory_after=inv)
    was = OW.md5(owner_book)

    def call(tool, **kw):
        r = asyncio.run(server.call_tool(tool, kw))
        blocks = r[0] if isinstance(r, tuple) else r
        return " ".join(getattr(b, "text", str(b)) for b in blocks)
    call("open_workbook", file_path=owner_book)
    assert call("save_workbook", output_path=owner_book).startswith("REFUSED")
    assert OW.md5(owner_book) == was
