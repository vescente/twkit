import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from twkit import extract as EX

_TWB = """<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1'>
  <datasources>
    <datasource caption='P&amp;L' inline='true' name='federated.x' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='h' name='mysql.x'>
            <connection class='mysql' dbname='reports' port='3306' server='h'
                        username='tableau' />
          </named-connection>
        </named-connections>
        <relation connection='mysql.x' name='Custom SQL Query' type='text'>SELECT 1</relation>
        <metadata-records>
          <metadata-record class='column'>
            <parent-name>[Custom SQL Query]</parent-name>
          </metadata-record>
        </metadata-records>
      </connection>
      <column datatype='date' name='[Month]' role='dimension' type='ordinal' />
      <column datatype='real' name='[Money]' role='measure' type='quantitative' />
      <column datatype='integer' name='[Sort Order]' role='measure' type='quantitative' />
      <column datatype='string' name='[Line]' role='dimension' type='nominal' />
    </datasource>
  </datasources>
</workbook>
"""


def _book(tmp_path):
    p = tmp_path / "Book.twbx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Book.twb", _TWB)
    return str(p)


def test_types_from_book_declarations(tmp_path):
    types = EX.workbook_column_types(_book(tmp_path))
    assert types["Month"] == "date"
    assert types["Money"] == "double"
    assert types["Sort Order"] == "big_int"
    assert types["Line"] == "text"


def test_type_found_in_any_attribute_order(tmp_path):
    twb = _TWB.replace(
        "<column datatype='date' name='[Month]'",
        "<column datatype='date' default-format='*mmm yyyy' name='[Month]'")
    p = tmp_path / "Reordered.twbx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Book.twb", twb)
    types = EX.workbook_column_types(str(p))
    assert types["Month"] == "date"
    assert types["Money"] == "double"


def test_workbook_sql_found(tmp_path):
    assert EX.workbook_sql(_book(tmp_path)).strip() == "SELECT 1"


def test_book_without_custom_sql_refused(tmp_path):
    p = tmp_path / "Plain.twbx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Plain.twb", "<workbook version='18.1'><datasources /></workbook>")
    res = EX.to_extract(str(p))
    assert res["ok"] is False
    assert "nothing to materialize" in res["why"]
