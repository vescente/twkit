"""Validation against the Tableau document schema (XSD) in `vendor/tableau-document-schemas`."""
from __future__ import annotations

import glob
import os
import tempfile
from functools import lru_cache

from lxml import etree

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "vendor",
                          "tableau-document-schemas", "schemas")
_XS = "http://www.w3.org/2001/XMLSchema"
# The schema imports two namespaces without a location; these stand in for them.
_STUBS = {
    "http://www.tableausoftware.com/xml/user": (
        f'<xs:schema xmlns:xs="{_XS}" targetNamespace="http://www.tableausoftware.com/xml/user">'
        '<xs:attributeGroup name="UserAttributes-AG">'
        '<xs:anyAttribute namespace="##any" processContents="lax"/></xs:attributeGroup>'
        '</xs:schema>'),
    "http://www.w3.org/XML/1998/namespace": (
        f'<xs:schema xmlns:xs="{_XS}" targetNamespace="http://www.w3.org/XML/1998/namespace">'
        '<xs:attribute name="base" type="xs:anyURI"/>'
        '<xs:attribute name="lang" type="xs:language"/>'
        '<xs:attribute name="space" type="xs:NCName"/>'
        '<xs:attribute name="id" type="xs:ID"/></xs:schema>'),
}


@lru_cache(maxsize=1)
def _schema():
    files = sorted(glob.glob(os.path.join(SCHEMA_DIR, "*", "twb_*.xsd")))
    if not files:
        return None, ""
    from .safexml import from_file
    path = files[-1]
    doc = from_file(path)
    stub_dir = tempfile.mkdtemp(prefix="twkit_xsd_")
    for i, imp in enumerate(doc.iter(f"{{{_XS}}}import")):
        body = _STUBS.get(imp.get("namespace") or "")
        if body and not imp.get("schemaLocation"):
            stub = os.path.join(stub_dir, f"ns{i}.xsd")
            with open(stub, "w", encoding="utf-8") as f:
                f.write(body)
            imp.set("schemaLocation", "file://" + stub)
    return etree.XMLSchema(doc), os.path.basename(path)


def validate(root) -> dict:
    """`{available, ok, errors, schema}`; the schema is newer than some files Tableau writes."""
    schema, name = _schema()
    if schema is None:
        return {"available": False, "ok": True, "errors": [], "schema": ""}
    ok = schema.validate(etree.ElementTree(root))
    errors = [f"line {e.line}: {e.message}" for e in schema.error_log]
    return {"available": True, "ok": bool(ok), "errors": errors, "schema": name}
