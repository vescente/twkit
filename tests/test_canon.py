import glob
import os

import pytest

from twkit import canon
from _userdata import CORPUS  # noqa: E402


@pytest.mark.skipif(not os.path.isdir(CORPUS), reason="corpus not available")
def test_corpus_has_no_canon_errors():
    dirty = {}
    for f in sorted(glob.glob(os.path.join(CORPUS, "*.twbx"))):
        errs = [x for x in canon.check_workbook(f) if x.severity == "error"]
        if errs:
            dirty[os.path.basename(f)] = [x.message for x in errs]
    assert not dirty, dirty


@pytest.mark.parametrize("caption,formula,why", [
    ("NGR", "SUM([ngr]) - SUM([rs_cost])", "NGR minus costs is profit"),
    ("FTD count", "SUM([ftd_attempts])", "attempts instead of depositors"),
    ("Total cost", "SUM([rs_cost]) + SUM([cpa_alt_cost])", "cpa_alt is another methodology"),
    ("Approval Rate", "AVG([ftd_count]/[ftd_attempts])", "average of ratios"),
])
def test_canon_catches_substitution(caption, formula, why):
    errs = [x for x in canon.check_formulas([(caption, formula)]) if x.severity == "error"]
    assert errs


@pytest.mark.parametrize("caption,formula", [
    ("NGR", "SUM([ngr])"),
    ("GGR", "SUM([ggr])"),
    ("FTD count", "SUM([ftd_count])"),
    ("Approval Rate", "SUM([ftd_count]) / NULLIF(SUM([ftd_attempts]), 0)"),
    ("Total cost", "SUM([rs_cost])+SUM([cpa_cost])+SUM([fix_cost])+SUM([hybrid_cost])"),
    ("ROMI", "SUM([ngr]) / NULLIF(SUM([rs_cost]), 0)"),
])
def test_canon_silent_on_correct(caption, formula):
    errs = [x for x in canon.check_formulas([(caption, formula)]) if x.severity == "error"]
    assert not errs, [x.message for x in errs]


def test_sql_marts_needs_final():
    errs = canon.check_sql("SELECT count() FROM marts.transactions")
    assert errs and "FINAL" in errs[0].canon


def test_sql_neighbour_final_does_not_count():
    errs = canon.check_sql("SELECT * FROM marts.transactions t JOIN marts.daily_metrics FINAL g ON 1")
    assert len(errs) == 1 and errs[0].metric == "marts.transactions"


def test_sql_final_ok():
    assert not canon.check_sql("SELECT * FROM marts.transactions FINAL")
    assert not canon.check_sql("SELECT * FROM marts.transactions AS t FINAL")
