"""Data source connections of a built workbook: a CSV file, a Hyper extract, a MySQL table or query."""
from __future__ import annotations

import copy
import csv as _csv
import os
import re
import uuid

from lxml import etree

from . import edit as ED
from . import order as ORD

DATATYPES = ("string", "integer", "real", "date", "datetime", "boolean")
_KIND_TYPE = {"big_int": "integer", "double": "real", "date": "date", "text": "string"}
_GEO_HINT = re.compile(r"(?i)(^|_)(country|state|city|region)($|_)")
_CAPABILITY = (("character-set", '"UTF-8"'), ("collation", '"en_US"'), ("field-delimiter", None),
               ("header-row", '"true"'), ("locale", '"en_US"'), ("single-char", '""'))


def safe_source(path: str, kinds: tuple) -> str:
    """`path` if it may go into a workbook: a data or layout file, not a secret.

    The extension must be one of `kinds`, no part of the path may be a hidden folder
    (`~/.ssh`, `~/.aws`, ...), and a text file must be text. A packaged file leaves the machine
    with the workbook, so this is the gate against exfiltration.
    """
    real = os.path.realpath(path)
    if not real.lower().endswith(kinds):
        raise PermissionError(f"refused: {os.path.basename(path)!r} is not a {'/'.join(kinds)} file")
    if any(part.startswith(".") and part not in (".", "..")
           for part in real.split(os.sep)[:-1]):
        raise PermissionError(f"refused: {path!r} sits in a hidden folder")
    if os.path.exists(real) and real.lower().endswith((".csv", ".tsv", ".txt")):
        with open(real, "rb") as f:
            if b"\0" in f.read(8192):
                raise PermissionError(f"refused: {path!r} is not text")
    return real


def _hex() -> str:
    return uuid.uuid4().hex.upper()


def _main(book, caption: str):
    """The main data source, emptied of its old connection; calculations stay."""
    from .book import VERSION, tableau_id
    ds = book.datasource
    if ds is None:
        ds = etree.SubElement(book.datasources, "datasource")
        ds.set("caption", caption)
        ds.set("inline", "true")
        ds.set("name", f"federated.{tableau_id()}")
        ds.set("version", VERSION)
    else:
        ds.set("caption", caption)
        for tag in ("connection", "object-graph", "extract", "semantic-values"):
            for el in ds.findall(tag):
                ds.remove(el)
        for col in list(ds.findall("column")):
            if col.find("calculation") is None and not (col.get("name") or "").startswith("[:"):
                ds.remove(col)
    conn = etree.Element("connection")
    conn.set("class", "federated")
    ds.insert(0, conn)
    if ds.find("aliases") is None:
        ED.insert_in_order(ds, etree.Element("aliases", enabled="yes"), list(ORD.DATASOURCE_ORDER))
    if ds.find("layout") is None:
        lay = etree.Element("layout")
        for k, v in (("dim-ordering", "alphabetic"), ("measure-ordering", "alphabetic"),
                     ("show-structure", "true")):
            lay.set(k, v)
        ED.insert_in_order(ds, lay, list(ORD.DATASOURCE_ORDER))
    return ds, conn


def _named(conn, cls: str, caption: str, attrs: list) -> str:
    from .book import tableau_id
    name = f"{cls}.{tableau_id()}"
    nc = etree.SubElement(etree.SubElement(conn, "named-connections"), "named-connection")
    nc.set("caption", caption)
    nc.set("name", name)
    inner = etree.SubElement(nc, "connection")
    for k, v in [("class", cls)] + attrs:
        inner.set(k, str(v))
    return name


def _relation(parent, connection: str, name: str, table: str, kind: str = "table", sql: str = ""):
    rel = etree.SubElement(parent, "relation")
    rel.set("connection", connection)
    rel.set("name", name)
    if kind == "table":
        rel.set("table", table)
    rel.set("type", kind)
    if sql:
        rel.text = sql
    return rel


