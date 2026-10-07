import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from twkit import shot as SHOT


def test_book_window_found_by_name_without_fallback():
    wins = [{"name": "Tableau", "w": 1800, "h": 1000, "x": 0, "y": 0, "id": 1,
             "owner": "Tableau"}]
    SHOT.list_windows = lambda owner="Tableau": wins
    assert SHOT.window_of("/tmp/PnL 2026.twbx") is None
    assert SHOT.pick_window("/tmp/PnL 2026.twbx") is wins[0]

    wins.append({"name": "Tableau - PnL 2026", "w": 900, "h": 600, "x": 0, "y": 0,
                 "id": 2, "owner": "Tableau"})
    assert SHOT.window_of("/tmp/PnL 2026.twbx")["id"] == 2


def test_error_window_seen_without_dialog_subrole(monkeypatch):
    monkeypatch.setattr(SHOT, "all_windows", lambda owner="Tableau": [
        {"name": "Unable to complete action", "w": 502, "h": 241, "x": 0, "y": 0,
         "id": 3, "owner": "Tableau"},
        {"name": "Tableau - PnL 2026", "w": 900, "h": 600, "x": 0, "y": 0,
         "id": 4, "owner": "Tableau"},
        {"name": "Tableau", "w": 900, "h": 600, "x": 0, "y": 0, "id": 5,
         "owner": "Tableau"},
    ])
    assert SHOT._cg_dialog_titles() == ["Unable to complete action"]


def test_dialog_text_not_replaced_by_clipboard(monkeypatch):
    monkeypatch.setattr(SHOT, "list_dialogs", lambda: ["Unable to complete action"])
    monkeypatch.setattr(SHOT, "_osa", lambda *a, **k: type("R", (), {"returncode": 0})())

    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw.get("input")))
        if cmd == ["pbpaste"]:
            return type("R", (), {"stdout": "owner note\nsecond line"})()
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr(SHOT.subprocess, "run", fake_run)
    assert SHOT.read_dialog() == []
    assert (["pbcopy"], "owner note\nsecond line") in calls


def test_dialog_text_read_when_title_matches(monkeypatch):
    monkeypatch.setattr(SHOT, "list_dialogs", lambda: ["Unable to complete action"])
    monkeypatch.setattr(SHOT, "_osa", lambda *a, **k: type("R", (), {"returncode": 0})())
    monkeypatch.setattr(SHOT.subprocess, "run", lambda cmd, **kw: type("R", (), {
        "stdout": "Unable to complete action\nError(398,145): no declaration found"
    })())
    assert SHOT.read_dialog()[1].startswith("Error(398,145)")


def test_hotkeys_sent_as_codes_not_characters():
    src = open(os.path.join(os.path.dirname(SHOT.__file__), "shot.py"),
               encoding="utf-8").read()
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    for combo in ('keystroke "v"', 'keystroke "c"', 'keystroke "a"',
                  'keystroke "w"', 'keystroke "d"'):
        assert combo not in code, combo
    assert re.search(r"key code \d+ using command down", code)


def test_password_not_via_clipboard():
    src = open(os.path.join(os.path.dirname(SHOT.__file__), "shot.py"),
               encoding="utf-8").read()
    assert "keyboardSetUnicodeString" in src
    assert "readLine(strippingNewline: true)" in src
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert "key code 9" not in code


def test_password_not_printed(monkeypatch):
    monkeypatch.setattr(SHOT, "signin_window", lambda: None)
    monkeypatch.setattr(SHOT, "edit_connection", lambda hint="": {"ok": False,
                                                                  "action": "no"})
    monkeypatch.setattr(SHOT, "ch_mysql_password", lambda: "s3cr3t#^@")
    res = SHOT.ensure_signed_in()
    assert "s3cr3t#^@" not in str(res)


def test_sign_in_without_password_says_so(monkeypatch):
    monkeypatch.setattr(SHOT, "ch_mysql_password", lambda: "")
    res = SHOT.ensure_signed_in()
    assert res["ok"] is False
    assert "manually" in res["action"]
