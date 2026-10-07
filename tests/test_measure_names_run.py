import zipfile

import pytest

from twkit import dryrun
from twkit.dryrun import Translator

DS = "federated.mn"


def _sheet_xml(measures):
    members = "".join(
        f"<groupfilter function='member' level='[:Measure Names]' "
        f"member='&quot;[{DS}].[{m}]&quot;'/>" for m in measures)
    return f"""<worksheet name="tab"><table><view>
      <datasources><datasource caption="D" name="{DS}"/></datasources>
      <datasource-dependencies datasource="{DS}">
        <column datatype="string" name="[metric]" role="dimension" type="nominal"/>
        <column datatype="real" name="[val]" role="measure" type="quantitative"/>
        <column-instance column="[metric]" derivation="None" name="[none:metric:nk]"
                         pivot="key" type="nominal"/>
        <column-instance column="[val]" derivation="Sum" name="[sum:val:qk]"
                         pivot="key" type="quantitative"/>
      </datasource-dependencies>
      <filter class="categorical" column="[{DS}].[:Measure Names]">
        <groupfilter function="union">{members}</groupfilter>
      </filter>
      <aggregation value="true"/>
    </view>
    <rows>[{DS}].[none:metric:nk]</rows>
    <cols>[{DS}].[:Measure Names]</cols></table></worksheet>"""


def test_measures_from_measure_names_filter():
    from lxml import etree

    ws = etree.fromstring(_sheet_xml(["sum:val:qk", "sum:other:qk"]).encode())

    got = dryrun._measure_names_refs(ws)

    assert got == ["[sum:val:qk]", "[sum:other:qk]"]


def test_without_measure_names_filter_nothing_invented():
    from lxml import etree

    ws = etree.fromstring(
        "<worksheet name='x'><table><view/></table></worksheet>".encode())

    assert dryrun._measure_names_refs(ws) == []


@pytest.mark.parametrize("formula,expect", [
    ("ZN([a])", "COALESCE(a, 0)"),
    ("ZN(SUM([a]))", "COALESCE(SUM(a), 0)"),
    ("ZN(COUNTD(IF [a]='x' THEN [b] END))",
     "COALESCE(COUNT(DISTINCT CASE WHEN a='x' THEN b END), 0)"),
    ("ZN([a]) + ZN(SUM([b]))", "COALESCE(a, 0) + COALESCE(SUM(b), 0)"),
    ("IFNULL([a], 0)", "COALESCE(a, 0)"),
])
def test_zn_adds_zero_inside_nested_call(formula, expect):
    tr = Translator({}, {}, {}, {"a", "b"}, dialect="hyper")

    assert tr.to_sql(formula)[0] == expect


def test_crosstab_not_bars():
    from lxml import etree

    crosstab = etree.fromstring(_sheet_xml(["sum:val:qk"]).encode())
    assert dryrun._is_text_table(crosstab)

    bar = etree.fromstring(f"""<worksheet name="b"><table>
      <panes><pane><mark class="Bar"/></pane></panes>
      <rows>[{DS}].[none:metric:nk]</rows>
      <cols>[{DS}].[sum:val:qk]</cols></table></worksheet>""".encode())
    assert not dryrun._is_text_table(bar)

    heat = etree.fromstring(f"""<worksheet name="h"><table>
      <panes><pane><mark class="Square"/></pane></panes>
      <rows>[{DS}].[none:metric:nk]</rows>
      <cols>[{DS}].[:Measure Names]</cols></table></worksheet>""".encode())
    assert not dryrun._is_text_table(heat)


@pytest.mark.parametrize("value,expect", [
    (543775.5572517832, "543 776"),
    (4504894.730350221, "4 504 895"),
    (10803.0, "10 803"),
    (9.223100465615916, "9.22"),
    (0.11446813428061287, "0.1145"),
    (-0.06857349756813491, "-0.0686"),
    (0, "0"),
    (None, ""),
    ("Deposits", "Deposits"),
])
def test_sketch_prints_numbers_like_tableau(value, expect):
    from twkit.sketch import _cell

    assert _cell(value) == expect


def test_sketch_survives_nan():
    from twkit.sketch import _cell, _is_number

    assert _cell(float("nan")) == ""
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))
    assert not _is_number(None)
    assert _is_number(0) and _is_number(-3.5)
