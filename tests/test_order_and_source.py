import os

import pytest
from lxml import etree

from twkit import order
from _userdata import FIXTURES  # noqa: E402


def test_datasource_element_order_restored():
    ds = etree.fromstring(
        "<datasource>"
        "<connection/><column name='a'/><folders-common/><column name='b'/>"
        "<layout/><column name='c'/>"
        "</datasource>")
    assert order.normalize_datasource(ds) is True
    tags = [c.tag for c in ds]
    assert tags == ["connection", "column", "column", "column",
                    "folders-common", "layout"]


def test_columns_not_shuffled():
    ds = etree.fromstring(
        "<datasource><folders-common/>"
        "<column name='first'/><column name='second'/><column name='third'/>"
        "</datasource>")
    order.normalize_datasource(ds)
    assert [c.get("name") for c in ds if c.tag == "column"] == [
        "first", "second", "third"]


def test_unknown_elements_kept():
    ds = etree.fromstring("<datasource><strange/><connection/><column name='a'/></datasource>")
    order.normalize_datasource(ds)
    tags = [c.tag for c in ds]
    assert "strange" in tags and tags[0] == "connection"


def test_correct_order_left_alone():
    ds = etree.fromstring("<datasource><connection/><column name='a'/><layout/></datasource>")
    assert order.normalize_datasource(ds) is False


def test_reference_line_scope_matches_tableau(tmp_path):
    import _matrix_book as M
    from twkit.book import Book
    b = Book.open(M.build(str(tmp_path)))
    with pytest.raises(ValueError, match="scope"):
        b.add_reference_line("Bars", axis_field="SUM(sales)", value_field="SUM(sales)",
                             scope="entire-table")
    b.add_reference_line("Bars", axis_field="SUM(sales)", value_field="SUM(sales)",
                         scope="per-table")
    assert any(r.get("scope") == "per-table" for r in b.root.iter("reference-line"))


REF_BOOK = os.path.join(FIXTURES, "Self Service.twbx")


def _hyper_from(book: str) -> str:
    import tempfile
    import zipfile
    with zipfile.ZipFile(book) as z:
        name = next(n for n in z.namelist() if n.endswith(".hyper"))
        out = os.path.join(tempfile.gettempdir(), os.path.basename(name))
        if not os.path.exists(out):
            with open(out, "wb") as f:
                f.write(z.read(name))
    return out


@pytest.mark.skipif(not os.path.exists(REF_BOOK), reason="reference book not available")
def test_schema_read_from_extract():
    pytest.importorskip("tableauhyperapi")
    from twkit.extract import schema_from_hyper
    fields = schema_from_hyper(_hyper_from(REF_BOOK))
    assert fields
    assert all({"name", "datatype", "role"} <= set(f) for f in fields)
    roles = {f["role"] for f in fields}
    assert roles == {"measure", "dimension"}, roles
