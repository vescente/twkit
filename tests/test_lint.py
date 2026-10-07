import glob
import os
import shutil
import zipfile

import pytest

from twkit.lint import ERROR, WARN, counts, lint
from _userdata import FIXTURES, CORPUS, INSPIRATION  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))


@pytest.fixture(scope="session")
def clean_book(tmp_path_factory) -> str:
    from twkit.book import Book

    from twkit.schema import apply_to_workbook, fetch_schema
    from twkit import config

    fields = fetch_schema("reports", "partner_daily")
    wb = Book()
    wb.set_mysql_connection(server=config.get("host"), dbname="reports", username=config.get("user"),
                            table_name="partner_daily", port=config.get("port"))
    apply_to_workbook(wb, fields)
    wb.add_parameter("p_start_dt", datatype="date", domain_type="any", default_value="2026-07-01")
    wb.add_parameter("p_metric", datatype="string", domain_type="list",
                     default_value="NGR", allowed_values=["NGR", "GGR"])
    wb.add_worksheet("ngr")
    wb.configure_chart("ngr", mark_type="Bar", columns=["event_date"], rows=["ngr"])
    out = str(tmp_path_factory.mktemp("lint") / "clean.twbx")
    wb.save(out)
    return out


def _mutate(src: str, tmp_path, replace: tuple[str, str], name: str = "broken.twb") -> str:
    with zipfile.ZipFile(src) as z:
        inner = [n for n in z.namelist() if n.endswith(".twb")][0]
        txt = z.read(inner).decode("utf-8")
    old, new = replace
    assert old in txt
    dst = str(tmp_path / name)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(txt.replace(old, new, 1))
    return dst


def _rules(violations, severity=ERROR) -> set[str]:
    return {v.rule for v in violations if v.severity == severity}


def test_clean_book_passes(clean_book):
    v = lint(clean_book)
    assert counts(v)[ERROR] == 0, "\n".join(str(x) for x in v)


@pytest.mark.skipif(not os.path.isdir(CORPUS), reason="owner corpus not available")
def test_owner_corpus_has_no_errors():
    dirty = {}
    for f in sorted(glob.glob(os.path.join(CORPUS, "*.twbx"))):
        v = lint(f)
        if counts(v)[ERROR]:
            dirty[os.path.basename(f)] = [str(x) for x in v if x.severity == ERROR]
    assert not dirty, dirty


def test_out_dir_has_no_errors():
    dirty = {}
    for f in sorted(glob.glob(os.path.join(FIXTURES, "*.twb*"))):
        v = lint(f)
        if counts(v)[ERROR]:
            dirty[os.path.basename(f)] = [str(x) for x in v if x.severity == ERROR]
    assert not dirty, dirty


def test_r01_broken_header(clean_book, tmp_path):
    p = _mutate(clean_book, tmp_path, ("encoding='utf-8'", "encoding='UTF-8'"))
    assert "R01" in _rules(lint(p))


def test_r01_workbook_glued_to_comment(clean_book, tmp_path):
    p = _mutate(clean_book, tmp_path, ("-->\n<workbook", "--><workbook"))
    assert "R01" in _rules(lint(p))


def test_r02_date_param_without_hashes(clean_book, tmp_path):
    p = _mutate(clean_book, tmp_path, ('value="#2026-07-01#"', 'value="2026-07-01"'))
    assert "R02" in _rules(lint(p))


def test_r03_string_param_quantitative(clean_book, tmp_path):
    p = _mutate(clean_book, tmp_path,
                ('datatype="string" name="[Parameter 2]" param-domain-type="list" role="measure" type="nominal"',
                 'datatype="string" name="[Parameter 2]" param-domain-type="list" role="measure" type="quantitative"'))
    assert "R03" in _rules(lint(p))


def test_r06_mysql_without_prompt(clean_book, tmp_path):
    p = _mutate(clean_book, tmp_path, ('workgroup-auth-mode="prompt"', 'workgroup-auth-mode=""'))
    assert "R06" in _rules(lint(p))


