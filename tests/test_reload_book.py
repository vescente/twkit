import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from twkit import shot as SHOT


def test_empty_book_not_document():
    assert SHOT._is_doc("Tableau - P&L 2026") is True
    assert SHOT._is_doc("Tableau - Book1") is False
    assert SHOT._is_doc("Tableau - Book12") is False
    assert SHOT._is_doc("Tableau") is False
    assert SHOT._is_doc("Finder - Book1") is False


def test_book_named_like_template_stays_document():
    assert SHOT._is_doc("Tableau - Bookmakers") is True
    assert SHOT._is_doc("Tableau - Book of Reports") is True


def test_close_documents_does_not_spin_on_empty_book(monkeypatch):
    seq = [["Tableau - Report"], ["Tableau - Book1"], ["Tableau - Book1"]]
    calls = {"n": 0, "osa": 0}

    def fake_list(owner="Tableau"):
        i = min(calls["n"], len(seq) - 1)
        return [{"name": x} for x in seq[i]]

    class R:
        returncode = 0

    def fake_osa(script, timeout=25.0):
        calls["osa"] += 1
        calls["n"] += 1
        return R()

    monkeypatch.setattr(SHOT, "list_windows", fake_list)
    monkeypatch.setattr(SHOT, "_osa", fake_osa)
    monkeypatch.setattr(SHOT, "dismiss_dialog", lambda tries=3: {})
    monkeypatch.setattr(SHOT.time, "sleep", lambda *_: None)
    assert SHOT.close_documents() == 1
    assert calls["osa"] == 1


def test_window_addressed_with_applescript_quotes(monkeypatch):
    seen = {}

    class R:
        returncode = 0

    def fake_osa(script, timeout=25.0):
        seen["script"] = script
        return R()

    monkeypatch.setattr(SHOT, "_osa", fake_osa)
    monkeypatch.setattr(SHOT, "dismiss_dialog", lambda tries=3: {})
    monkeypatch.setattr(SHOT, "window_alive", lambda title: False)
    monkeypatch.setattr(SHOT.time, "sleep", lambda *_: None)
    assert SHOT._close_window('Tableau - P&L "2026"') is True
    assert 'whose name is "Tableau - P&L \\"2026\\""' in seen["script"]
    assert "'" not in seen["script"].split("whose name is")[1].split("\n")[0]


def test_reload_does_not_quit_app(monkeypatch):
    called = {"quit": 0, "close": 0, "open": 0}
    monkeypatch.setattr(SHOT, "close_tableau",
                        lambda wait=25.0: called.__setitem__("quit", 1))
    monkeypatch.setattr(SHOT, "window_of", lambda b, owner="Tableau": None)
    monkeypatch.setattr(SHOT, "close_blank_books", lambda: 0)
    monkeypatch.setattr(SHOT, "open_book",
                        lambda b, wait=25.0, reopen=False: (
                            called.__setitem__("open", 1) or {"ok": True, "action": "opened"}))
    res = SHOT.reload_book("/here/book.twbx")
    assert res["ok"] is True
    assert called["quit"] == 0
    assert called["open"] == 1


def test_active_can_be_a_sheet_not_only_a_page():
    from lxml import etree

    root = etree.fromstring("""<workbook><windows>
      <window class='dashboard' name='Page' maximized='true' />
      <window class='worksheet' name='Sheet' />
      <window class='worksheet' name='Other' />
    </windows></workbook>""".encode("utf-8"))
    assert SHOT.set_active_page(root, "Sheet") is True
    got = {w.get("name"): w.get("maximized") for w in root.iter("window")}
    assert got == {"Page": None, "Sheet": "true", "Other": None}


def test_missing_tab_reported():
    from lxml import etree

    root = etree.fromstring("<workbook><windows>"
                            "<window class='worksheet' name='Sheet' />"
                            "</windows></workbook>".encode("utf-8"))
    assert SHOT.set_active_page(root, "No such") is False


def test_quit_closes_documents_then_app(monkeypatch):
    order = []
    monkeypatch.setattr(SHOT, "dismiss_dialog", lambda tries=3: {})
    monkeypatch.setattr(SHOT, "list_windows", lambda owner="Tableau": [{"name": "Tableau - K"}])
    monkeypatch.setattr(SHOT, "close_documents",
                        lambda tries=8: (order.append("documents"), 1)[1])
    monkeypatch.setattr(SHOT, "_gone", lambda wait: order[-1] == "documents")
    res = SHOT.close_tableau()
    assert order == ["documents"]
    assert res["ok"] and "documents" in res["action"]


def test_signal_is_last_resort(monkeypatch):
    calls = []
    monkeypatch.setattr(SHOT, "dismiss_dialog", lambda tries=3: {})
    monkeypatch.setattr(SHOT, "list_windows", lambda owner="Tableau": [{"name": "Tableau - K"}])
    monkeypatch.setattr(SHOT, "close_documents", lambda tries=8: 0)
    monkeypatch.setattr(SHOT, "_gone", lambda wait: "pkill" in calls)
    monkeypatch.setattr(SHOT.subprocess, "run",
                        lambda *a, **k: (calls.append("pkill" if "pkill" in a[0] else "osa"), None)[1])
    res = SHOT.close_tableau()
    assert calls.count("osa") >= 1 and "pkill" in calls
    assert "abnormal" in res["action"]


