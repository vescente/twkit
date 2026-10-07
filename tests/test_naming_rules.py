import os

import pytest

from twkit.extract import ch_type_to_hyper
from twkit.lint import lint

HERE = os.path.dirname(os.path.abspath(__file__))
import glob
from _userdata import FIXTURES  # noqa: E402

_SNAP = os.path.join(FIXTURES, "Old Users.REF.twbx")
OWNER_OLD_USERS = _SNAP if os.path.exists(_SNAP) else ""


def _r35(path):
    return [v for v in lint(path) if v.rule == "R35"]


@pytest.mark.parametrize("ch,hyper", [
    ("Int64", "big_int"),
    ("UInt8", "big_int"),
    ("Float64", "double"),
    ("Date", "date"),
    ("Date32", "date"),
    ("DateTime", "timestamp"),
    ("DateTime64(3)", "timestamp"),
    ("String", "text"),
    ("LowCardinality(String)", "text"),
    ("Nullable(Date)", "date"),
    ("Nullable(LowCardinality(String))", "text"),
    ("Decimal(18, 4)", "double"),
    ("Enum8('a' = 1)", "text"),
    ("Tuple(a Int64)", "text"),
])
def test_ch_type_to_hyper(ch, hyper):
    assert ch_type_to_hyper(ch) == hyper


def test_r35_flags_default_names_and_missing_folders():
    if not OWNER_OLD_USERS or not os.path.exists(OWNER_OLD_USERS):
        pytest.skip("no pre-rebuild snapshot on this machine")
    msgs = " ".join(v.message for v in _r35(OWNER_OLD_USERS))
    assert "outside the Calcs folder" in msgs
    assert "without folders" in msgs
    assert "default field names" in msgs
    assert "trace" in msgs


def test_r35_is_warning_not_error():
    if not OWNER_OLD_USERS or not os.path.exists(OWNER_OLD_USERS):
        pytest.skip("no pre-rebuild snapshot on this machine")
    assert all(v.severity == "warn" for v in _r35(OWNER_OLD_USERS))


def test_r35_reports_field_once():
    if not OWNER_OLD_USERS or not os.path.exists(OWNER_OLD_USERS):
        pytest.skip("no pre-rebuild snapshot on this machine")
    copy_msg = next((v.message for v in _r35(OWNER_OLD_USERS)
                     if "trace" in v.message and "field_count" in v.message), "")
    assert "Calculation_" not in copy_msg


def test_folders_not_duplicated_on_second_call():
    from lxml import etree

    from twkit.blocks import field_folders

    class FakeEditor:
        pass

    ds = etree.Element("datasource")
    for name in ("updated_at", "user_id", "_helper"):
        col = etree.SubElement(ds, "column")
        col.set("name", f"[{name}]")
    ed = FakeEditor()
    ed.datasource = ds

    field_folders(ed, {"System": ["updated_at"]})
    field_folders(ed, {"System": ["_helper"], "Calcs": ["user_id"]})

    holder = ds.find("folders-common")
    names = [f.get("name") for f in holder.findall("folder")]
    assert names.count("System") == 1, names
    system = next(f for f in holder.findall("folder") if f.get("name") == "System")
    items = {i.get("name") for i in system.findall("folder-item")}
    assert items == {"[updated_at]", "[_helper]"}