def _record(recs, field: dict, key: str, parent: str, ordinal: int, object_id: str):
    dt = field["datatype"]
    rec = etree.SubElement(recs, "metadata-record")
    rec.set("class", "column")
    for tag, text in (("remote-name", field["name"]), ("remote-type", ED._REMOTE_TYPE.get(dt, "129")),
                      ("local-name", f"[{key}]"), ("parent-name", f"[{parent}]"),
                      ("remote-alias", field["name"]), ("ordinal", str(ordinal)),
                      ("local-type", dt), ("aggregation", ED._AGG.get(dt, "Count")),
                      ("contains-null", "true"), ("object-id", f"[{object_id}]")):
        etree.SubElement(rec, tag).text = text


def _declare(ds, key: str, field: dict) -> None:
    """The field's `<column>`: role and type as given, or as its datatype implies."""
    if field["datatype"] not in DATATYPES:
        raise ValueError(f"field {key!r}: datatype {field['datatype']!r} is not one of "
                         f"{', '.join(DATATYPES)}")
    role, typ = ED._ROLE_BY_TYPE.get(field["datatype"], ("dimension", "nominal"))
    role = field.get("role") or role
    if field.get("field_type") or field.get("type"):
        typ = field.get("field_type") or field.get("type")
    elif role == "dimension" and typ == "quantitative":
        typ = "ordinal"
    elif role == "measure":
        typ = "quantitative"
    for old in [c for c in ds.findall("column") if c.get("name") == f"[{key}]"]:
        ds.remove(old)
    col = etree.Element("column")
    if field.get("caption"):
        col.set("caption", field["caption"])
    col.set("datatype", field["datatype"])
    col.set("name", f"[{key}]")
    col.set("role", role)
    col.set("type", typ)
    geo = field.get("semantic_role")
    if geo is None and field["datatype"] == "string" and _GEO_HINT.search(key):
        from .schema import infer_geo_role
        geo = infer_geo_role(key, "string")
    if geo:
        col.set("semantic-role", geo)
    ED.insert_in_order(ds, col, list(ORD.DATASOURCE_ORDER))


def _object(ds, caption: str, relation) -> str:
    og = ds.find("object-graph")
    if og is None:
        og = etree.Element("object-graph")
        ED.insert_in_order(ds, og, list(ORD.DATASOURCE_ORDER))
    objs = og.find("objects")
    if objs is None:
        objs = etree.SubElement(og, "objects")
    oid = f"{caption}_{_hex()}"
    obj = etree.SubElement(objs, "object")
    obj.set("caption", caption)
    obj.set("id", oid)
    props = etree.SubElement(obj, "properties")
    props.set("context", "")
    props.append(copy.deepcopy(relation))
    tcol = etree.Element("column")
    tcol.set("caption", caption)
    tcol.set("datatype", "table")
    tcol.set("name", f"[__tableau_internal_object_id__].[{oid}]")
    tcol.set("role", "measure")
    tcol.set("type", "quantitative")
    ED.insert_in_order(ds, tcol, list(ORD.DATASOURCE_ORDER))
    return oid


def _relationship(ds, first: str, second: str, key1: str, key2: str) -> None:
    og = ds.find("object-graph")
    rels = og.find("relationships")
    if rels is None:
        rels = etree.SubElement(og, "relationships")
    r = etree.SubElement(rels, "relationship")
    eq = etree.SubElement(r, "expression")
    eq.set("op", "=")
    etree.SubElement(eq, "expression").set("op", f"[{key1}]")
    etree.SubElement(eq, "expression").set("op", f"[{key2}]")
    etree.SubElement(r, "first-end-point").set("object-id", first)
    etree.SubElement(r, "second-end-point").set("object-id", second)


def _sniff(path: str, delimiter: str) -> tuple[str, list]:
    from .extract import _sniff_csv_types
    if not delimiter:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            head = f.read(8192)
        try:
            delimiter = _csv.Sniffer().sniff(head, delimiters=",;\t|").delimiter
        except _csv.Error:
            delimiter = ","
    names, kinds = _sniff_csv_types(path, delimiter=delimiter)
    return delimiter, [{"name": n, "datatype": _KIND_TYPE.get(kinds.get(n), "string")}
                       for n in names]


