"""Materialise a database table into a Tableau extract (`.hyper`)."""
from __future__ import annotations

HYPER_QUIET = {"log_config": ""}

import os
import tempfile

from lxml import etree

from twkit import chsafe as _chsafe

_CH_TO_HYPER = {
    "integer": "big_int",
    "real": "double",
    "date": "date",
    "datetime": "timestamp",
    "boolean": "bool",
    "string": "text",
}


def describe_hyper(path: str) -> dict:
    """What a built .hyper holds: rows, columns, size, build date."""
    import datetime as _dt

    from tableauhyperapi import Connection, HyperProcess, TableName, Telemetry
    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                     parameters=HYPER_QUIET) as hp:
        with Connection(endpoint=hp.endpoint, database=path) as conn:
            tname = TableName("Extract", "Extract")
            rows = conn.execute_scalar_query(f"SELECT COUNT(*) FROM {tname}")
            cols = [c.name.unescaped for c in conn.catalog.get_table_definition(tname).columns]
    return {
        "path": path, "rows": rows, "columns": len(cols), "column_names": cols,
        "size_mb": round(os.path.getsize(path) / 1024 / 1024, 2),
        "built": _dt.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M"),
    }


def build_hyper(db: str, table: str, fields: list[dict], out_path: str,
                where: str = "", limit: int | None = None,
                reuse_if_unreachable: bool = False) -> dict:
    """Export a table into a .hyper."""
    from tableauhyperapi import (
        Connection, CreateMode, HyperProcess, Inserter, SqlType,
        TableDefinition, TableName, Telemetry,
    )

    from . import config                    # noqa: PLC0415 — local by design

    sql_type = {
        "big_int": SqlType.big_int(), "double": SqlType.double(),
        "date": SqlType.date(), "timestamp": SqlType.timestamp(),
        "bool": SqlType.bool(), "text": SqlType.text(),
    }
    cols = [(f["name"], _CH_TO_HYPER.get(f["datatype"], "text")) for f in fields]

    q = f"SELECT {', '.join(c for c, _ in cols)} FROM {db}.{table}"
    if where:
        q += f" WHERE {where}"
    if limit:
        q += f" LIMIT {int(limit)}"
    try:
        rows = config.clickhouse(read_only=True).execute(_chsafe.read_only(q))
    except Exception as exc:
        if not (reuse_if_unreachable and os.path.exists(out_path)):
            raise
        info = describe_hyper(out_path)
        info["reused"] = True
        info["why"] = f"ClickHouse unavailable ({type(exc).__name__}); using the existing extract from {info['built']}"
        return info

    import datetime as _dt

    def coerce(v, kind):
        if v is None or v == "":
            return None
        if kind == "big_int":
            return int(float(v))
        if kind == "double":
            return float(v)
        if kind == "bool":
            return bool(int(v))
        if kind == "date":
            return _dt.date.fromisoformat(str(v)[:10])
        if kind == "timestamp":
            s = str(v).replace("T", " ")[:19]
            return _dt.datetime.fromisoformat(s)
        return str(v)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)

    tdef = TableDefinition(
        table_name=TableName("Extract", "Extract"),
        columns=[TableDefinition.Column(n, sql_type[k]) for n, k in cols],
    )
    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                     parameters=HYPER_QUIET) as hp:
        with Connection(endpoint=hp.endpoint, database=out_path,
                        create_mode=CreateMode.CREATE_AND_REPLACE) as conn:
            conn.catalog.create_schema("Extract")
            conn.catalog.create_table(tdef)
            with Inserter(conn, tdef) as ins:
                ins.add_rows([[coerce(v, k) for v, (_, k) in zip(r, cols)] for r in rows])
                ins.execute()

    return {
        "path": out_path, "rows": len(rows), "columns": len(cols),
        "size_mb": round(os.path.getsize(out_path) / 1024 / 1024, 2), "reused": False,
    }


_HYPER_TO_TABLEAU = {
    "date": "date", "timestamp": "datetime", "timestamptz": "datetime",
    "text": "string", "varchar": "string", "char": "string",
    "big_int": "integer", "int": "integer", "small_int": "integer",
    "double": "real", "numeric": "real", "bool": "boolean",
}


