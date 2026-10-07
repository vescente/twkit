import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))
import pytest

from twkit import palette as P


def test_snippet_uses_straight_quotes_and_the_documented_shape():
    out = P.snippet("Sign", ["#c4813c", "#4f8a5b"])
    assert 'name="Sign"' in out and 'type="ordered-diverging"' in out
    assert "“" not in out and "’" not in out, "curly quotes break Preferences.tps"
    assert out.count("<color>") == 2


def test_bad_input_is_refused_before_it_reaches_a_file():
    with pytest.raises(ValueError, match="#rrggbb"):
        P.snippet("Sign", ["c4813c"])
    with pytest.raises(ValueError, match="two end colours"):
        P.snippet("Sign", ["#c4813c"])
    with pytest.raises(ValueError, match="palette type"):
        P.snippet("Sign", ["#c4813c", "#4f8a5b"], kind="rainbow")
    with pytest.raises(ValueError, match="needs a name"):
        P.snippet("  ", ["#c4813c", "#4f8a5b"])


def test_nothing_is_written_unless_asked(tmp_path):
    path = tmp_path / "Preferences.tps"
    out = P.install("Sign", ["#c4813c", "#4f8a5b"], path=str(path))
    assert out["written"] is False and not path.exists()
    assert "apply=True" in out["next_step"]


def test_writing_keeps_a_backup_and_never_replaces_a_named_palette(tmp_path):
    path = tmp_path / "Preferences.tps"
    path.write_text("<?xml version='1.0'?>\n<workbook>\n  <preferences>\n"
                    '    <color-palette name="Just black" type="regular">\n'
                    "      <color>#000000</color>\n    </color-palette>\n"
                    "  </preferences>\n</workbook>\n", encoding="utf-8")

    out = P.install("Sign", ["#c4813c", "#4f8a5b"], path=str(path), apply=True)
    assert out["written"] is True and os.path.exists(out["backup"])
    text = path.read_text(encoding="utf-8")
    assert 'name="Sign"' in text and 'name="Just black"' in text, "existing palette survives"

    again = P.install("Just black", ["#111111", "#222222"], path=str(path), apply=True)
    assert again["written"] is False and "already declared" in again["refused"], \
        "overwriting someone's tuned colours without being asked is the loss we guard against"


def test_oversized_palette_is_allowed_but_the_dialog_limit_is_named(tmp_path):
    out = P.install("Wide", [f"#{i:02x}0000" for i in range(25)],
                    path=str(tmp_path / "p.tps"))
    assert "Edit Colors shows only 20" in out["note"]
