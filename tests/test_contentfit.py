from twkit import contentfit as CF
from twkit import layoutmodel as LM
from twkit import style as S


def test_tidy_caption_drops_tableau_tail_and_keeps_numbered_week():
    assert CF.tidy_caption("% of Total Bet along Table (Down)") == "% of Total Bet"
    assert CF.tidy_caption("player_segment") == "Player segment"
    assert CF.tidy_caption("Company Name 2") == "Company Name"
    assert CF.tidy_caption("Week 2") == "Week 2"


def test_tidy_caption_applies_caller_tails_after_tableau():
    tails = [(r"(?i)\s+classification$", "")]
    assert CF.tidy_caption("Tier classification along Table (Down)", tails) == "Tier"


def test_two_line_px_splits_at_best_gap():
    one = LM.text_width("Deposit Acceptance Rate", 10)
    assert CF.two_line_px("Deposit Acceptance Rate") < one
    assert CF.two_line_px("Deposit​") == CF.two_line_px("Deposit")


def test_compact_mask_keeps_currency_prefix():
    assert CF.compact_mask(S.FMT["eur"], 2e6) == S.FMT["eur_k"]
    assert CF.compact_mask(S.FMT["int"], 2e6) == S.FMT["thousands"]
    assert CF.compact_mask(S.FMT["eur"], 9e4) == S.FMT["eur"]
    assert CF.compact_mask(S.FMT["pct1"], 2e6) == S.FMT["pct1"]
    assert CF.compact_mask(S.FMT["eur_m"], 2e9) == S.FMT["eur_m"]


def test_label_column_short_values_keep_auto_width_unless_header_needs_more():
    assert CF.label_column_px({"UK", "DE"}, "Country") is None
    px = CF.label_column_px({"12", "13"}, "Foreign Partner Identifier Code")
    assert px and px > CF.AUTO_HEAD_PX


def test_label_column_gives_up_a_little_room_when_labels_stay_distinct():
    vals = {"Sports top five matches by turnover", "Casino slots weekly"}
    assert CF.label_column_px(vals, "Name", free=200) == 200
    assert CF.label_column_px(vals, "Name") <= 220


def test_label_column_takes_free_room_when_clipping_would_merge_labels():
    vals = {"Very long provider name alpha one", "Very long provider name alpha two"}
    assert CF.label_column_px(vals, "Provider", free=500) > 220


def test_measure_cell_goes_to_three_lines_when_zone_is_narrow():
    heads = ["Deposit Acceptance Rate Percent", "Withdrawal Acceptance Rate Percent"]
    w, head = CF.measure_cell_px(heads, ["12.5%"], zone_w=300, used=90)
    assert head == CF.THREE_LINE_HEAD_PX
    w, head = CF.measure_cell_px(heads, ["12.5%"], zone_w=2000, used=90)
    assert w > CF.AUTO_HEAD_PX and head == 0
    assert CF.measure_cell_px(["GGR"], ["1"], 300, 90) == (0, 0)


def test_header_px_only_for_three_or_more_lines():
    assert CF.header_px(2) == 0
    assert CF.header_px(3) == int(4 + CF.HEAD_LINE_PX * 3)
    assert CF.header_px(9) == CF.header_px(4)
    assert CF.header_px(99) == 0


def test_title_room_widens_first_column_under_long_title():
    assert CF.title_room_px("Top 10", [80, 60]) == 0
    title = "Daily first deposits by affiliate top ten"
    px = CF.title_room_px(title, [60, 50])
    assert px > 60 and px + 50 + 12 >= CF.two_line_px(title, 15) - 6
    assert CF.title_room_px(title, [60, 50], "Affiliate Identifier Long") >= \
        int(CF.two_line_px("Affiliate Identifier Long"))


def test_equal_row_heights_per_row_only():
    zones = {"a": {"y": 100, "h": 300}, "b": {"y": 101, "h": 299}, "c": {"y": 500, "h": 300}}
    assert CF.equal_row_heights(zones, {"a": 52}) == {"a": 52, "b": 52}


def _chart(h):
    return {"type": "worksheet", "name": "chart", "_h": h, "fixed_size": h}


def test_squeeze_row_gives_chart_height_to_table_height():
    table = {"type": "worksheet", "name": "t", "_h": 240, "_w": 300}
    stack = {"type": "container", "direction": "vertical", "_chart": True, "_h": 500,
             "children": [_chart(250), _chart(250)]}
    assert CF.squeeze_row([table, stack]) == 320
    assert [c["fixed_size"] for c in stack["children"]] == [160, 160]
    assert CF.squeeze_row([table, _chart(500)]) == 240
    assert CF.squeeze_row([table, _chart(260)]) is None


def test_drop_orphan_heads_only_over_lost_sheets():
    kids = [{"type": "text"}, {"type": "empty", "_lost": True}, {"type": "text"}, {"type": "worksheet"}]
    CF.drop_orphan_heads(kids)
    assert kids[:2] == [None, None] and kids[2] and kids[3]


def test_row_overflow_and_balance():
    table = {"type": "worksheet", "_w": 600, "fixed_size": 400}
    chart = {"type": "worksheet", "fixed_size": 800}
    assert CF.row_overflow([table, chart], 1200)
    widths = {0: 400.0, 1: 800.0}
    CF.balance([table, chart], widths)
    assert widths == {0: 600.0, 1: 600.0}
    assert not CF.row_overflow([table], 1200)




def test_equal_row_pitch_for_level_tables_with_as_many_rows():
    zones = {"a": {"y": 821, "h": 255}, "b": {"y": 822, "h": 413}, "c": {"y": 821, "h": 255}}
    got = CF.equal_row_pitch(zones, {"a": 35, "b": 0, "c": 0}, {"a": 5, "b": 5, "c": 20})
    assert got == {"a": 35, "b": 35}, "zone heights may differ; a 20-row neighbour is not stretched"