def schema_from_hyper(path: str, table: str = "") -> list[dict]:
    """Fields from an extract, in the shape `schema.fetch_schema` returns for a table."""
    from tableauhyperapi import Connection, HyperProcess, Telemetry

    out: list[dict] = []
    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                      parameters=HYPER_QUIET) as hp:
        with Connection(endpoint=hp.endpoint, database=path) as conn:
            names = []
            for schema in conn.catalog.get_schema_names():
                names += list(conn.catalog.get_table_names(schema))
            if not names:
                raise RuntimeError(f"no tables in the extract: {path}")
            target = next((n for n in names if table and table in str(n)), names[0])
            for col in conn.catalog.get_table_definition(target).columns:
                raw = str(col.type).lower()
                dt = next((v for k, v in _HYPER_TO_TABLEAU.items() if k in raw), "string")
                out.append({
                    "name": col.name.unescaped,
                    "datatype": dt,
                    "role": "measure" if dt in ("integer", "real") else "dimension",
                    "comment": "",
                })
    return out


def hyper_schema(path: str, table: str) -> str:
    """The schema that holds `table` in an extract (`Extract` by Tableau's habit, `public` by the API's)."""
    from tableauhyperapi import Connection, HyperProcess, Telemetry

    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                      parameters=HYPER_QUIET) as hp:
        with Connection(endpoint=hp.endpoint, database=path) as conn:
            for schema in conn.catalog.get_schema_names():
                for name in conn.catalog.get_table_names(schema):
                    if name.name.unescaped == table:
                        return schema.name.unescaped
    return "Extract"


def live_extract_columns(book_path: str) -> set:
    """All extract columns of a workbook: every .hyper, every table inside it."""
    import zipfile

    from tableauhyperapi import Connection, HyperProcess, Telemetry

    with zipfile.ZipFile(book_path) as z:
        hypers = [n for n in z.namelist() if n.endswith(".hyper")]
        if not hypers:
            return set()
        paths = []
        for i, n in enumerate(hypers):
            tmp = os.path.join(tempfile.gettempdir(), f"twkit_live_{i}.hyper")
            with open(tmp, "wb") as f:
                f.write(z.read(n))
            paths.append(tmp)

    live: set = set()
    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                      parameters=HYPER_QUIET) as hp:
        for path in paths:
            with Connection(endpoint=hp.endpoint, database=path) as conn:
                for schema in conn.catalog.get_schema_names():
                    for table in conn.catalog.get_table_names(schema):
                        live |= {c.name.unescaped for c
                                 in conn.catalog.get_table_definition(table).columns}
    return live


def _bare(name: str) -> str:
    """`Order ID (Returns)` -> `Order ID`: the workbook appends the table name."""
    import re
    return re.sub(r"\s*\([^()]*\)$", "", name).strip()


_NOT_A_READ = {
    ("column", "datasource"),
    ("folder-item", None),
    (None, "metadata-record"),
    ("map", "cols"),
    ("bucket", "dictionary"),
    ("field", "color-one-way"),
    ("field-sort-custom-order", "field-sort-info"),
}


def _declaration_only(tag: str, parent_tag: str) -> bool:
    return ((tag, parent_tag) in _NOT_A_READ or (tag, None) in _NOT_A_READ
            or (None, parent_tag) in _NOT_A_READ)


def orphan_formula_refs(root) -> dict:
    """Fields referenced by formulas that no longer exist in the workbook."""
    import re

    from lxml import etree

    known: set = set()
    for col in root.iter("column"):
        nm = (col.get("name") or "").strip("[]")
        if nm:
            known.add(nm)
        if col.get("caption"):
            known.add(col.get("caption"))
    for rel in root.iter("relation"):
        cols = rel.find("columns")
        for c in (cols if cols is not None else []):
            if c.get("name"):
                known.add(c.get("name"))
    for g in root.iter("group"):
        for key in ("name", "caption"):
            if g.get(key):
                known.add(g.get(key).strip("[]"))

    used_on_sheets: set = set()
    for holder in list(root.iter("worksheet")) + list(root.iter("dashboard")):
        blob = etree.tostring(holder, encoding="unicode")
        used_on_sheets |= set(re.findall(r"\[([^\[\]]+)\]", blob))

    blocking: dict = {}
    idle: dict = {}
    for col in root.iter("column"):
        calc = col.find("calculation")
        if calc is None or not calc.get("formula"):
            continue
        body = re.sub(r"\[[^\[\]]+\]\.\[[^\[\]]+\]", " ", calc.get("formula"))
        miss = sorted({m for m in re.findall(r"\[([^\[\]]+)\]", body) if m not in known})
        if not miss:
            continue
        nm = (col.get("name") or "").strip("[]")
        label = col.get("caption") or nm
        bucket = blocking if any(nm in u or u in nm for u in used_on_sheets) else idle
        bucket[label] = miss
    return {"blocking": blocking, "idle": idle}


