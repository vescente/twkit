import os

import pytest

from twkit import cdp, frame


def test_ws_frame_lengths_roundtrip():
    class Sock:
        def __init__(self):
            self.out = b""

        def sendall(self, b):
            self.out += b
    for n in (5, 300, 70000):
        ws = cdp._WS.__new__(cdp._WS)
        ws.s, ws.buf = Sock(), b""
        ws.send("x" * n)
        raw = ws.s.out
        assert raw[0] == 0x81 and raw[1] & 0x80
        ln = raw[1] & 0x7F
        assert ln == (n if n < 126 else 126 if n < 65536 else 127)


@pytest.mark.skipif(not os.path.exists(cdp.CHROME), reason="no Chrome")
def test_probe_uses_one_persistent_browser(tmp_path):
    page = tmp_path / "Sales _ #VOTD.html"
    page.write_text("<html><body><div class='canvas' style='width:100px;height:50px'>"
                    "<div class='zone' data-kind='text' data-id='1'>Hi</div></div>"
                    "<script>window.addEventListener('load',()=>{const e=document.createElement"
                    "('script');e.type='application/json';e.id='probe-out';"
                    "e.textContent=JSON.stringify({zones:[1]});document.body.appendChild(e);});"
                    "</script></body></html>")
    shot = str(tmp_path / "s.png")
    r = frame._probe_cdp(str(page), shot)
    assert r["zones"] == [1] and os.path.getsize(shot) > 0
    assert cdp._alive()


def test_shutdown_passes_the_profile_pattern_after_double_dash(monkeypatch):
    from twkit import cdp
    calls = []
    monkeypatch.setattr(cdp, "_http", lambda *a, **k: {})
    monkeypatch.setattr(cdp.subprocess, "run", lambda args, **k: calls.append(args))
    cdp.shutdown()
    args = calls[0]
    assert args[args.index("--") + 1].startswith("--user-data-dir="), \
        "pkill reads a leading-dash pattern as its own option and kills nothing"


def test_title_lines_do_not_count_trailing_blank_padding(tmp_path):
    from twkit import stylecritic as S
    page = tmp_path / "page_01.html"
    page.write_text("<html><body><div class='canvas' style='width:400px;height:200px'>"
                    "<div class='zone sheet' data-kind='worksheet' data-name='T' data-id='1' "
                    "style='width:300px;height:150px'><div class='ttl' style='font-size:20px'>Yesterday"
                    "<br><span> </span><br><span> </span></div></div></div>"
                    "<div id='probe-out'></div></body></html>")
    d, err = S.probe(str(page), {})
    title = next(z for z in d["zones"] if z["name"] == "T")["title"]
    assert title["lines"] == 1, title
