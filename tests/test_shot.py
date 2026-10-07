def test_foreign_window_not_taken():
    from twkit import shot as SH

    problem = SH.wrong_window("Tableau - Game report", "/tmp/twkit_shoot_Old Users.twbx")
    assert "WRONG" in problem and "Game report" in problem and "Old Users" in problem

    assert SH.wrong_window("Tableau - twkit_shoot_Old Users", "/tmp/twkit_shoot_Old Users.twbx") == ""
    assert SH.wrong_window("", "/tmp/twkit_shoot_Old Users.twbx") == ""
    assert SH.wrong_window("Tableau - anything", "") == ""


def test_working_copy_named_differently():
    from twkit import shot as SH
    assert SH.WORK_PREFIX
    assert SH.WORK_PREFIX not in "Cohort Segmentation"


def test_lock_blocks_second_session(tmp_path, monkeypatch):
    from twkit import shot as SH
    monkeypatch.setattr(SH, "LOCK_PATH", str(tmp_path / "lock.json"))
    assert SH.acquire_window("book.twbx")["ok"]
    import json
    held = json.load(open(SH.LOCK_PATH, encoding="utf-8"))
    held["pid"] = 1
    json.dump(held, open(SH.LOCK_PATH, "w", encoding="utf-8"))
    refusal = SH.acquire_window("other.twbx")
    assert not refusal["ok"]
    assert "held by another session" in refusal["why"]


def test_abandoned_lock_does_not_hold_window_forever(tmp_path, monkeypatch):
    import json

    from twkit import shot as SH
    monkeypatch.setattr(SH, "LOCK_PATH", str(tmp_path / "lock.json"))
    json.dump({"pid": 999999, "time": __import__("time").time(), "book": "x"},
              open(SH.LOCK_PATH, "w", encoding="utf-8"))
    assert SH.acquire_window("book.twbx")["ok"]


def test_stale_lock_released(tmp_path, monkeypatch):
    import json
    import time as T

    from twkit import shot as SH
    monkeypatch.setattr(SH, "LOCK_PATH", str(tmp_path / "lock.json"))
    json.dump({"pid": 1, "time": T.time() - SH.LOCK_STALE - 1, "book": "x"},
              open(SH.LOCK_PATH, "w", encoding="utf-8"))
    assert SH.acquire_window("book.twbx")["ok"]


def test_own_lock_released_foreign_kept(tmp_path, monkeypatch):
    import json
    import os as O

    from twkit import shot as SH
    monkeypatch.setattr(SH, "LOCK_PATH", str(tmp_path / "lock.json"))
    json.dump({"pid": 1, "time": __import__("time").time(), "book": "foreign"},
              open(SH.LOCK_PATH, "w", encoding="utf-8"))
    SH.release_window()
    assert O.path.exists(SH.LOCK_PATH)


def test_locked_screen_not_reported_as_permission_denial(tmp_path, monkeypatch):
    from twkit import shot

    class R:
        returncode = 1
        stderr = "could not create image from window"
        stdout = ""

    monkeypatch.setattr(shot, "pick_window", lambda *a, **k: {"id": 7, "owner": "Tableau", "name": "Tableau - x", "w": 10, "h": 10})
    monkeypatch.setattr(shot.subprocess, "run", lambda *a, **k: R())
    monkeypatch.setattr(shot.time, "sleep", lambda *_: None)
    monkeypatch.setattr(shot, "screen_locked", lambda: True)
    v = shot.capture(str(tmp_path / "a.png"), "x")
    assert v["screen"] == "locked" and "not a Screen Recording issue" in v["why"]
    monkeypatch.setattr(shot, "screen_locked", lambda: False)
    v = shot.capture(str(tmp_path / "a.png"), "x")
    assert "re-confirm" in v["why"]


def test_lock_flag_read_from_ioreg(monkeypatch):
    from twkit import shot

    class R:
        stdout = "<dict><key>CGSSessionScreenIsLocked</key>\n\t\t\t<true/></dict>"

    monkeypatch.setattr(shot.subprocess, "run", lambda *a, **k: R())
    assert shot.screen_locked() is True
    R.stdout = "<dict><key>kCGSSessionOnConsoleKey</key><true/></dict>"
    assert shot.screen_locked() is False


def test_cursor_parked_before_capture(tmp_path, monkeypatch):
    from twkit import shot as SH
    calls = []
    win = {"id": 7, "owner": SH.TABLEAU_OWNER, "x": 0, "y": 0, "w": 800, "h": 600}
    monkeypatch.setattr(SH, "pick_window", lambda hint="": win)
    monkeypatch.setattr(SH, "park_mouse", lambda w: calls.append("park") or True)

    class R:
        returncode, stderr = 1, "stop"

    def fake_run(cmd, **kw):
        if cmd and cmd[0] == "screencapture":
            calls.append("shot")
        return R()
    monkeypatch.setattr(SH.subprocess, "run", fake_run)
    monkeypatch.setattr(SH.time, "sleep", lambda s: None)
    SH.capture(str(tmp_path / "x.png"))
    assert calls and calls[0] == "park" and "shot" in calls


def test_book_fingerprint_stable_across_rebuilds(tmp_path):
    import zipfile
    from twkit import shot as SH
    def book(name, uuid, calc, order, formula="SUM([x])"):
        cols = [f"<column name='[Calculation_{calc}]' caption='A'><calculation formula='{formula}'/></column>",
                "<column name='[b]' caption='B'/>"]
        if order:
            cols.reverse()
        xml = (f"<?xml version='1.0'?><!-- build {uuid} --><workbook><datasources>"
               f"<datasource name='textscan.{uuid}'>{''.join(cols)}</datasource>"
               f"</datasources></workbook>")
        p = tmp_path / name
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("b.twb", xml)
            z.writestr("d.csv", "a,b\n1,2\n")
        return str(p)
    a = book("a.twbx", "52df2018-450c-4121-be20-efb57cfd2d81", "CDEA3446361047F293F9FB678F88623B", False)
    b = book("b.twbx", "9a680c1d-cb92-4f6c-9f4d-368cdb86fddb", "00D2864267774741842884F359B122E1", True)
    c = book("c.twbx", "9a680c1d-cb92-4f6c-9f4d-368cdb86fddb", "00D2864267774741842884F359B122E1", True,
             formula="AVG([x])")
    assert SH.book_fingerprint(a) == SH.book_fingerprint(b)
    assert SH.book_fingerprint(a) != SH.book_fingerprint(c)
    shots = tmp_path / "shots"
    assert SH.needs_shot([a], str(shots)) == [a]
    shots.mkdir(); (shots / "a.png").write_bytes(b"x")
    SH.remember_shot(a, str(shots))
    assert SH.needs_shot([a], str(shots)) == []