def test_r07_hyper_not_packed(clean_book, tmp_path):
    src = str(tmp_path / "noextract.twbx")
    shutil.copy(clean_book, src)
    with zipfile.ZipFile(src) as z:
        inner = [n for n in z.namelist() if n.endswith(".twb")][0]
        txt = z.read(inner).decode("utf-8")
    txt = txt.replace("class='mysql'", "class='hyper'", 1).replace('class="mysql"', 'class="hyper"', 1)
    txt = txt.replace('dbname="reports"', 'dbname="Data/Extracts/x.hyper"', 1)
    txt = txt.replace("dbname='reports'", "dbname='Data/Extracts/x.hyper'", 1)
    dst = str(tmp_path / "noextract2.twbx")
    with open(str(tmp_path / "x.hyper"), "wb") as f:
        f.write(b"stub")
    with zipfile.ZipFile(dst, "w") as z:
        z.writestr("book.twb", txt)
    assert "R07" in _rules(lint(dst))


def test_r07_hyper_packed_but_unreachable(clean_book, tmp_path):
    from twkit.extract import drop_packaged_extracts, packaged_extracts

    with zipfile.ZipFile(clean_book) as z:
        inner = [n for n in z.namelist() if n.endswith(".twb")][0]
        txt = z.read(inner).decode("utf-8")
    dst = str(tmp_path / "orphan.twbx")
    with zipfile.ZipFile(dst, "w") as z:
        z.writestr("book.twb", txt)
        z.writestr("Data/foreign.twb Files/x.hyper", b"stub" * 100)
    assert "R07" in _rules(lint(dst), WARN)
    assert packaged_extracts(dst)["extra"] == ["Data/foreign.twb Files/x.hyper"]

    drop_packaged_extracts(dst)
    assert packaged_extracts(dst)["extra"] == []
    assert "R07" not in _rules(lint(dst), WARN)
    with zipfile.ZipFile(dst) as z:
        assert [n for n in z.namelist() if n.endswith(".twb")]


def test_r04_boolean_calc_summed(clean_book, tmp_path):
    with zipfile.ZipFile(clean_book) as z:
        inner = [n for n in z.namelist() if n.endswith(".twb")][0]
        txt = z.read(inner).decode("utf-8")
    calc = ("<column caption='_filter_period' datatype='boolean' name='[Calculation_999]' "
            "role='measure' type='quantitative'>"
            "<calculation class='tableau' formula='[event_date] &gt; #2026-01-01#' />"
            "</column>")
    txt = txt.replace("</datasource>", calc + "\n</datasource>", 1)
    txt = txt.replace("</worksheet>",
                      "<filter column='[sum:Calculation_999:qk]' /></worksheet>", 1)
    dst = str(tmp_path / "boolcalc.twb")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(txt)
    v = lint(dst)
    assert "R04" in _rules(v), "\n".join(str(x) for x in v)


def test_r08_twb_extension_is_warning(clean_book, tmp_path):
    p = _mutate(clean_book, tmp_path, ("<workbook", "<workbook"), name="plain.twb")
    v = lint(p)
    assert "R08" in {x.rule for x in v if x.severity == "warn"}
    assert counts(v)[ERROR] == 0


def _lint_text(tmp_path, twb_text: str, name="sem.twb"):
    dst = str(tmp_path / name)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(twb_text)
    return lint(dst)


def test_r13_catches_simpson_paradox(clean_book, tmp_path):
    p = _mutate(clean_book, tmp_path,
                ("</datasource>",
                 "<column caption='Bad share' datatype='real' name='[Calculation_S1]' "
                 "role='measure' type='quantitative'>"
                 "<calculation class='tableau' formula='SUM([ngr]/[dep_sum])' />"
                 "</column>\n</datasource>"))
    v = lint(p)
    assert "R13" in _rules(v), "\n".join(str(x) for x in v)


def test_r13_allows_ratio_of_sums(clean_book, tmp_path):
    p = _mutate(clean_book, tmp_path,
                ("</datasource>",
                 "<column caption='Good share' datatype='real' name='[Calculation_S2]' "
                 "role='measure' type='quantitative'>"
                 "<calculation class='tableau' formula='SUM([ngr]) / SUM([dep_sum])' />"
                 "</column>\n</datasource>"))
    assert "R13" not in _rules(lint(p))


def test_r19_catches_dual_axis(clean_book, tmp_path):
    p = _mutate(clean_book, tmp_path, ("</worksheet>", "<axis-dual/></worksheet>"))
    assert "R19" in _rules(lint(p))