def split_absent_refs(root, live: set):
    """Workbook references to columns outside the extract: what is read and what is only declared."""
    from .edit import mentions

    calc_names = {(c.get("name") or "").strip("[]")
                  for c in root.iter("column") if c.find("calculation") is not None}

    used = set()
    for col in root.iter("column"):
        if col.find("calculation") is not None or col.get("param-domain-type"):
            continue
        name = (col.get("name") or "").strip("[]")
        if not name or name in calc_names or name.startswith(
                (":", "Calculation_", "__tableau", "Parameter ")):
            continue
        used.add(name)

    absent = {n for n in used if n not in live and _bare(n) not in live}
    reading: set = set()
    for el in root.iter():
        par = el.getparent()
        if par is None:
            continue
        if _declaration_only(el.tag, par.tag):
            continue
        blob = " ".join(v for v in el.values() if v)
        if el.text:
            blob += " " + el.text
        reading |= {n for n in absent - reading if mentions(blob, n)}
    return sorted(reading), sorted(absent - reading), len(used)


def stale_extract_refs(book_path: str) -> dict:
    """Whether the workbook references columns missing from its own extract."""
    import zipfile

    from . import safexml

    if not os.path.exists(book_path):
        return {"verdict": f"file not found: {book_path}", "dead": []}
    with zipfile.ZipFile(book_path) as z:
        if not any(n.endswith(".hyper") for n in z.namelist()):
            return {"verdict": "the workbook has no extract; nothing to check",
                    "dead": []}
    live = live_extract_columns(book_path)
    dead, idle, used = split_absent_refs(safexml.from_twbx(book_path), live)
    return {
        "verdict": ("OK: every workbook reference exists in the extract" if not dead else
                    f"DO NOT DELIVER: {len(dead)} references to columns missing from "
                    f"the extract; Tableau will show NOTHING on every sheet"),
        "dead": dead,
        "declared_unread": idle,
        "extract_column_count": len(live),
        "workbook_refs": used,
    }


def packaged_extracts(book_path: str) -> dict:
    """Which .hyper files are packed in the .twbx and which nobody reads."""
    import re
    import zipfile

    if not os.path.exists(book_path) or not book_path.lower().endswith(".twbx"):
        return {"packed": [], "referenced": [], "extra": []}
    with zipfile.ZipFile(book_path) as z:
        names = z.namelist()
        twb = [n for n in names if n.lower().endswith(".twb")]
        xml = z.read(twb[0]).decode("utf-8", "replace") if twb else ""
    packed = [n for n in names if n.lower().endswith(".hyper")]
    refs = {os.path.basename(m.group("path")) for m in
            re.finditer(r"<connection [^>]*class=(?P<q>['\"])hyper(?P=q)[^>]*"
                        r"dbname=(?P<q2>['\"])(?P<path>[^'\"]*)(?P=q2)", xml)}
    refs.discard("")
    return {"packed": packed,
            "referenced": sorted(refs),
            "extra": [n for n in packed if os.path.basename(n) not in refs]}


def drop_packaged_extracts(book_path: str, names: list = None) -> dict:
    """Drop unreachable .hyper files from a .twbx by rebuilding the archive."""
    import shutil
    import zipfile

    from .owner import check_write
    check_write(book_path)

    info = packaged_extracts(book_path)
    doomed = set(names if names is not None else info["extra"])
    if not doomed:
        return {"removed": [], "bytes_freed": 0}
    tmp = book_path + ".repack"
    freed = 0
    with zipfile.ZipFile(book_path) as src, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if item.filename in doomed:
                freed += item.file_size
                continue
            dst.writestr(item, src.read(item.filename))
    shutil.move(tmp, book_path)
    return {"removed": sorted(doomed), "bytes_freed": freed}