def test_fallback_when_accessibility_silent(monkeypatch):
    state = {"remaining": ["Tableau - target"], "keys": 0}

    class Bad:
        returncode = 1

    class Ok:
        returncode = 0

    def fake_osa(script, timeout=25.0):
        if "click button 1" in script:
            return Bad()
        state["keys"] += 1
        state["remaining"] = []
        return Ok()

    monkeypatch.setattr(SHOT, "_osa", fake_osa)
    monkeypatch.setattr(SHOT, "list_windows",
                        lambda owner="Tableau": [{"name": n} for n in state["remaining"]])
    monkeypatch.setattr(SHOT, "_ax_all_windows", lambda: list(state["remaining"]))
    monkeypatch.setattr(SHOT, "dismiss_dialog", lambda tries=3: {})
    monkeypatch.setattr(SHOT.time, "sleep", lambda *_: None)
    assert SHOT._close_window("Tableau - target") is True
    assert state["keys"] == 1


def test_fallback_reports_remaining_window(monkeypatch):
    class Bad:
        returncode = 1

    monkeypatch.setattr(SHOT, "_osa", lambda script, timeout=25.0: Bad())
    monkeypatch.setattr(SHOT, "list_windows",
                        lambda owner="Tableau": [{"name": "Tableau - target"}])
    monkeypatch.setattr(SHOT, "_ax_all_windows", lambda: ["Tableau - target"])
    monkeypatch.setattr(SHOT, "dismiss_dialog", lambda tries=3: {})
    monkeypatch.setattr(SHOT.time, "sleep", lambda *_: None)
    assert SHOT._close_window("Tableau - target") is False


def test_window_liveness_by_accessibility(monkeypatch):
    monkeypatch.setattr(SHOT, "list_windows",
                        lambda owner="Tableau": [{"name": "Tableau - ghost"},
                                                 {"name": "Tableau - Book3"}])
    monkeypatch.setattr(SHOT, "_ax_all_windows", lambda: ["Tableau - Book3"])
    assert SHOT.window_alive("Tableau - ghost") is False
    assert SHOT.window_alive("Tableau - Book3") is True


def test_coregraphics_trusted_when_accessibility_silent(monkeypatch):
    monkeypatch.setattr(SHOT, "list_windows",
                        lambda owner="Tableau": [{"name": "Tableau - book"}])
    monkeypatch.setattr(SHOT, "_ax_all_windows", lambda: [])
    assert SHOT.window_alive("Tableau - book") is True


def test_working_copies_closed_others_kept(monkeypatch, tmp_path):
    import os

    work = tmp_path / "twkit_shots"
    work.mkdir()
    (work / "report.twbx").write_text("x")
    (work / "probe.twbx").write_text("x")
    monkeypatch.setattr(SHOT.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(SHOT, "list_windows", lambda owner="Tableau": [
        {"name": "Tableau - report"},
        {"name": "Tableau - probe"},
        {"name": "Tableau - P&L 2026"},
    ])
    closed = []
    monkeypatch.setattr(SHOT, "_close_window_strict",
                        lambda t: (closed.append(t), True)[1])
    assert SHOT.close_work_copies() == 2
    assert closed == ["Tableau - report", "Tableau - probe"]
    assert "Tableau - P&L 2026" not in closed


def test_current_frame_not_closed(monkeypatch, tmp_path):
    work = tmp_path / "twkit_states"
    work.mkdir()
    (work / "book — Plan.twbx").write_text("x")
    (work / "book — Actual.twbx").write_text("x")
    monkeypatch.setattr(SHOT.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(SHOT, "list_windows", lambda owner="Tableau": [
        {"name": "Tableau - book — Plan"},
        {"name": "Tableau - book — Actual"},
    ])
    assert SHOT.work_copies_open(keep="/tmp/twkit_states/book — Actual.twbx") == [
        "Tableau - book — Plan"]


def test_copy_cleanup_spares_front_document(monkeypatch, tmp_path):
    work = tmp_path / "twkit_shots"
    work.mkdir()
    (work / "copy.twbx").write_text("x")
    monkeypatch.setattr(SHOT.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(SHOT, "list_windows",
                        lambda owner="Tableau": [{"name": "Tableau - copy"}])
    monkeypatch.setattr(SHOT, "_ax_all_windows", lambda: [])
    keys = []
    monkeypatch.setattr(SHOT, "_osa",
                        lambda script, timeout=25.0: keys.append(script))
    assert SHOT.close_work_copies() == 0
    assert keys == []


def test_orphan_lock_not_an_open_book(monkeypatch, tmp_path):
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))
    from twkit import owner as OW

    book = tmp_path / "Report.twbx"
    book.write_text("x")
    (tmp_path / ".~Report__999.twbr").write_text("lock")

    class R:
        stdout = ""

    monkeypatch.setattr(OW.__dict__.get("subprocess", __import__("subprocess")),
                        "run", lambda *a, **k: R())
    assert OW.opened_in_tableau(str(book)) == ""
    assert len(OW.stale_locks(str(book))) == 1


def test_live_lock_still_blocks(monkeypatch, tmp_path):
    import subprocess as SP_
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))
    from twkit import owner as OW

    book = tmp_path / "Report.twbx"
    book.write_text("x")
    (tmp_path / ".~Report__999.twbr").write_text("lock")

    class R:
        stdout = "COMMAND PID ...\nTableau 123 ..."

    monkeypatch.setattr(SP_, "run", lambda *a, **k: R())
    assert OW.opened_in_tableau(str(book)).endswith(".twbr")
    assert OW.stale_locks(str(book)) == []
