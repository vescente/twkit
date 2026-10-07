import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "mcp"))

from twkit import selfcheck as sc


def test_toolkit_consistent():
    r = sc.selfcheck()
    assert not r["findings"]


def test_all_channels_wired_to_preflight():
    assert sc.channels_wired() == []


def test_every_module_classified():
    assert sc.modules_classified() == []


def test_no_dead_code():
    assert sc.dead_modules() == []


def test_documents_do_not_duplicate():
    bad, _gaps = sc.docs_consistent()
    assert bad == [], "\n  ".join(bad)


def test_selfcheck_catches_fake(tmp_path, monkeypatch):
    fake = os.path.join(sc.HERE, "_zzz_fake_channel.py")
    with open(fake, "w", encoding="utf-8") as f:
        f.write("# temporary test module\n")
    try:
        assert any("_zzz_fake_channel" in m for m in sc.modules_classified())
    finally:
        os.unlink(fake)
    assert sc.modules_classified() == []