def test_r15_ignores_service_filters(clean_book, tmp_path):
    p = _mutate(clean_book, tmp_path,
                ("</worksheet>",
                 "<filter class='categorical' column='[ds].[Action (Period)]' /></worksheet>"))
    assert "R15" not in _rules(lint(p))


def test_r14_reports_dead_parameter(clean_book):
    v = lint(clean_book)
    assert "R14" in {x.rule for x in v if x.severity == "warn"}, \
        "\n".join(str(x) for x in v)


def test_r20_catches_ngr_with_costs_subtracted(clean_book, tmp_path):
    p = _mutate(clean_book, tmp_path,
                ("</datasource>",
                 "<column caption='NGR' datatype='real' name='[Calculation_C1]' "
                 "role='measure' type='quantitative'>"
                 "<calculation class='tableau' formula='SUM([ngr]) - SUM([rs_cost])' />"
                 "</column>\n</datasource>"))
    assert "R20" in _rules(lint(p))


def test_r20_allows_canonical_ngr(clean_book, tmp_path):
    p = _mutate(clean_book, tmp_path,
                ("</datasource>",
                 "<column caption='NGR' datatype='real' name='[Calculation_C2]' "
                 "role='measure' type='quantitative'>"
                 "<calculation class='tableau' formula='SUM([ngr])' />"
                 "</column>\n</datasource>"))
    assert "R20" not in _rules(lint(p))


TABLEAU_APP = "/Applications/Tableau Desktop (Apple silicon) 2026.1.app/Contents"
VENDOR = (glob.glob(os.path.join(TABLEAU_APP, "help", "Workbooks", "en_US", "*.twbx"))
          + glob.glob(os.path.join(TABLEAU_APP, "install", "Performance", "*.twb*")))


@pytest.mark.skipif(not VENDOR, reason="Tableau Desktop is not installed")
@pytest.mark.parametrize("path", sorted(VENDOR))
def test_vendor_books_have_no_errors(path):
    v = lint(path)
    assert counts(v)[ERROR] == 0, "\n".join(str(x) for x in v if x.severity == ERROR)


PUBLIC = glob.glob(os.path.join(INSPIRATION, "*.twbx"))


@pytest.mark.skipif(not PUBLIC, reason="Tableau Public corpus not available")
@pytest.mark.parametrize("path", sorted(PUBLIC))
def test_public_books_have_no_errors(path):
    v = lint(path)
    assert counts(v)[ERROR] == 0, "\n".join(str(x) for x in v if x.severity == ERROR)


def test_rule_codes_unique_across_modules():
    import os
    import re

    here = os.path.dirname(os.path.abspath(__file__))
    layer = os.path.join(os.path.dirname(here), "mcp", "twkit")
    owner = {}
    for f in sorted(os.listdir(layer)):
        if not f.endswith(".py"):
            continue
        src = open(os.path.join(layer, f), encoding="utf-8").read()
        for code in set(re.findall(r'"(R\d\d)"', src)):
            owner.setdefault(code, set()).add(f)
    clash = {c: sorted(m) for c, m in owner.items() if len(m) > 1}
    assert not clash


def test_parameter_caption_encoding_intact(tmp_path):
    import os
    import sys
    sys.path.insert(0, "mcp")
    from lxml import etree
    from twkit.book import Book
    from twkit import style as S
    import _matrix_book as M
    wb = Book()
    wb.set_csv_connection(M.write_csv(str(tmp_path / "s.csv")), fields=[dict(f) for f in M.FIELDS])
    wb.add_parameter("p_probe", datatype="integer", domain_type="list",
                     allowed_values=["1", "2"], default_value="1")
    wb.add_worksheet("probe")
    layout = {"type": "container", "direction": "horizontal",
              "children": [S.control_panel(["p_probe"], width=200),
                           {"type": "worksheet", "name": "probe", "weight": 4}]}
    wb.add_dashboard("probe dash", worksheet_names=["probe"], layout=layout)

    from twkit import safexml
    out = tmp_path / "probe.twbx"
    wb.save(str(out))
    raw = safexml.serialize(safexml.from_twbx(str(out))).decode("utf-8")
    assert "鍙傛暟" not in raw, "broken parameter caption came back"

    root = safexml.from_twbx(str(out))
    caps = {ds.get("caption") for ds in root.iter("datasource")
            if ds.get("name") == "Parameters" and ds.get("caption")}
    assert caps == {"Parameters"}


