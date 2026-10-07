import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "mcp"))

from lxml import etree

from twkit import lint as LINT


class _B:
    def __init__(self, root):
        self.root = root


def _book(tooltip_prefix: str, formula: str) -> _B:
    return _B(etree.fromstring(f"""<workbook><datasources>
        <datasource name='ds'>
          <column name='[Calculation_1]' datatype='real' role='measure'>
            <calculation class='tableau' formula='{formula}'/></column>
        </datasource></datasources>
      <worksheets><worksheet name='Line'><table><view>
          <datasources><datasource name='ds'/></datasources></view>
        <rows>[ds].[usr:Calculation_1:qk]</rows>
        <panes><pane><mark class='Line'/><encodings>
          <tooltip column='[ds].[{tooltip_prefix}:Calculation_1:qk]'/>
        </encodings></pane></panes></table></worksheet></worksheets></workbook>""".encode()))


def _r34(book):
    return LINT.r34_double_aggregation(book)


def test_flags_sum_over_aggregate():
    got = _r34(_book("sum", "SUM(IF [measure] = &apos;FTD&apos; THEN [value] END)"))

    assert len(got) == 1, got
    assert got[0].rule == "R34" and got[0].severity == LINT.ERROR
    assert "Line" in got[0].message and "Calculation_1" in got[0].message


def test_usr_on_aggregate_is_fine():
    assert _r34(_book("usr", "SUM([value])")) == []


def test_sum_over_row_formula_is_fine():
    assert _r34(_book("sum", "[Profit] / [Sales]")) == []


def test_flags_table_calculation():
    got = _r34(_book("sum", "WINDOW_SUM(SUM([value]))"))
    assert len(got) == 1, got


def test_repeats_per_sheet_not_duplicated():
    root = etree.fromstring("""<workbook><datasources>
        <datasource name='ds'>
          <column name='[Calculation_1]' datatype='real' role='measure'>
            <calculation class='tableau' formula='SUM([value])'/></column>
        </datasource></datasources>
      <worksheets><worksheet name='Line'><table><view>
          <datasources><datasource name='ds'/></datasources></view>
        <panes><pane><mark class='Line'/><encodings>
          <tooltip column='[ds].[sum:Calculation_1:qk]'/>
          <text column='[ds].[sum:Calculation_1:qk]'/>
        </encodings></pane></panes></table></worksheet></worksheets></workbook>""".encode())

    assert len(_r34(_B(root))) == 1


def test_rule_silent_on_corpus_books():
    import glob

    from _userdata import INSPIRATION
    books = (sorted(glob.glob(os.path.join(INSPIRATION, "*.twbx")))
             + sorted(glob.glob(os.path.expanduser(
                 "~/Documents/My Tableau Repository/Workbooks/*.twbx"))))
    if not books:
        import pytest
        pytest.skip("corpus not available")

    caught = []
    for path in books:
        try:
            b = LINT.load(path)
        except Exception:
            continue
        caught += [(os.path.basename(path), v.message) for v in _r34(b)]

    assert not caught
