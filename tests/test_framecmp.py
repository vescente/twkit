from twkit import framecmp as C
from twkit import frame


def test_tokens_numbers_and_words():
    t = C.tokens("Sales $733.2K vs. Previous Year +20.4%")
    assert {"$733.2K", "+20.4%", "sales", "previous", "year"} <= t


def test_shape_separates_value_from_format():
    assert C.shape("$733.2K") == C.shape("$745.6K")
    assert C.shape("$733,215") != C.shape("$745568")


def test_classes():
    assert C.classes({"$733.2K"}, {"$745.6K"}, "", False) == ["value"]
    assert C.classes({"$733,215"}, {"$745568"}, "", False) == ["format"]
    assert C.classes({"sales"}, set(), "error: none", True) == ["error", "empty", "text"]


def test_sfnt_names_roundtrip():
    import struct
    name = "Tableau Book".encode("utf-16-be")
    sub = "Bold".encode("utf-16-be")
    strs = name + sub
    recs = struct.pack(">6H", 3, 1, 0x409, 1, len(name), 0) + struct.pack(">6H", 3, 1, 0x409, 2, len(sub), len(name))
    tbl = struct.pack(">HHH", 0, 2, 6 + 24) + recs + strs
    off = 12 + 16
    blob = struct.pack(">IHHHH", 0x10000, 1, 0, 0, 0) + struct.pack(">4sIII", b"name", 0, off, len(tbl)) + tbl
    assert frame._sfnt_names(blob) == ("Tableau Book", "Bold")


def test_page_url_escapes_hash():
    import pathlib
    u = pathlib.Path("/tmp/Sales _ #VOTD/page_01.html").as_uri()
    assert "#" not in u and "%23" in u


def _snap(path, zones: dict):
    import json as _j
    pages = {"Main": {"zones": [{"id": k, "zone": k, "view": "v", "classes": v, "missing": []}
                                for k, v in zones.items()]}}
    _j.dump({"books": {"Book": {"pages": pages}}}, open(path, "w"))
    return str(path)


def test_gate_redraws_a_zone_that_went_empty_before_calling_it_worse(tmp_path):
    from twkit import framecmp as FC
    base = _snap(tmp_path / "base.json", {"a": [], "b": ["text"]})
    run = _snap(tmp_path / "run.json", {"a": ["empty"], "b": ["value"]})
    asked = []

    def rerun(books):
        asked.append(books)
        _snap(tmp_path / "run.json", {"a": [], "b": ["value"]})
    got = FC.gate(base, run, rerun)
    assert asked == [["Book"]]
    assert got["worse"] == 1 and [z["zone"] for z in got["worse_zones"]] == ["b"]
    assert got["recovered"] == ["Book | Main | a"]


def test_gate_keeps_an_empty_zone_that_stays_empty(tmp_path):
    from twkit import framecmp as FC
    base = _snap(tmp_path / "base.json", {"a": []})
    run = _snap(tmp_path / "run.json", {"a": ["empty"]})
    got = FC.gate(base, run, lambda books: None)
    assert got["worse"] == 1 and got["recovered"] == []
    assert FC.gate(base, _snap(tmp_path / "ok.json", {"a": []}), lambda b: 1 / 0)["redrawn"] == []


def test_corpus_refuses_a_name_it_does_not_know(tmp_path):
    import json as _j
    import pytest
    from twkit import framecmp as FC
    man = tmp_path / "manifest.json"
    _j.dump([{"book": "Retention in Education - full name", "dashboards": []}], open(man, "w"))
    with pytest.raises(ValueError, match="Retention in Education - full name"):
        FC.corpus(str(man), str(tmp_path), str(tmp_path / "run.json"), only=["Retention in Education"])