def test_capture_retries_and_requeries_id(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, "mcp")
    from twkit import shot

    ids = iter([111, 222, 333, 444])
    asked = []

    def fake_pick(book_hint="", owner="Tableau"):
        i = next(ids)
        asked.append(i)
        return {"owner": "Tableau", "name": "Tableau - X", "id": i,
                "x": 0, "y": 0, "w": 1200, "h": 900}

    calls = []

    class R:
        def __init__(self, rc):
            self.returncode, self.stdout, self.stderr = rc, "", (
                "" if rc == 0 else "could not create image from window")

    def fake_run(cmd, **kw):
        calls.append(cmd)
        rc = 0 if len(calls) >= 3 else 1
        if rc == 0:
            open(cmd[-1], "wb").write(b"\x89PNG\r\n\x1a\n" + b"\0" * 200)
        return R(rc)

    monkeypatch.setattr(shot, "pick_window", fake_pick)
    monkeypatch.setattr(shot, "park_mouse", lambda w: False)
    monkeypatch.setattr(shot.subprocess, "run", fake_run)
    monkeypatch.setattr(shot, "looks_rendered", lambda p: {"ok": True})
    monkeypatch.setattr(shot.time, "sleep", lambda *_: None)

    out = tmp_path / "shot.png"
    res = shot.capture(str(out))
    assert res["ok"]
    assert len(calls) == 3
    assert asked == [111, 222, 333]
    assert all(c[-2].startswith("-l") for c in calls), "captured not by window id"


def test_fullscreen_capture_forbidden():
    src = open("mcp/twkit/shot.py", encoding="utf-8").read()
    import re
    for m in re.finditer(r'\["screencapture"[^\]]*\]', src):
        assert "-l" in m.group(0)


def _lint_xml(xml: str, rule=None):
    from lxml import etree

    from twkit import safexml
    from twkit.lint import Book, r37_gradient_on_plain_measure

    root = safexml.from_bytes(etree.tostring(etree.fromstring(xml)))
    return r37_gradient_on_plain_measure(
        Book(path="<memory>", root=root, raw=xml.encode(), is_twbx=False))


def test_r37_gradient_on_non_delta_flagged():
    xml = """<workbook><worksheets><worksheet name='T'><table><style>
      <style-rule element='mark'>
        <encoding attr='color' field='[ds].[usr:NGR:qk]' type='interpolated' palette='Just black'/>
        <encoding attr='color' field='[ds].[usr:NGR Δ:qk]' type='interpolated'
                  palette='red_green_diverging_10_0' center='0.0' num-steps='2'/>
      </style-rule>
    </style></table></worksheet></worksheets></workbook>"""
    hits = [v for v in _lint_xml(xml) if v.rule == "R37"]
    assert len(hits) == 1, [v.message for v in hits]
    assert "NGR" in hits[0].message and "Δ" not in hits[0].message


def test_r37_silent_on_single_color_measure():
    xml = """<workbook><worksheets><worksheet name='T'><table><style>
      <style-rule element='mark'>
        <encoding attr='color' field='[ds].[usr:NGR:qk]' type='custom-interpolated' num-steps='2'>
          <color-palette custom='true' name='' type='ordered-diverging'>
            <color>#000000</color><color>#000000</color>
          </color-palette>
        </encoding>
        <encoding attr='color' field='[ds].[usr:NGR Δ:qk]' type='interpolated'
                  palette='red_green_diverging_10_0' center='0.0' num-steps='2'/>
      </style-rule>
    </style></table></worksheet></worksheets></workbook>"""
    assert [v for v in _lint_xml(xml) if v.rule == "R37"] == []


def test_r37_ignores_foreign_book_without_our_idiom():
    xml = """<workbook><worksheets><worksheet name='T'><table><style>
      <style-rule element='mark'>
        <encoding attr='color' field='[ds].[usr:P1:qk]' type='interpolated' palette='blue_10_0'/>
        <encoding attr='color' field='[ds].[usr:P2:qk]' type='interpolated' palette='blue_10_0'/>
      </style-rule>
    </style></table></worksheet></worksheets></workbook>"""
    assert [v for v in _lint_xml(xml) if v.rule == "R37"] == []


