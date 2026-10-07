import json
import os
import tempfile
import zipfile

import pytest

from twkit import dryrun, shot, tablog
from _userdata import FIXTURES  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _png(path, color=(255, 255, 255), filled=0.0):
    from PIL import Image
    im = Image.new("RGB", (400, 300), color)
    if filled:
        px = im.load()
        rows = int(300 * filled)
        for y in range(rows):
            for x in range(400):
                px[x, y] = ((x * 3) % 255, (y * 5) % 255, (x + y) % 255)
    im.save(path)
    return path


def test_blank_canvas_not_render(tmp_path):
    p = _png(str(tmp_path / "blank.png"))
    v = shot.looks_rendered(p)
    assert v["ok"] is False
    assert "almost one color" in v["why"]


def test_colorful_image_is_render(tmp_path):
    p = _png(str(tmp_path / "real.png"), filled=0.3)
    assert shot.looks_rendered(p)["ok"] is True


def test_missing_file_does_not_crash():
    v = shot.looks_rendered("/nope/nothing.png")
    assert v["ok"] is False


def test_capture_without_window_returns_reason(monkeypatch, tmp_path):
    monkeypatch.setattr(shot, "pick_window", lambda *a, **k: None)
    v = shot.capture(str(tmp_path / "x.png"))
    assert v["ok"] is False and "not found" in v["why"]