def add_extract_source(root, caption: str, hyper_arcname: str, table: str,
                       columns: list, schema: str = "Extract") -> dict:
    """Add a SECOND data source, backed by its own packaged extract."""
    import uuid as _uuid

    dss = root.find("datasources")
    if dss is None:
        return {"added": False, "why": "workbook has no <datasources> element"}
    if any((d.get("caption") or "") == caption for d in dss):
        return {"added": False, "why": f"a source captioned {caption!r} is already there"}

    ds_name = f"federated.{_uuid.uuid4().hex[:20]}"
    conn_name = f"hyper.{_uuid.uuid4()}"

    ds = etree.SubElement(dss, "datasource")
    ds.set("caption", caption)
    ds.set("inline", "true")
    ds.set("name", ds_name)
    ds.set("version", "18.1")

    conn = etree.SubElement(ds, "connection")
    conn.set("class", "federated")
    named = etree.SubElement(conn, "named-connections")
    nc = etree.SubElement(named, "named-connection")
    nc.set("caption", os.path.basename(hyper_arcname))
    nc.set("name", conn_name)
    inner = etree.SubElement(nc, "connection")
    for k, v in (("authentication", "auth-none"), ("author-locale", "en_US"),
                 ("class", "hyper"), ("dbname", hyper_arcname),
                 ("default-settings", "yes"), ("schema", schema),
                 ("sslmode", ""), ("tablename", table), ("username", "")):
        inner.set(k, v)

    rel = etree.SubElement(conn, "relation")
    rel.set("connection", conn_name)
    rel.set("name", table)
    rel.set("table", f"[{schema}].[{table}]")
    rel.set("type", "table")

    recs = etree.SubElement(conn, "metadata-records")
    _REMOTE = {"string": "string", "integer": "integer", "real": "real", "date": "date"}
    for i, col in enumerate(columns):
        rec = etree.SubElement(recs, "metadata-record")
        rec.set("class", "column")
        etree.SubElement(rec, "remote-name").text = col["name"]
        etree.SubElement(rec, "remote-type").text = {
            "string": "129", "integer": "20", "real": "5", "date": "7",
        }.get(col["datatype"], "129")
        etree.SubElement(rec, "local-name").text = f"[{col['name']}]"
        etree.SubElement(rec, "parent-name").text = f"[{table}]"
        etree.SubElement(rec, "remote-alias").text = col["name"]
        etree.SubElement(rec, "ordinal").text = str(i)
        etree.SubElement(rec, "local-type").text = _REMOTE.get(col["datatype"], "string")
        etree.SubElement(rec, "aggregation").text = (
            "Sum" if col.get("role") == "measure" else "Count")
        etree.SubElement(rec, "contains-null").text = "true"

    for col in columns:
        c = etree.SubElement(ds, "column")
        c.set("datatype", col["datatype"])
        c.set("name", f"[{col['name']}]")
        c.set("role", col.get("role", "dimension"))
        c.set("type", "quantitative" if col.get("role") == "measure" else "nominal")
        if col.get("caption"):
            c.set("caption", col["caption"])

    return {"added": True, "datasource": ds_name, "connection": conn_name,
            "table": table, "columns": len(columns)}


def package_file(twbx_path: str, local_path: str, arcname: str) -> dict:
    """Put a file inside a `.twbx` (which is a zip), replacing it if present."""
    import shutil
    import tempfile
    import zipfile

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".twbx").name
    replaced = False
    with zipfile.ZipFile(twbx_path) as src, zipfile.ZipFile(
            tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if item.filename == arcname:
                replaced = True
                continue
            dst.writestr(item, src.read(item.filename))
        dst.write(local_path, arcname)
    shutil.move(tmp, twbx_path)
    return {"packaged": arcname, "replaced": replaced,
            "size_mb": round(os.path.getsize(local_path) / 1024 / 1024, 2)}


def build_hyper_multi(tables: list[dict], out_path: str) -> dict:
    """Build a .hyper with SEVERAL tables, one per data grain."""
    import datetime as _dt
    import sys

    from tableauhyperapi import (
        Connection, CreateMode, HyperProcess, Inserter, SqlType,
        TableDefinition, TableName, Telemetry,
    )

    from . import config                    # noqa: PLC0415 — local by design

    sql_type = {
        "big_int": SqlType.big_int(), "double": SqlType.double(),
        "date": SqlType.date(), "timestamp": SqlType.timestamp(),
        "bool": SqlType.bool(), "text": SqlType.text(),
    }

    def coerce(v, kind):
        if v is None or v == "":
            return None
        if kind == "big_int":
            return int(float(v))
        if kind == "double":
            return float(v)
        if kind == "bool":
            return bool(int(v))
        if kind == "date":
            return _dt.date.fromisoformat(str(v)[:10])
        if kind == "timestamp":
            return _dt.datetime.fromisoformat(str(v).replace("T", " ")[:19])
        return str(v)

    ch = config.clickhouse(read_only=True)
    fetched = [(t, ch.execute(_chsafe.read_only(t["sql"]))) for t in tables]

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)

    counts = {}
    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                      parameters=HYPER_QUIET) as hp:
        with Connection(endpoint=hp.endpoint, database=out_path,
                        create_mode=CreateMode.CREATE_AND_REPLACE) as conn:
            conn.catalog.create_schema("Extract")
            for t, rows in fetched:
                cols = t["columns"]
                tdef = TableDefinition(
                    table_name=TableName("Extract", t["name"]),
                    columns=[TableDefinition.Column(n, sql_type[k]) for n, k in cols],
                )
                conn.catalog.create_table(tdef)
                with Inserter(conn, tdef) as ins:
                    ins.add_rows([[coerce(v, k) for v, (_, k) in zip(r, cols)] for r in rows])
                    ins.execute()
                counts[t["name"]] = len(rows)

    return {"path": out_path, "tables": counts,
            "size_mb": round(os.path.getsize(out_path) / 1024 / 1024, 2)}