def test_r37_symmetric_stepped_range_is_mono_color():
    ramp = "".join(f"<color>{c}</color>" for c in
                   ("#333333", "#6a6a6a", "#a1a1a1", "#d9d9d9", "#a1a1a1", "#6a6a6a", "#333333"))
    xml = f"""<workbook><worksheets><worksheet name='T'><table><style>
      <style-rule element='mark'>
        <encoding attr='color' field='[ds].[usr:NGR:qk]' type='custom-interpolated'
                  num-steps='2' include-totals='true'>
          <color-palette custom='true' name='' type='ordered-diverging'>{ramp}</color-palette>
        </encoding>
        <encoding attr='color' field='[ds].[usr:NGR Δ:qk]' type='interpolated'
                  palette='red_green_diverging_10_0' num-steps='2' include-totals='true'/>
      </style-rule>
    </style></table></worksheet></worksheets></workbook>"""
    assert [v for v in _lint_xml(xml) if v.rule == "R37"] == []


def test_folder_canon_places_fields_and_lint_sees_it():
    from lxml import etree

    from twkit import safexml
    from twkit.edit import apply_folder_canon

    xml = """<workbook><datasources><datasource name='federated.x' caption='D'>
      <connection class='federated'/>
      <column name='[GEO]' datatype='string' role='dimension'/>
      <column name='[event_date]' datatype='date' role='dimension'/>
      <column name='[dep_sum]' datatype='real' role='measure'/>
      <column name='[_helper]' datatype='real' role='measure'>
        <calculation class='tableau' formula='1'/>
      </column>
      <column name='[NGR]' datatype='real' role='measure'>
        <calculation class='tableau' formula='SUM([dep_sum])'/>
      </column>
    </datasource></datasources></workbook>"""
    root = safexml.from_bytes(etree.tostring(etree.fromstring(xml)))
    got = apply_folder_canon(root)["D"]
    assert got == {"Fields": 1, "Date": 1, "Measures": 1, "Calcs": 1, "System": 1}, got
    common = root.find(".//folders-common")
    assert common is not None, "folders not in folders-common"
    calcs = [f for f in common.findall("folder") if f.get("name") == "Calcs"]
    assert calcs and calcs[0].find("folder-item").get("name") == "[NGR]"


def test_r07_ignores_tableau_temp_path(tmp_path):
    import zipfile

    from twkit import lint as L

    twb = ("<?xml version='1.0' encoding='utf-8' ?>\n\n<workbook>"
           "<datasources><datasource name='ds'><connection class='federated'>"
           "<named-connections><named-connection name='nc'>"
           "<connection class='hyper' dbname='/var/folders/x/T/tableau-temp/"
           "1234/Data/Book.hyper'/></named-connection></named-connections>"
           "</connection><extract><connection class='hyper' "
           "dbname='Data/Book.twb Files/Custom SQL Query.hyper'/></extract>"
           "</datasource></datasources>"
           "<worksheets/><dashboards/></workbook>")
    book = tmp_path / "Book.twbx"
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("Book.twb", twb)
        z.writestr("Data/Book.twb Files/Custom SQL Query.hyper", b"x")
    errors = [v for v in L.lint(str(book)) if v.rule == "R07" and v.severity == L.ERROR]
    assert not errors, [v.message for v in errors]


def test_r07_still_flags_unpacked_extract(tmp_path):
    import zipfile

    from twkit import lint as L

    twb = ("<?xml version='1.0' encoding='utf-8' ?>\n\n<workbook>"
           "<datasources><datasource name='ds'>"
           "<connection class='hyper' dbname='Data/Extracts/missing.hyper'/>"
           "<extract><connection class='hyper' "
           "dbname='Data/Extracts/missing.hyper'/></extract>"
           "</datasource></datasources><worksheets/><dashboards/></workbook>")
    book = tmp_path / "Book.twbx"
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("Book.twb", twb)
        z.writestr("Data/Extracts/other.hyper", b"x")
    bad = [v for v in L.lint(str(book)) if v.rule == "R07" and v.severity == L.ERROR]
    assert bad, "an unpacked extract must stay an error"


