import os

import pytest

from twkit import spec as SP

GOOD = {
    "name": "Test",
    "source": {"table": "reports.partner_daily", "period": ["2026-07-01", "2026-07-31"]},
    "parameters": {"metrics": {"NGR": "SUM([ngr])"}, "dimensions": ["traffic_source"]},
    "kpi": [{"title": "NGR", "expr": "SUM([ngr])", "format": "eur_k", "delta_by": "ngr"}],
    "blocks": [{"type": "trend", "sheet": "Trend"},
               {"type": "top", "sheet": "Top", "dimension": "traffic_source", "top": 5}],
}


def test_good_spec_validates():
    assert SP.validate(GOOD) == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda s: s.pop("source"), "table"),
    (lambda s: s["source"].update(table="partner_daily"), "schema.table"),
    (lambda s: s["blocks"].append({"type": "helicopter", "sheet": "X"}), "type"),
    (lambda s: s["blocks"].append({"type": "top", "sheet": "Y"}), "dimension"),
    (lambda s: s["blocks"].append({"type": "trend", "sheet": "Trend"}), "already used"),
    (lambda s: s["kpi"].append({"title": "X"}), "expr"),
    (lambda s: s["kpi"].append({"title": "X", "expr": "1", "format": "roubles"}), "format"),
])
def test_bad_spec_is_rejected_with_pointer(mutate, expect):
    import copy
    s = copy.deepcopy(GOOD)
    mutate(s)
    problems = SP.validate(s)
    assert problems, "an invalid spec passed validation"
    assert any(expect in p for p in problems), problems


def test_empty_spec_is_rejected():
    assert any("nothing to build" in p for p in SP.validate({"source": {"table": "a.b"}}))


def test_build_produces_clean_book(tmp_path):
    from twkit.lint import ERROR, counts, lint
    out = SP.build(GOOD, str(tmp_path / "spec.twbx"))
    assert os.path.exists(out)
    v = lint(out)
    assert counts(v)[ERROR] == 0, "\n".join(str(x) for x in v if x.severity == ERROR)


def test_build_adds_baseline_and_titles(tmp_path):
    import zipfile

    from lxml import etree
    out = SP.build(GOOD, str(tmp_path / "spec2.twbx"))
    with zipfile.ZipFile(out) as z:
        root = etree.fromstring(z.read([n for n in z.namelist() if n.endswith(".twb")][0]))
    assert list(root.iter("reference-line")), "no reference line"
    zones = [(z.get("type-v2") or "") for d in root.iter("dashboard") for z in d.iter("zone")]
    assert "title" in zones, "no title zone"
    assert zones.count("text") >= 1, "blocks without captions"


def test_unknown_dimension_is_skipped_not_crashed(tmp_path):
    import copy
    s = copy.deepcopy(GOOD)
    s["parameters"]["dimensions"] = ["traffic_source", "no_such_column"]
    out = SP.build(s, str(tmp_path / "spec3.twbx"))
    assert os.path.exists(out)


def test_describe_lists_all_block_types():
    d = SP.describe()
    assert set(d["blocks"]) == set(SP.BLOCK_TYPES)


STORY = {**GOOD, "story": {
    "name": "Review", "title": "What happened",
    "steps": [{"sheet": "Trend", "caption": "it grew"},
              {"sheet": "Top", "caption": "driven by one source"}]}}


def test_spec_with_story_validates():
    assert SP.validate(STORY) == []


@pytest.mark.parametrize("story,expect", [
    ({"steps": []}, "at least one step"),
    ({"steps": [{"sheet": "None", "caption": "x"}]}, "not among the blocks"),
    ({"steps": [{"sheet": "Trend"}]}, "required"),
    ("not a dict", "dict"),
])
def test_spec_story_errors(story, expect):
    import copy
    s = copy.deepcopy(GOOD)
    s["story"] = story
    problems = SP.validate(s)
    assert any(expect in p for p in problems), problems


def test_spec_builds_story_and_folders(tmp_path):
    import zipfile

    from lxml import etree
    out = SP.build(STORY, str(tmp_path / "story_spec.twbx"))
    with zipfile.ZipFile(out) as z:
        root = etree.fromstring(z.read([n for n in z.namelist() if n.endswith(".twb")][0]))
    assert [d for d in root.iter("dashboard") if d.get("type") == "storyboard"]
    assert len(list(root.iter("story-point"))) == 2
    assert list(root.iter("folder")), "data pane folders were not created"
