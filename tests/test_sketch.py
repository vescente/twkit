import os

import pytest

from twkit import sketch
from _userdata import FIXTURES  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OURS = os.path.join(FIXTURES, "Self Service.twbx")


def test_sketch_stamp_required(tmp_path):
    out = str(tmp_path / "s.png")
    sketch.sketch_sheet([["A", "10"], ["B", "20"]], out, title="t")
    from PIL import Image
    im = Image.open(out).convert("RGB")
    w, h = im.size
    band = im.crop((0, h - 18, w, h)).getcolors(maxcolors=100000) or []
    assert any(c == sketch.STAMP for _, c in band), "SKETCH stamp not drawn"


def test_many_categories_noticed(tmp_path):
    rows = [[f"category {i}", str(i + 1)] for i in range(40)]
    r = sketch.sketch_sheet(rows, str(tmp_path / "many.png"), size=(300, 160))
    assert any("categories 40" in o for o in r["observations"]), r["observations"]


def test_value_spread_noticed(tmp_path):
    rows = [["large", "1000000"], ["small", "3"], ["medium", "500"]]
    r = sketch.sketch_sheet(rows, str(tmp_path / "spread.png"))
    assert any("spread" in o for o in r["observations"]), r["observations"]


def test_merged_labels_noticed(tmp_path):
    rows = [["Affiliates_Randy A, CS", "10"], ["Affiliates_Randy A, FA", "20"]]
    r = sketch.sketch_sheet(rows, str(tmp_path / "clash.png"), size=(170, 120))
    assert any("INDISTINGUISHABLE" in o for o in r["observations"]), r["observations"]


def test_empty_sheet_not_reported_drawn(tmp_path):
    r = sketch.sketch_sheet([], str(tmp_path / "empty.png"))
    assert "sheet is empty" in " ".join(r["observations"])
    assert os.path.exists(r["file"])


def test_non_numeric_measure_reported(tmp_path):
    r = sketch.sketch_sheet([["A", "not a number"]], str(tmp_path / "nan.png"))
    assert any("did not parse" in o for o in r["observations"])


@pytest.mark.skipif(not os.path.exists(OURS), reason="built book not available")
def test_sketches_built_for_all_sheets(tmp_path):
    pytest.importorskip("tableauhyperapi")
    r = sketch.sketch_workbook(OURS, str(tmp_path))
    assert len(r["sketches"]) == 7
    assert all(os.path.exists(e["file"]) for e in r["sketches"])


@pytest.mark.skipif(not os.path.exists(OURS), reason="built book not available")
def test_sketch_uses_zone_size(tmp_path):
    pytest.importorskip("tableauhyperapi")
    r = sketch.sketch_workbook(OURS, str(tmp_path))
    sizes = {e["sheet"]: e["size"] for e in r["sketches"]}
    assert sizes["tab"] == "1100x643"
    assert sizes["bar1"].startswith("550")


def test_relaxed_run_returns_sheet():
    from twkit import dryrun as DR
    res = DR.SheetResult("Matrix", "ok", rows=40,
                         relaxed="not computed: Level 1 Dim*")
    assert res.as_dict()["relaxed"].startswith("not computed")


def test_relaxation_names_dropped_dimension():
    from twkit import dryrun as DR
    r = DR.SheetResult("Matrix", "ok", relaxed="not computed: Level 1 Dim*; "
                                                "marked * - DIMENSION dropped")
    assert "DIMENSION" in r.relaxed


def test_matrix_drawn_as_grid_not_bars():
    import tempfile

    from PIL import ImageDraw, Image

    from twkit import sketch as SK
    rows = [[f"2026-0{m}-01", str(age), 100.0 - age * 5]
            for m in range(1, 5) for age in range(0, 6)]
    img = Image.new("RGB", (400, 200), (255, 255, 255))
    d = ImageDraw.Draw(img)
    obs = SK._draw_matrix(d, rows, 8, 8, 400, 200, SK._font(9), ndims=2)
    assert any("matrix 4x6" in o for o in obs), obs


def test_matrix_sorts_dimensions():
    from PIL import ImageDraw, Image

    from twkit import sketch as SK
    rows = [["2026-03-01", "2", 1.0], ["2026-01-01", "10", 2.0],
            ["2026-02-01", "1", 3.0]]
    img = Image.new("RGB", (300, 120), (255, 255, 255))
    obs = SK._draw_matrix(ImageDraw.Draw(img), rows, 8, 8, 300, 120,
                          SK._font(9), ndims=2)
    assert any("matrix 3x3" in o for o in obs), obs


def test_card_drawn_from_runs_and_measures_height(tmp_path):
    from lxml import etree
    from twkit import sketch as SK
    ws = etree.fromstring("""<worksheet name='K'><table><panes><pane>
      <customized-label><formatted-text>
        <run bold='true' fontsize='26'>&lt;[ds].[usr:kpi:qk]&gt;
</run><run fontsize='8'>SCORE &gt; 70% · REVIEW NOW</run>
      </formatted-text></customized-label></pane></panes></table></worksheet>""")
    lines = SK.card_lines(ws)
    assert len(lines) == 2 and lines[0][0][3] is True and lines[0][0][1] == 26
    tall = [[(t, 40.0, b, f) for (t, _, b, f) in ln] for ln in lines]
    small = SK.sketch_sheet([["LIKELY ABUSERS #", "238"]], str(tmp_path / "k.png"),
                            kind="card", size=(280, 120), card=tall, ncols_dims=1)
    assert any(o.startswith("card") for o in small["observations"])
    assert any("DOES NOT FIT" in o for o in small["observations"]), small["observations"]
    ok = SK.sketch_sheet([["LIKELY ABUSERS #", "238"]], str(tmp_path / "k2.png"),
                         kind="card", size=(280, 130), card=lines, ncols_dims=1)
    assert not any("DOES NOT FIT" in o for o in ok["observations"]), ok["observations"]