def csv(book, filepath: str, delimiter: str = "", charset: str = "utf-8-sig",
        fields: list | None = None) -> str:
    """A packaged CSV file as the main data source."""
    path = safe_source(filepath, (".csv", ".tsv", ".txt"))
    fname = os.path.basename(path)
    stem = os.path.splitext(fname)[0]
    if fields is None or not delimiter:
        sniffed_delim, sniffed = _sniff(path, delimiter) if os.path.exists(path) else (",", [])
        delimiter = delimiter or sniffed_delim
        fields = fields if fields is not None else sniffed
    if not fields:
        raise ValueError(f"no fields: {path} is missing or empty and no `fields` were given")
    ds, conn = _main(book, stem)
    cname = _named(conn, "textscan", stem,
                   [("directory", ""), ("filename", fname), ("password", ""), ("server", "")])
    rel = _relation(conn, cname, fname, f"[{stem}#csv]")
    cols = etree.SubElement(rel, "columns")
    for k, v in (("character-set", "UTF-8"), ("header", "yes"), ("locale", "en_US"),
                 ("separator", delimiter)):
        cols.set(k, v)
    for i, f in enumerate(fields):
        c = etree.SubElement(cols, "column")
        c.set("datatype", f["datatype"])
        c.set("name", f["name"])
        c.set("ordinal", str(i))
    cmap = etree.SubElement(conn, "cols")
    for f in fields:
        m = etree.SubElement(cmap, "map")
        m.set("key", f"[{f['name']}]")
        m.set("value", f"[{fname}].[{f['name']}]")
    oid = _object(ds, fname, rel)
    recs = etree.SubElement(conn, "metadata-records")
    cap = etree.SubElement(recs, "metadata-record")
    cap.set("class", "capability")
    for tag, text in (("remote-name", None), ("remote-type", "0"), ("parent-name", f"[{fname}]"),
                      ("remote-alias", None), ("aggregation", "Count"), ("contains-null", "true")):
        etree.SubElement(cap, tag).text = text
    attrs = etree.SubElement(cap, "attributes")
    for name, value in _CAPABILITY:
        a = etree.SubElement(attrs, "attribute")
        a.set("datatype", "string")
        a.set("name", name)
        a.text = value if value is not None else f'"{delimiter}"'
    for i, f in enumerate(fields):
        _record(recs, f, f["name"], fname, i, oid)
        _declare(ds, f["name"], f)
    if os.path.exists(path):
        book.members[fname] = path
    return f"Connected CSV {fname}: {len(fields)} fields"


_DATE_HINT = re.compile(r"(?i)(date|day|week|month|year|_at$|_dt$|time)")
_NUM_HINT = re.compile(r"(?i)(sum|count|cnt|amount|value|total|num|qty|rate|pct|share|avg|ltv|"
                       r"ngr|ggr|revenue|cost|price|_n$)")


def _guess(name: str) -> str:
    if _DATE_HINT.search(name):
        return "date"
    if _NUM_HINT.search(name):
        return "real"
    return "string"


def _hyper_tables(path: str, specs: list) -> list:
    """`[{name, fields}]`: types from the file when it exists, else guessed from names."""
    out = []
    for spec in specs:
        known = {}
        if os.path.exists(path):
            from .extract import schema_from_hyper
            try:
                known = {f["name"]: f for f in schema_from_hyper(path, spec["name"])}
            except Exception:                 # noqa: BLE001 — a table may be absent
                known = {}
        names = spec.get("columns") or list(known)
        schema = "Extract"
        if os.path.exists(path):
            from .extract import hyper_schema
            try:
                schema = hyper_schema(path, spec["name"])
            except Exception:                 # noqa: BLE001 — Tableau's default then
                schema = "Extract"
        out.append({"name": spec["name"], "schema": schema,
                    "fields": [known.get(n) or {"name": n, "datatype": _guess(n)} for n in names]})
    return out


