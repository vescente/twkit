import os
import shutil
import subprocess
import sys
import zipfile
from html.parser import HTMLParser

import pytest
from lxml import etree

from twkit import chsafe, safexml, shot
from twkit import frame as F

sys.path.insert(0, os.path.dirname(__file__))
import _matrix_book  # noqa: E402

SHORT = "#'><u>x"
LONG = "Tableau'\"><u>pwn</u>"


@pytest.mark.parametrize("sql", [
    "SELECT * FROM numbers(1) /* /* */ ' */ , url('http://x', CSV, 'a String') --'",
    "SELECT * FROM numbers(1) -- x\r'\n, url('http://x', CSV, 'a String') --'",
])
def test_comments_that_dialects_end_differently_are_refused(sql):
    with pytest.raises(PermissionError):
        chsafe.read_only(sql)


def test_plain_comments_still_pass():
    assert chsafe.read_only("SELECT 1 /* note */ -- tail\r\n")
    assert chsafe.read_only("SELECT 1 -- tail")


@pytest.mark.skipif(not shutil.which("osascript"), reason="no AppleScript")
def test_applescript_literal_round_trips_a_hostile_title():
    title = 'Book" & (do shell script "echo pwn") & "\\'
    r = subprocess.run(["osascript", "-e", "return " + shot._lit(title)],
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and r.stdout.rstrip("\n") == title


def test_dialog_title_reaches_applescript_as_a_literal(monkeypatch):
    title = 'Error in "x" & (do shell script "echo pwn") & ""'
    seen = []
    monkeypatch.setattr(shot, "list_dialogs", lambda: [title])
    monkeypatch.setattr(shot, "_osa", lambda script, timeout=25.0: seen.append(script))
    monkeypatch.setattr(shot.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="", stderr=""))
    shot.read_dialog()
    shot._press_default(title)
    assert len(seen) == 2 and all(shot._lit(title) in s for s in seen)


def test_cached_helper_writable_by_others_is_not_run(tmp_path):
    exe = tmp_path / "helper"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    assert shot._trusted(str(exe))
    exe.chmod(0o775)
    assert not shot._trusted(str(exe))


def test_workbook_colours_and_fonts_are_checked_before_css():
    assert F._hex("#4E79A7ff") == "#4E79A7" and F._hex(SHORT) is None
    assert F._font(LONG) == "Tableauupwnu"
    btn = etree.fromstring("<button><button-visual-state><caption>Go</caption>"
                           "<button-caption-font-style/></button-visual-state>"
                           "<format attr='background-color'/></button>")
    btn.find(".//button-caption-font-style").attrib.update({"fontcolor": SHORT, "fontname": LONG})
    btn.find("format").set("value", SHORT)
    assert "<u>" not in F._button_html(btn, {})


def _poison(root) -> int:
    n = 0
    for ws in root.iter("worksheet"):
        table = ws.find("table")
        style = table.find("style")
        if style is None:
            style = etree.SubElement(table, "style")
        for element, attr, value in (("mark", "mark-color", SHORT), ("cell", "color", SHORT),
                                     ("cell", "font-family", LONG), ("table", "background-color", SHORT)):
            rule = etree.SubElement(style, "style-rule", element=element)
            etree.SubElement(rule, "format", attr=attr, value=value)
    for e in root.iter():
        for a, v in (("fontcolor", SHORT), ("fontname", LONG), ("to", SHORT)):
            if e.get(a) is not None:
                e.set(a, v)
                n += 1
        if e.tag == "format" and e.get("attr") in ("color", "mark-color", "background-color",
                                                    "border-color", "font-family"):
            e.set("value", LONG if e.get("attr") == "font-family" else SHORT)
            n += 1
        if e.tag == "color" and (e.text or "").startswith("#"):
            e.text = SHORT
            n += 1
    return n


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_hostile_workbook_strings_never_become_page_markup(tmp_path):
    src = _matrix_book.build(str(tmp_path))
    root = safexml.from_twbx(src)
    assert _poison(root) > 10
    bad = str(tmp_path / "hostile.twbx")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = safexml.serialize(root) if info.filename.endswith(".twb") else zin.read(info)
            zout.writestr(info.filename, data)
    out = F.publish(bad, out_dir=str(tmp_path / "frame"))
    assert out["pages"]
    for pg in out["pages"]:
        p = _Tags()
        p.feed(open(pg["file"], encoding="utf-8").read())
        names = [t for t, _ in p.tags]
        assert "u" not in names, f"workbook text became markup on {pg['page']}"
        assert names.count("script") == 1
        assert any(a.get("http-equiv") == "Content-Security-Policy" for t, a in p.tags if t == "meta")


@pytest.mark.parametrize("sql", [
    "SELECT * FROM view(SELECT * FROM someNewFn('h'))",
    "SELECT * FROM (someNewFn('h'))",
    "SELECT * FROM numbers(1) WHERE ‘'’ = '' , url('http://x', CSV, 'a String') --'",
    "SELECT “x” FROM t",
    "SELECT * FROM viewIfPermitted(SELECT 1 ELSE null('a Int8'))",
    "SELECT * FROM t WHERE x IN someNewFn('h')",
])
def test_table_functions_hidden_from_the_guard_are_refused(sql):
    with pytest.raises(PermissionError):
        chsafe.read_only(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM t WHERE d IN (toDate('2026-01-01'), toDate('2026-02-01'))",
    "SELECT * FROM view(SELECT number FROM numbers(3))",
    "SELECT * FROM t JOIN u ON (t.a = lower(u.b))",
    "SELECT 'Zürich' AS r, count() FROM t -- naïve note\n",
    "SELECT * FROM (SELECT 1) AS a, (SELECT 2) AS b",
])
def test_ordinary_reads_still_pass(sql):
    assert chsafe.read_only(sql) == sql


def test_a_keyword_before_a_bracket_is_never_a_table_function():
    assert chsafe._table_functions("SELECT * FROM a, b, FROM (SELECT 1)") == []