def test_foreign_session_untouched(monkeypatch):
    monkeypatch.setattr(shot, "dismiss_dialog", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(shot, "window_of", lambda *a, **k: {"id": 1, "w": 800, "h": 600})
    assert shot.open_book("any.twbx")["action"] == "the workbook is already open; left as is"


def test_window_chosen_by_book_name(monkeypatch):
    wins = [{"id": 1, "name": "Tableau - Other", "w": 1920, "h": 1050},
            {"id": 2, "name": "Tableau - Self Service", "w": 800, "h": 600}]
    monkeypatch.setattr(shot, "list_windows", lambda owner="Tableau": wins)
    assert shot.pick_window("/path/Self Service.twbx")["id"] == 2
    assert shot.pick_window("")["id"] == 1


def test_service_noise_not_a_problem(tmp_path, monkeypatch):
    log = tmp_path / "log.txt"
    log.write_text("\n".join([
        json.dumps({"sev": "error", "k": "endeavour-edpa", "v": {"msg": "entitlement"}}),
        json.dumps({"sev": "error", "k": "msg", "v": {"excp-msg": "Field not found: [x]"}}),
        json.dumps({"sev": "info", "k": "msg", "v": "opened the book"}),
    ]), encoding="utf-8")
    monkeypatch.setattr(tablog, "LOG", str(log))
    p = tablog.problems()
    assert p["error_count"] == 1
    assert "Field not found" in p["errors"][0]["msg"]


def test_no_log_no_false_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(tablog, "LOG", str(tmp_path / "missing.txt"))
    assert tablog.problems()["verdict"] == "no log records - the workbook was not opened"


def test_broken_lines_do_not_break_parsing(tmp_path, monkeypatch):
    log = tmp_path / "log.txt"
    log.write_text("not json\n{truncated\n" +
                   json.dumps({"sev": "warn", "k": "msg", "v": {"msg": "ouch"}}),
                   encoding="utf-8")
    monkeypatch.setattr(tablog, "LOG", str(log))
    assert tablog.problems()["warning_count"] == 1


BOOKS = [p for p in
         [os.path.join(FIXTURES, "Self Service.twbx")]
         if os.path.exists(p)]


def test_shown_differs_from_declared():
    import xml.etree.ElementTree as ET
    from twkit.dryrun import _user_visible_fields
    root = ET.fromstring(
        '<workbook><worksheets><worksheet name="s"><table>'
        '<rows>[ds].[none:on_shelf:nk]</rows></table></worksheet></worksheets>'
        '<dashboards><dashboard name="d"><zones>'
        '<zone type-v2="filter" param="[ds].[none:in_filter:nk]"/>'
        '<zone type-v2="worksheet" name="s"/></zones></dashboard></dashboards>'
        '<datasources><datasource><column name="[R]" param-domain-type="list">'
        '<members><member value="&quot;in_switcher&quot;"/></members>'
        '</column></datasource></datasources></workbook>')
    shown = _user_visible_fields(root)
    assert {"in_filter", "on_shelf", "in_switcher"} <= shown
    assert "just_declared" not in shown


@pytest.mark.skipif(not BOOKS, reason="no built book with an extract")
def test_dimension_and_metric_verdicts_not_mixed():
    pytest.importorskip("tableauhyperapi")
    r = dryrun.dead_dimensions(BOOKS[0])
    assert all(d["role"] != "measure" for d in r["dead"] + r["degenerate"])


@pytest.mark.skipif(not BOOKS, reason="no built book with an extract")
def test_only_referenced_fields_checked():
    pytest.importorskip("tableauhyperapi")
    with zipfile.ZipFile(BOOKS[0]) as z:
        twb = [n for n in z.namelist() if n.endswith(".twb")][0]
        xml = z.read(twb).decode("utf-8", "replace")
    r = dryrun.dead_dimensions(BOOKS[0])
    for item in r["dead"] + r["degenerate"] + r["constant_metrics"]:
        assert f"[{item['field']}]" in xml


def test_unavailable_source_not_reported_as_checked(tmp_path):
    twb = tmp_path / "empty.twb"
    twb.write_text("<workbook><datasources/><worksheets/></workbook>", encoding="utf-8")
    r = dryrun.dead_dimensions(str(twb))
    assert "not checked" in r["verdict"]


def test_book_with_comments_does_not_break_check(tmp_path):
    twb = tmp_path / "with_comment.twb"
    twb.write_text("<?xml version='1.0' encoding='utf-8' ?>\n\n"
                   "<!-- build 2026.1 -->\n"
                   "<workbook><!-- service comment -->"
                   "<datasources/><worksheets/></workbook>", encoding="utf-8")
    r = dryrun.dead_dimensions(str(twb))
    assert "TypeError" not in r["verdict"]
    assert "not checked" in r["verdict"]


def test_connector_plugin_at_startup_not_book_error(tmp_path, monkeypatch):
    log = tmp_path / "log.txt"
    log.write_text("\n".join([
        json.dumps({"sev": "error", "k": "connector-plugin-error",
                    "v": "Some connector plugins failed to load:"}),
        json.dumps({"sev": "error", "k": "connector-plugin-error",
                    "v": "/Applications/Tableau/connectors/libsalesforce-uip.dylib failed to load"}),
        json.dumps({"sev": "info", "k": "msg", "v": "opened the book"}),
    ]), encoding="utf-8")
    monkeypatch.setattr(tablog, "LOG", str(log))
    p = tablog.problems()
    assert p["error_count"] == 0 and p["verdict"] == "Tableau opened it without errors"


def test_error_window_text_from_log(tmp_path, monkeypatch):
    args = ('tabdoc:show-detailed-error-dialog error-code-id="0" error-details=["*****"] '
            'error-dialog-title="" error-help-link="" error-short-message="Warnings occurred '
            'while loading the workbook \\"/x/Book A.twbx\\"." issue-helper-links="" '
            'query-details="" use-copy-command="true"')
    log = tmp_path / "log.txt"
    log.write_text("\n".join([
        json.dumps({"sev": "info", "k": "begin-commands-controller.invoke-command",
                    "v": {"name": "tabdoc:show-detailed-error-dialog", "args": args},
                    "ctx": {"wb": "Book A"}}),
    ]), encoding="utf-8")
    monkeypatch.setattr(tablog, "LOG", str(log))
    d = tablog.error_dialogs()
    assert d and d[0]["warning"] and "Book A.twbx" in d[0]["text"]
    p = tablog.problems("/x/Book A.twbx")
    assert p["verdict"].startswith("Tableau showed a warnings dialog")
