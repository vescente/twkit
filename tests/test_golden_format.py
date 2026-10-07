import glob
import io
import os
import zipfile

import pytest
from lxml import etree
from _userdata import CORPUS  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.isdir(CORPUS), reason="owner corpus not available")


def _roots():
    for f in sorted(glob.glob(os.path.join(CORPUS, "*.twbx"))):
        with zipfile.ZipFile(f) as z:
            inner = [n for n in z.namelist() if n.endswith(".twb")][0]
            yield os.path.basename(f), etree.parse(io.BytesIO(z.read(inner))).getroot()


@pytest.fixture(scope="session")
def golden() -> dict:
    out: dict[str, tuple[str, etree._Element]] = {}
    for book, root in _roots():
        for c in root.iter("column"):
            pdt = c.get("param-domain-type")
            if pdt:
                out.setdefault(f"param:{c.get('datatype')}:{pdt}", (book, c))
            elif (c.get("name") or "") == "[:Measure Names]":
                out.setdefault("measure-names", (book, c))
            elif c.find("calculation") is not None and c.get("datatype") == "boolean" \
                    and c.get("role") == "dimension":
                out.setdefault("calc:boolean", (book, c))
        for con in root.iter("connection"):
            if con.get("class") in ("hyper", "mysql"):
                out.setdefault(f"conn:{con.get('class')}", (book, con))
        for d in root.iter("dashboard"):
            s = d.find("size")
            if s is not None and s.get("sizing-mode") == "range":
                out.setdefault("size:range", (book, s))
    return out


@pytest.fixture(scope="session")
def ours():
    from twkit.book import Book

    from twkit import style as S
    from twkit.schema import apply_to_workbook, fetch_schema
    from twkit import config
    wb = Book()
    wb.set_mysql_connection(server=config.get("host"), dbname="reports", username=config.get("user"),
                            table_name="partner_daily", port=config.get("port"))
    apply_to_workbook(wb, fetch_schema("reports", "partner_daily"))

    S.date_range_params(wb, "2026-07-01", "2026-07-31")
    S.period_param(wb)
    wb.add_parameter("p_topn", datatype="integer", domain_type="range",
                     default_value="10", min_value="1", max_value="50")
    wb.add_calculated_field("_flag_period", "[event_date] >= [Parameters].[p_start_dt]",
                            datatype="boolean")
    S.apply_sizing(wb)
    wb.add_worksheet("s1")
    wb.configure_chart("s1", mark_type="Bar", columns=["event_date"], rows=["ngr"])
    wb.add_dashboard("d1", width=1600, height=1000, worksheet_names=["s1"])
    return wb


def _find(wb, pred):
    for c in wb.root.iter("column"):
        if pred(c):
            return c
    return None


def _params(wb, datatype, domain):
    return [c for c in wb.root.iter("column")
            if c.get("param-domain-type") == domain and c.get("datatype") == datatype]


CRITICAL_PARAM_ATTRS = ("datatype", "param-domain-type", "role", "type")


def test_param_date_matches_corpus(golden, ours):
    book, ref = golden["param:date:any"]
    got = _params(ours, "date", "any")
    assert got
    for c in got:
        for a in CRITICAL_PARAM_ATTRS:
            assert c.get(a) == ref.get(a)
        assert c.get("value", "").startswith("#") and c.get("value", "").endswith("#")
        calc = c.find("calculation")
        assert calc is not None and calc.get("formula", "").startswith("#")


def test_param_string_list_matches_corpus(golden, ours):
    book, ref = golden["param:string:list"]
    got = _params(ours, "string", "list")
    assert got
    for c in got:
        for a in CRITICAL_PARAM_ATTRS:
            assert c.get(a) == ref.get(a)
        assert c.get("value", "").startswith('"')
        assert c.find("members") is not None


def test_param_range_matches_corpus(golden, ours):
    key = "param:integer:range" if "param:integer:range" in golden else "param:real:range"
    book, ref = golden[key]
    got = _params(ours, "integer", "range")
    assert got
    c = got[0]
    assert c.get("role") == ref.get("role") and c.get("type") == ref.get("type")
    rng = c.find("range")
    assert rng is not None and rng.get("min") and rng.get("max")


def test_boolean_calc_is_dimension(golden, ours):
    book, ref = golden["calc:boolean"]
    assert ref.get("role") == "dimension" and ref.get("type") == "nominal"
    got = _find(ours, lambda c: c.find("calculation") is not None
                and c.get("datatype") == "boolean")
    assert got is not None
    assert got.get("role") == "dimension"
    assert got.get("type") == "nominal"


def test_mysql_connection_matches_corpus(golden, ours):
    book, ref = golden["conn:mysql"]
    got = [c for c in ours.root.iter("connection") if c.get("class") == "mysql"]
    assert got
    c = got[0]
    assert c.get("workgroup-auth-mode") == ref.get("workgroup-auth-mode") == "prompt"
    for a in ("server-oauth", "port", "username"):
        assert c.get(a) is not None


def test_sizing_range_matches_corpus(golden, ours):
    book, ref = golden["size:range"]
    sizes = [d.find("size") for d in ours.root.iter("dashboard")]
    sizes = [s for s in sizes if s is not None]
    assert sizes
    s = sizes[0]
    assert s.get("sizing-mode") == "range", f"sizing-mode={s.get('sizing-mode')}"
    for a in ("minwidth", "maxwidth", "minheight", "maxheight"):
        assert s.get(a)


def test_header_matches_corpus(ours, tmp_path):
    out = str(tmp_path / "golden.twbx")
    ours.save(out)
    with zipfile.ZipFile(out) as z:
        inner = [n for n in z.namelist() if n.endswith(".twb")][0]
        head = z.read(inner)[:300].decode("utf-8")
    assert head.startswith("<?xml version='1.0' encoding='utf-8'"), repr(head[:60])
    assert "\n<workbook" in head
    assert "@" not in head.split("<workbook")[0]


def test_measure_names_declaration_matches_corpus(golden):
    if "measure-names" not in golden:
        pytest.skip("the corpus has no explicit [:Measure Names] declaration")
    book, ref = golden["measure-names"]
    assert ref.get("datatype") == "string", book
    assert ref.get("role") == "dimension", book
    assert ref.get("type") == "nominal", book