_PD_TO_HYPER = {"int64": "big_int", "int32": "big_int", "float64": "double",
                "float32": "double", "bool": "bool",
                "datetime64[ns]": "timestamp", "object": "text"}


def workbook_sql(book_path: str) -> str:
    """Custom SQL of a workbook."""
    from twkit import safexml
    root = (safexml.from_twbx(book_path) if book_path.lower().endswith(".twbx")
            else safexml.from_file(book_path))
    for rel in root.iter("relation"):
        if rel.get("type") == "text" and (rel.text or "").strip():
            return rel.text
    return ""


_TWB_TO_HYPER = {"date": "date", "datetime": "timestamp", "real": "double",
                 "integer": "big_int", "boolean": "bool", "string": "text"}


def workbook_column_types(book_path: str) -> dict:
    """Declared physical column types: name -> Hyper type."""
    import re
    import zipfile
    if book_path.lower().endswith(".twbx"):
        with zipfile.ZipFile(book_path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".twb"))
            xml = z.read(name).decode("utf-8")
    else:
        xml = open(book_path, encoding="utf-8").read()
    out = {}
    for m in re.finditer(r"<column\s([^>]*)>", xml):
        attrs = m.group(1)
        dt = re.search(r"\bdatatype='([a-z]+)'", attrs)
        nm = re.search(r"\bname='\[([^\]]+)\]'", attrs)
        if dt and nm:
            out[nm.group(1)] = _TWB_TO_HYPER.get(dt.group(1), "text")
    return out


CH_TO_HYPER = {
    "Int8": "big_int", "Int16": "big_int", "Int32": "big_int", "Int64": "big_int",
    "Int128": "double", "Int256": "double",
    "UInt8": "big_int", "UInt16": "big_int", "UInt32": "big_int", "UInt64": "big_int",
    "UInt128": "double", "UInt256": "double",
    "Float32": "double", "Float64": "double",
    "Date": "date", "Date32": "date",
    "DateTime": "timestamp", "DateTime64": "timestamp",
    "String": "text", "FixedString": "text", "UUID": "text", "Bool": "bool",
}


def ch_type_to_hyper(ch_type: str) -> str:
    """ClickHouse type -> Hyper type."""
    t = str(ch_type).strip()
    for wrapper in ("Nullable(", "LowCardinality("):
        while t.startswith(wrapper):
            t = t[len(wrapper):-1].strip()
    base = t.split("(", 1)[0]
    if base.startswith("Decimal"):
        return "double"
    if base.startswith("Enum"):
        return "text"
    return CH_TO_HYPER.get(base, "text")


