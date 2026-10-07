import os
import zipfile

import pytest

from twkit import safexml


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_external_entity_does_not_read_local_file(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET", encoding="utf-8")
    path = _write(tmp_path, "xxe.twb",
                  "<?xml version='1.0' encoding='utf-8' ?>\n"
                  f'<!DOCTYPE workbook [<!ENTITY xxe SYSTEM "file://{secret}">]>\n'
                  '<workbook><worksheets><worksheet name="&xxe;"/></worksheets></workbook>')
    try:
        root = safexml.from_file(path)
    except Exception:
        return
    names = [w.get("name") or "" for w in root.iter("worksheet")]
    assert not any("SECRET" in n for n in names)


def test_entity_bomb_does_not_blow_memory(tmp_path):
    ents = "\n".join(f'  <!ENTITY e{i} "' + f"&e{i - 1};" * 6 + '">' for i in range(1, 10))
    path = _write(tmp_path, "bomb.twb",
                  "<?xml version='1.0' encoding='utf-8' ?>\n"
                  '<!DOCTYPE workbook [\n  <!ENTITY e0 "AAAAAAAAAA">\n' + ents + "\n]>\n"
                  '<workbook><worksheets><worksheet name="&e9;"/></worksheets></workbook>')
    try:
        root = safexml.from_file(path)
    except Exception:
        return
    for w in root.iter("worksheet"):
        assert len(w.get("name") or "") < 100_000


def test_external_dtd_not_fetched(tmp_path):
    import time
    path = _write(tmp_path, "net.twb",
                  "<?xml version='1.0' encoding='utf-8' ?>\n"
                  '<!DOCTYPE workbook SYSTEM "http://127.0.0.1:9/evil.dtd">\n'
                  "<workbook><worksheets/></workbook>")
    t = time.time()
    try:
        safexml.from_file(path)
    except Exception:
        pass
    assert time.time() - t < 2.0


def test_normal_book_reads(tmp_path):
    path = _write(tmp_path, "ok.twb",
                  "<?xml version='1.0' encoding='utf-8' ?>\n\n"
                  "<!-- build 2026.1 -->\n"
                  '<workbook><worksheets><worksheet name="sheet"/></worksheets></workbook>')
    root = safexml.from_file(path)
    assert [w.get("name") for w in root.iter("worksheet")] == ["sheet"]


def test_twbx_read_like_twb(tmp_path):
    twbx = tmp_path / "k.twbx"
    with zipfile.ZipFile(twbx, "w") as z:
        z.writestr("k.twb", "<?xml version='1.0' encoding='utf-8' ?>\n\n"
                            '<workbook><worksheets><worksheet name="sheet"/></worksheets></workbook>')
    root = safexml.from_twbx(str(twbx))
    assert [w.get("name") for w in root.iter("worksheet")] == ["sheet"]


def test_archive_without_workbook_rejected(tmp_path):
    twbx = tmp_path / "empty.twbx"
    with zipfile.ZipFile(twbx, "w") as z:
        z.writestr("readme.txt", "not a book")
    with pytest.raises(ValueError):
        safexml.from_twbx(str(twbx))


def test_parsing_only_via_safexml():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "mcp" / "twkit"
    offenders = []
    for f in root.rglob("*.py"):
        if f.name == "safexml.py":
            continue
        src = f.read_text(encoding="utf-8")
        for marker in ("etree.parse(", "ET.parse(", "ET.fromstring(", "etree.fromstring("):
            if marker in src:
                offenders.append(f"{f.name}: {marker}")
    assert not offenders, "XML parsed bypassing safexml: " + ", ".join(offenders)


def test_build_comment_survives_rebuild(tmp_path):
    import zipfile

    from twkit import safexml as SX

    raw = (b"<?xml version='1.0' encoding='utf-8' ?>\n\n"
           b"<!-- build 20253.25.1210.1815 -->\n"
           b"<workbook version='18.1'><dashboards/></workbook>")
    src = tmp_path / "in.twbx"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("book.twb", raw)

    root = SX.from_twbx(str(src))
    dst = tmp_path / "out.twbx"
    SX.to_twbx(str(src), root, str(dst))

    with zipfile.ZipFile(dst) as z:
        out = z.read("book.twb").decode()
    assert "build 20253.25.1210.1815" in out, out[:200]
    assert "--><workbook" not in out, out[:200]
