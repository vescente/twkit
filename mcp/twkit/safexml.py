"""The single place XML is parsed: workbooks come from outside, so the parser is strict."""
from __future__ import annotations

import io

from lxml import etree

_PARSER_ARGS = {
    "resolve_entities": False,
    "no_network": True,
    "load_dtd": False,
    "huge_tree": False,
    "recover": False,
}


def parser() -> etree.XMLParser:
    """Strict parser."""
    return etree.XMLParser(**_PARSER_ARGS)


def from_bytes(raw: bytes):
    """Parse XML from bytes (as the workbook sits inside a .twbx)."""
    return etree.parse(io.BytesIO(raw), parser()).getroot()


def from_file(path: str):
    with open(path, "rb") as f:
        return from_bytes(f.read())


def from_twbx(path: str):
    """Workbook root from a .twbx or .twb."""
    if path.lower().endswith(".twbx"):
        import zipfile
        with zipfile.ZipFile(path) as z:
            inner = [n for n in z.namelist() if n.lower().endswith(".twb")]
            if not inner:
                raise ValueError(f"no .twb inside {path}")
            return from_bytes(z.read(inner[0]))
    return from_file(path)

def to_twbx(src: str, root, dst: str) -> str:
    """Write the edited tree back into a .twbx, copying every other member as is."""
    from .owner import check_write
    check_write(dst)
    import os
    import shutil
    import zipfile

    if not dst.lower().endswith(".twbx"):
        raise ValueError(f"only .twbx can be written, not {os.path.splitext(dst)[1]}")
    tmp = dst + ".tmp"
    body = serialize(root)
    with zipfile.ZipFile(src) as z, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        names = z.namelist()
        inner = [n for n in names if n.lower().endswith(".twb")]
        if not inner:
            os.unlink(tmp)
            raise ValueError(f"no .twb inside {src}")
        for n in names:
            out.writestr(n, body if n == inner[0] else z.read(n))
    shutil.move(tmp, dst)
    try:
        from .preview import mark_written
        mark_written(dst)
    except Exception:
        pass
    return dst


def serialize(root) -> bytes:
    """The workbook as Tableau writes it: declaration, comments on their own lines, then the tree."""
    tree = root.getroottree()
    body = etree.tostring(tree if tree is not None else root,
                          xml_declaration=True, encoding="utf-8", standalone=True)
    tag = b"<" + root.tag.encode() if isinstance(root.tag, str) else b"<workbook"
    return body.replace(b"--><!--", b"-->\n<!--").replace(b"-->" + tag, b"-->\n" + tag)


def write_twbx(root, dst: str, twb_name: str, members: dict | None = None) -> str:
    """A new .twbx from the tree and packaged files.

    `members`: arcname -> bytes, a local path, or `(zip_path, member)` copied by streaming.
    """
    from .owner import check_write
    check_write(dst)
    import os
    import shutil
    import zipfile

    if not dst.lower().endswith(".twbx"):
        raise ValueError(f"only .twbx can be written, not {os.path.splitext(dst)[1]}")
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    tmp = dst + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr(twb_name, serialize(root))
        for arc, data in (members or {}).items():
            if isinstance(data, (bytes, bytearray)):
                out.writestr(arc, bytes(data))
            elif isinstance(data, tuple):
                with zipfile.ZipFile(data[0]) as src, src.open(data[1]) as fin, \
                        out.open(arc, "w", force_zip64=True) as fout:
                    shutil.copyfileobj(fin, fout, 1 << 20)
            else:
                out.write(str(data), arc)
    shutil.move(tmp, dst)
    try:
        from .preview import mark_written
        mark_written(dst)
    except Exception:
        pass
    return dst