@_chsafe.guard
def build_hyper_from_sql(sql: str, out_path: str, table: str = "Extract",
                         types: dict | None = None, batch: int = 50_000) -> dict:
    """Run a ClickHouse query and stream the result into a .hyper."""
    from tableauhyperapi import (
        Connection, CreateMode, HyperProcess, Inserter, SqlType,
        TableDefinition, TableName, Telemetry,
    )
    from . import config                    # noqa: PLC0415 — local by design

    names, ch_types, batches = config.clickhouse(read_only=True).query_stream(
        _chsafe.read_only(sql), batch=batch)
    if not names or names == [""]:
        raise RuntimeError("the query returned no columns")

    types = types or {}
    sql_type = {"big_int": SqlType.big_int(), "double": SqlType.double(),
                "bool": SqlType.bool(), "timestamp": SqlType.timestamp(),
                "date": SqlType.date(), "text": SqlType.text()}
    kinds = [types.get(n) or ch_type_to_hyper(t) for n, t in zip(names, ch_types)]
    cols = [TableDefinition.Column(n, sql_type[k]) for n, k in zip(names, kinds)]

    import datetime as _dt

    def cast(v, kind):
        if v is None or v == "":
            return None
        if kind == "big_int":
            return int(float(v))
        if kind == "double":
            return float(v)
        if kind == "bool":
            return str(v) not in ("0", "false", "False")
        if kind == "date":
            return _dt.date.fromisoformat(str(v)[:10])
        if kind == "timestamp":
            return _dt.datetime.fromisoformat(str(v).replace(" ", "T")[:26])
        return str(v)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    tdef = TableDefinition(TableName("Extract", table), cols)
    written = 0
    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                      parameters=HYPER_QUIET) as hp:
        with Connection(hp.endpoint, out_path, CreateMode.CREATE_AND_REPLACE) as conn:
            conn.catalog.create_schema("Extract")
            conn.catalog.create_table(tdef)
            with Inserter(conn, tdef) as ins:
                for chunk in batches:
                    ins.add_rows([[cast(v, k) for v, k in zip(row, kinds)] for row in chunk])
                    written += len(chunk)
                ins.execute()
    return {"path": out_path, "rows": written, "columns": len(cols),
            "size_mb": round(os.path.getsize(out_path) / 1024 / 1024, 2)}


TYPE_SNIFF_SHARE = 0.5

NULL_SENTINELS = {"%null%", "%missing%", "%all%", "%other%", "%no-value%"}


def is_null_sentinel(v) -> bool:
    return str(v).strip().lower() in NULL_SENTINELS


def _sniff_csv_types(csv_path: str, sample: int = 2000,
                     delimiter: str = ",") -> tuple[list[str], dict]:
    """Column type inferred from its values (Hyper kinds: big_int, double, date, text)."""
    import csv as _csv
    import datetime as _dt
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rd = _csv.reader(f, delimiter=delimiter)
        header = next(rd, [])
        rows = []
        for i, r in enumerate(rd):
            if i >= sample:
                break
            rows.append(r)
    kinds = {}
    for j, name in enumerate(header):
        vals = [r[j] for r in rows
                if j < len(r) and str(r[j]).strip() != "" and not is_null_sentinel(r[j])]
        if not vals:
            kinds[name] = "text"
            continue

        def _share(fn):
            good = 0
            for v in vals:
                try:
                    fn(v)
                    good += 1
                except Exception:
                    pass
            return good / len(vals)

        if _share(lambda v: int(str(v))) >= TYPE_SNIFF_SHARE:
            kinds[name] = "big_int"
        elif _share(lambda v: float(str(v))) >= TYPE_SNIFF_SHARE:
            kinds[name] = "double"
        elif _share(lambda v: _dt.date.fromisoformat(str(v)[:10])) >= TYPE_SNIFF_SHARE:
            kinds[name] = "date"
        else:
            kinds[name] = "text"
    return header, kinds


_TWB_TO_HYPER = {"string": "text", "date": "date", "datetime": "date",
                 "real": "double", "integer": "big_int", "boolean": "text"}


def declared_column_types(root) -> dict:
    """Column type declared in the workbook: bare name -> Hyper type."""
    out = {}
    for col in root.iter("column"):
        name = (col.get("name") or "").strip("[]")
        dt = (col.get("datatype") or "").strip().lower()
        if name and dt in _TWB_TO_HYPER and not name.startswith("Calculation_"):
            out.setdefault(name, _TWB_TO_HYPER[dt])
    return out


