import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "mcp"))

from lxml import etree

from twkit import safexml
from twkit.extract import split_absent_refs


def _tree(xml: str):
    return safexml.from_bytes(etree.tostring(etree.fromstring(xml)))


DS = """<workbook><datasources><datasource name='ds'>
  <column name='[Sales]' datatype='real'/>
  <column name='[m_brand_id]' datatype='integer'/>
  <metadata-record class='column'><local-name>[m_brand_id]</local-name></metadata-record>
  <folder name='f'><folder-item name='[m_brand_id]'/></folder>
</datasource></datasources>{ws}</workbook>"""


def test_shelf_reference_to_missing_column_is_blocker():
    root = _tree(DS.format(ws="""<worksheets><worksheet name='w'><table><view/>
      <rows>[ds].[none:m_brand_id:nk]</rows></table></worksheet></worksheets>"""))
    dead, idle, _ = split_absent_refs(root, {"Sales"})
    assert dead == ["m_brand_id"], (dead, idle)
    assert idle == []


def test_unused_declaration_not_blocker():
    root = _tree(DS.format(ws="<worksheets/>"))
    dead, idle, used = split_absent_refs(root, {"Sales"})
    assert dead == []
    assert idle == ["m_brand_id"]
    assert used == 2


def test_cache_and_cosmetics_not_reads():
    root = _tree(DS.format(ws="""<worksheets><worksheet name='w'>
      <dictionary><bucket>&quot;[m_brand_id]&quot;</bucket></dictionary>
      <color-one-way><field>[m_brand_id]</field><field>[Sales]</field></color-one-way>
      <field-sort-info><field-sort-custom-order field='m_brand_id'/></field-sort-info>
    </worksheet></worksheets>"""))
    dead, idle, _ = split_absent_refs(root, {"Sales"})
    assert dead == [], dead
    assert idle == ["m_brand_id"]


def test_name_with_table_suffix_found_without_it():
    root = _tree("""<workbook><datasources><datasource name='ds'>
      <column name='[Order ID (Returns)]' datatype='string'/>
    </datasource></datasources><worksheets><worksheet name='w'>
      <rows>[ds].[none:Order ID (Returns):nk]</rows></worksheet></worksheets></workbook>""")
    dead, _idle, _ = split_absent_refs(root, {"Order ID"})
    assert dead == []


def test_named_calculation_not_a_dead_column():
    xml = """<workbook><datasources><datasource name='ds'>
      <column name='[Cohort FTD]' datatype='integer'>
        <calculation class='tableau' formula='SUM([FTD])'/>
      </column>
      <column name='[FTD]' datatype='integer'/>
    </datasource></datasources>
    <worksheets><worksheet name='KPI'><table><view>
      <datasource-dependencies datasource='ds'>
        <column name='[Cohort FTD]' datatype='integer'/>
      </datasource-dependencies>
      <rows>[ds].[Cohort FTD]</rows>
    </view></table></worksheet></worksheets></workbook>"""
    reading, idle, _ = split_absent_refs(_tree(xml), {"FTD"})
    assert reading == []
    assert idle == []


def test_real_dead_column_still_flagged():
    xml = """<workbook><datasources><datasource name='ds'>
      <column name='[ngr_old]' datatype='real'/>
    </datasource></datasources>
    <worksheets><worksheet name='S'><table><view>
      <rows>[ds].[ngr_old]</rows>
    </view></table></worksheet></worksheets></workbook>"""
    reading, _, _ = split_absent_refs(_tree(xml), {"ngr"})
    assert reading == ["ngr_old"]