def hyper(book, filepath: str, table_name: str = "Extract", tables: list | None = None) -> str:
    """A packaged .hyper as the main data source; several tables are related on a shared column."""
    path = safe_source(filepath, (".hyper",))
    fname = os.path.basename(path)
    arc = f"Data/Extracts/{fname}"
    specs = tables or [{"name": table_name}]
    tabs = _hyper_tables(path, specs)
    ds, conn = _main(book, os.path.splitext(fname)[0])
    cname = _named(conn, "hyper", fname,
                   [("authentication", "auth-none"), ("author-locale", "en_US"),
                    ("dbname", arc), ("default-settings", "yes"), ("schema", tabs[0]["schema"]),
                    ("sslmode", ""), ("tablename", tabs[0]["name"]), ("username", "")])
    holder = conn if len(tabs) == 1 else etree.SubElement(conn, "relation", type="collection")
    rels = [_relation(holder, cname, t["name"], f"[{t['schema']}].[{t['name']}]") for t in tabs]
    cmap = etree.SubElement(conn, "cols")
    recs = etree.SubElement(conn, "metadata-records")
    seen, oids, keys = set(), [], []
    for t, rel in zip(tabs, rels):
        oid = _object(ds, t["name"], rel)
        oids.append(oid)
        tkeys = {}
        for i, f in enumerate(t["fields"]):
            key = f["name"] if f["name"] not in seen else f"{f['name']} ({t['name']})"
            seen.add(f["name"])
            tkeys[f["name"]] = key
            m = etree.SubElement(cmap, "map")
            m.set("key", f"[{key}]")
            m.set("value", f"[{t['name']}].[{f['name']}]")
            _record(recs, f, key, t["name"], i, oid)
            _declare(ds, key, f)
        keys.append(tkeys)
    for k in range(1, len(tabs)):
        shared = next((n for n in keys[0] if n in keys[k]), None)
        if shared:
            _relationship(ds, oids[0], oids[k], keys[0][shared], keys[k][shared])
    if os.path.exists(path):
        book.members[arc] = path
    return f"Connected extract {fname}: {', '.join(t['name'] for t in tabs)}"


def mysql(book, server: str, dbname: str, username: str, table_name: str, port: str = "3306",
          odbc_extras: str = "", sslmode: str = "", custom_sql: str = "") -> str:
    """A live MySQL-protocol connection to a table, or to Custom SQL when `custom_sql` is given."""
    ds, conn = _main(book, table_name if not custom_sql else "Custom SQL Query")
    attrs = [("dbname", dbname), ("odbc-native-protocol", ""), ("one-time-sql", ""),
             ("port", port), ("server", server), ("server-oauth", ""), ("source-charset", ""),
             ("username", username), ("workgroup-auth-mode", "prompt")]
    if odbc_extras:
        attrs.append(("odbc-connect-string-extras", odbc_extras))
    if sslmode:
        attrs.append(("sslmode", sslmode))
    cname = _named(conn, "mysql", server, attrs)
    if custom_sql:
        rel = _relation(conn, cname, "Custom SQL Query", "", kind="text", sql=custom_sql)
    else:
        rel = _relation(conn, cname, table_name, f"[{table_name}]")
    etree.SubElement(conn, "metadata-records")
    _object(ds, rel.get("name"), rel)
    return f"Connected {server}/{dbname}: {rel.get('name')}"


def register(book, fields: list) -> int:
    """Declare a live source's fields: metadata records and `<column>`s, as Tableau caches them."""
    ds = book.datasource
    conn = ds.find("connection") if ds is not None else None
    if conn is None:
        raise ValueError("connect a data source first")
    rel = conn.find("relation")
    parent = rel.get("name") if rel is not None else "Custom SQL Query"
    obj = ds.find("object-graph/objects/object")
    oid = obj.get("id") if obj is not None else ""
    recs = conn.find("metadata-records")
    if recs is None:
        recs = etree.SubElement(conn, "metadata-records")
    known = {r.findtext("remote-name") for r in recs.findall("metadata-record")}
    n = 0
    for i, f in enumerate(fields):
        if f["name"] not in known:
            _record(recs, f, f["name"], parent, len(known) + i, oid)
        _declare(ds, f["name"], f)
        n += 1
    return n