def build_hyper_from_csv(csv_path: str, out_path: str, table: str = "Extract",
                         types: dict | None = None) -> dict:
    """CSV -> .hyper, so a CSV workbook is checked by the same channels as a table workbook."""
    import csv as _csv
    import datetime as _dt

    from tableauhyperapi import (
        Connection, CreateMode, HyperProcess, Inserter, SqlType,
        TableDefinition, TableName, Telemetry,
    )

    header, kinds = _sniff_csv_types(csv_path)
    for name, kind in (types or {}).items():
        if name in kinds and kind in ("big_int", "double", "date", "text"):
            kinds[name] = kind
    sql_type = {"big_int": SqlType.big_int(), "double": SqlType.double(),
                "date": SqlType.date(), "text": SqlType.text()}
    cols = [TableDefinition.Column(n, sql_type[kinds[n]]) for n in header]

    coerced = {"count": 0}

    def cast(v, kind):
        s = str(v).strip()
        if s == "" or is_null_sentinel(s):
            return None
        try:
            if kind == "big_int":
                return int(float(s))
            if kind == "double":
                return float(s)
            if kind == "date":
                return _dt.date.fromisoformat(s[:10])
        except (TypeError, ValueError):
            coerced["count"] += 1
            return None
        return s

    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rd = _csv.reader(f)
        next(rd, None)
        for r in rd:
            r = list(r) + [""] * (len(header) - len(r))
            rows.append([cast(r[i], kinds[n]) for i, n in enumerate(header)])

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    tdef = TableDefinition(TableName("Extract", table), cols)
    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                      parameters=HYPER_QUIET) as hp:
        with Connection(hp.endpoint, out_path, CreateMode.CREATE_AND_REPLACE) as conn:
            conn.catalog.create_schema("Extract")
            conn.catalog.create_table(tdef)
            with Inserter(conn, tdef) as ins:
                ins.add_rows(rows)
                ins.execute()
    return {"path": out_path, "rows": len(rows), "columns": len(cols),
            "types": kinds, "coerced": coerced["count"],
            "size_mb": round(os.path.getsize(out_path) / 1024 / 1024, 2)}


def to_extract(book_path: str, out_path: str = "", table: str = "Extract") -> dict:
    """Switch a workbook from a live query to a packaged .hyper."""
    import re
    import shutil
    import zipfile

    sql = workbook_sql(book_path)
    if not sql:
        return {"ok": False, "why": "the workbook has no Custom SQL; nothing to materialize"}
    out_path = out_path or book_path.replace(".twbx", " (extract).twbx")
    from .owner import check_write
    check_write(out_path)
    stem = os.path.splitext(os.path.basename(out_path))[0]
    hyper_rel = f"Data/{stem}.hyper"
    hyper_abs = os.path.join(tempfile.mkdtemp(prefix="twkit_hyper_"), f"{stem}.hyper")
    built = build_hyper_from_sql(sql, hyper_abs, table,
                                 types=workbook_column_types(book_path))

    with zipfile.ZipFile(book_path) as z:
        items = [(i.filename, z.read(i.filename)) for i in z.infolist()]
    twb = next(n for n, _ in items if n.lower().endswith(".twb"))
    xml = dict(items)[twb].decode("utf-8")

    conn_name = "hyper.twkit_extract"
    named = (f"<named-connection caption='{stem}' name='{conn_name}'>"
             f"<connection authentication='auth-none' author-locale='en_US' class='hyper' "
             f"dbname='{hyper_rel}' default-settings='yes' sslmode='' "
             f"workgroup-auth-mode='as-is' /></named-connection>")
    xml = re.sub(r"<named-connection\b.*?</named-connection>", named, xml, flags=re.S)
    xml = re.sub(r"<relation\b[^>]*type=['\"]text['\"]\s*>.*?</relation>",
                 f"<relation connection='{conn_name}' name='Extract' "
                 f"table='[Extract].[{table}]' type='table' />", xml, flags=re.S)
    xml = re.sub(r"<parent-name>\[Custom SQL Query\d*\]</parent-name>",
                 f"<parent-name>[{table}]</parent-name>", xml)
    xml = re.sub(r'value="\[Custom SQL Query\d*\]\.', f'value="[{table}].', xml)
    xml = re.sub(r"value='\[Custom SQL Query\d*\]\.", f"value='[{table}].", xml)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in items:
            if name.lower().endswith(".twb"):
                z.writestr(name, xml.encode("utf-8"))
            elif not name.lower().endswith(".hyper"):
                z.writestr(name, data)
        z.write(hyper_abs, hyper_rel)
    shutil.rmtree(os.path.dirname(hyper_abs), ignore_errors=True)
    return {"ok": True, "file": out_path, "row_count": built["rows"],
            "column_count": built["columns"],
            "size_mb": round(os.path.getsize(out_path) / 1024 / 1024, 2)}
