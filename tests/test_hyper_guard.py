"""A check never fills the disk: Hyper stops a runaway query, the relationship view joins only what a query
reads, and unpacked extracts are removed."""
import os
import sys
import time
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from twkit import dryrun as D
from twkit import extract as EX

hyper = pytest.importorskip("tableauhyperapi")
from tableauhyperapi import (  # noqa: E402
    Connection, CreateMode, HyperProcess, SqlType, TableDefinition, TableName, Telemetry)

_CROSS = ("SELECT COUNT(DISTINCT a::BIGINT * 100000000 + b) "
          "FROM generate_series(1, 60000) a, generate_series(1, 60000) b")


def test_the_guard_settings_start_hyper_and_stop_a_spilling_query(tmp_path):
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters=EX.HYPER_QUIET):
        pass
    small = {**EX.HYPER_QUIET, "temp_file_size_limit": "64m"}
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters=small) as hp:
        with Connection(hp.endpoint, str(tmp_path / "x.hyper"), CreateMode.CREATE_AND_REPLACE,
                        parameters=EX.HYPER_READ_TIMEOUT) as c:
            t = time.time()
            with pytest.raises(Exception) as err:
                c.execute_scalar_query(_CROSS)
    assert time.time() - t < 60 and D._GUARD_STOP.search(str(err.value))


def _spec():
    return {"tables": {"r0": "t_out", "r1": "t_day", "r2": "t_in"},
            "fields": {"out_id": ("r0", "out_id"), "uid": ("r1", "uid"), "amount": ("r1", "amount"),
                       "in_id": ("r2", "in_id")},
            "edges": [("r0", "r1", "r1.uid = r0.uid"), ("r0", "r2", "r2.uid = r0.uid")]}


class _Base:
    dialect = "hyper"


def test_a_query_on_one_table_reads_it_alone():
    v = D._RelTarget(_Base(), _spec(), set(), set()).view_for("SELECT SUM(amount) FROM _rel")
    assert "FROM t_day AS r1" in v and "JOIN" not in v and "out_id" not in v


def test_the_view_roots_at_a_read_table_and_keeps_only_the_path_between_them():
    v = D._RelTarget(_Base(), _spec(), set(), set()).view_for("SELECT SUM(amount), COUNT(in_id) FROM _rel")
    assert v.index("FROM t_day AS r1") < v.index("LEFT JOIN t_out AS r0") < v.index("LEFT JOIN t_in AS r2")


def _book(path, rows):
    h = str(path) + ".hyper"
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters=EX.HYPER_QUIET) as hp:
        with Connection(hp.endpoint, h, CreateMode.CREATE_AND_REPLACE) as c:
            c.catalog.create_schema("Extract")
            t = TableDefinition(TableName("Extract", "Extract"), [TableDefinition.Column("n", SqlType.int())])
            c.catalog.create_table(t)
            c.execute_command(f'INSERT INTO "Extract"."Extract" SELECT * FROM generate_series(1, {rows})')
    with zipfile.ZipFile(path, "w") as z:
        z.write(h, "Data/Extracts/e.hyper")
    os.remove(h)


def test_unpacked_copies_are_removed(tmp_path):
    book = str(tmp_path / "b.twbx")
    _book(book, 3)
    a = D._open_hyper(book, "Data/Extracts/e.hyper")
    b = D._open_hyper(book, "Data/Extracts/e.hyper")
    cached = os.path.dirname(a.path)
    own = b.own_dir
    b.close()
    assert not own or not os.path.exists(own)
    a.close()
    time.sleep(1.1)
    _book(book, 4)
    D._open_hyper(book, "Data/Extracts/e.hyper").close()
    assert not os.path.exists(cached)
    D._drop_cache()
    assert not D._HYPER_CACHE