def test_r10_unbracketed_column_name_is_error(tmp_path):
    from twkit.lint import Book, ERROR, r10_xsd
    from twkit import safexml
    from lxml import etree
    xml = """<?xml version='1.0' encoding='utf-8' ?>
<workbook source-build='2026.1' version='18.1'><datasources>
  <datasource caption='T' name='federated.x'>
    <column caption='Roi' datatype='real' name='[roi]' role='measure' type='quantitative'/>
  </datasource></datasources>
<worksheets><worksheet name='A'><table><view>
  <datasources><datasource caption='T' name='federated.x'/></datasources>
  <datasource-dependencies datasource='federated.x'>
    <column datatype='string' name='dim_1' ordinal='2'/>
  </datasource-dependencies></view>
  <panes><pane><mark class='Text'/></pane></panes><rows/><cols/></table></worksheet></worksheets>
</workbook>"""
    root = safexml.from_bytes(etree.tostring(etree.fromstring(xml.encode())))
    v = r10_xsd(Book(path="<memory>", root=root, raw=xml.encode(), is_twbx=False))
    errs = [x for x in v if x.severity == ERROR]
    assert errs and "dim_1" in str(errs[0]), [str(x) for x in v]


def test_r32_sort_without_manifest_flag():
    from twkit.lint import Book, ERROR, r32_manifest_gate
    from twkit import safexml
    from lxml import etree
    def book(flag: str):
        xml = f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook><document-format-change-manifest>{flag}</document-format-change-manifest>
<worksheets><worksheet name='A'><table><view>
  <shelf-sorts><shelf-sort-v2 dimension-to-sort='[d].[none:x:nk]' direction='DESC'
     is-on-innermost-dimension='true' measure-to-sort-by='[d].[usr:v:qk]' shelf='rows'/></shelf-sorts>
</view></table></worksheet></worksheets></workbook>"""
        root = safexml.from_bytes(etree.tostring(etree.fromstring(xml.encode())))
        return Book(path="<memory>", root=root, raw=xml.encode(), is_twbx=False)
    bad = [v for v in r32_manifest_gate(book("")) if v.severity == ERROR]
    assert bad and "IntuitiveSorting" in str(bad[0]), bad
    assert not r32_manifest_gate(book("<IntuitiveSorting/>"))


def test_r40_color_map_with_source_prefix():
    from lxml import etree as ET
    from twkit import lint as L
    xml = b"""<workbook><datasources><datasource name='federated.x'><style><style-rule element='mark'>
      <encoding attr='color' field='[federated.x].[none:Calc:nk]' type='palette'><map to='#bab0ac'><bucket>"Out"</bucket></map></encoding>
    </style-rule></style></datasource></datasources></workbook>"""
    root = ET.fromstring(xml)
    assert L.r40_ds_style_encoding(L.Book("x.twb", xml, root, False))
    root.find(".//encoding").set("field", "[none:Calc:nk]")
    v = L.r40_ds_style_encoding(L.Book("x.twb", xml, root, False))
    assert [x.severity for x in v] == [L.WARN], v
    ds = root.find(".//datasource")
    ET.SubElement(ds, "column-instance", column="[Calc]", derivation="None",
                  name="[none:Calc:nk]", pivot="key", type="nominal")
    assert not L.r40_ds_style_encoding(L.Book("x.twb", xml, root, False))


def test_r42_two_fields_one_caption():
    from twkit.lint import Book, r42_caption_collision
    from twkit import safexml
    xml = ("<workbook><datasources><datasource name='ds' caption='Data'>"
           "<column name='[Calculation_1]' caption='Stag'><calculation formula='[dim_4]'/></column>"
           "<column name='[Calculation_2]' caption='Stag'><calculation formula='[dim_1]'/></column>"
           "<column name='[Calculation_3]' caption='Stag​'><calculation formula='[dim_2]'/></column>"
           "</datasource></datasources></workbook>")
    root = safexml.from_bytes(xml.encode())
    v = r42_caption_collision(Book(path="<memory>", root=root, raw=xml.encode(), is_twbx=False))
    assert len(v) == 1 and v[0].severity == ERROR and "'Stag'" in v[0].message


def test_r42_ignores_the_table_object_named_like_a_field():
    from twkit.lint import Book, r42_caption_collision
    from twkit import safexml
    xml = ("<workbook><datasources><datasource name='ds' caption='Data'>"
           "<column name='[__tableau_internal_object_id__].[Orders_1]' caption='Orders'/>"
           "<column name='[Calculation_1]' caption='Orders'><calculation formula='1'/></column>"
           "</datasource></datasources></workbook>")
    root = safexml.from_bytes(xml.encode())
    assert r42_caption_collision(Book(path="<memory>", root=root, raw=xml.encode(), is_twbx=False)) == []
