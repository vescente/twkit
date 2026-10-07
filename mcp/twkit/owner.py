"""Editing someone else's workbook without reverting their work."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil


class Refused(Exception):
    """Diff-guard refusal: the owner's file was NOT touched."""


SNAP_DIR_NAME = "_ai"
MANIFEST = "manifest.json"


WORKBOOKS_DIR_NAME = "Workbooks"


def workbooks_root(book_path: str) -> str:
    """Nearest ancestor folder named `Workbooks` (Tableau repository); else the book's folder."""
    d = os.path.dirname(os.path.abspath(book_path))
    probe = d
    while True:
        if os.path.basename(probe) == WORKBOOKS_DIR_NAME:
            return probe
        up = os.path.dirname(probe)
        if up == probe:
            return d
        probe = up


def book_key(book_path: str) -> str:
    """Book path relative to the workbooks root, `/`-separated: manifest key and snapshot folder."""
    rel = os.path.relpath(os.path.abspath(book_path), workbooks_root(book_path))
    return rel.replace(os.sep, "/")


def store_dir(book_path: str) -> str:
    return os.path.join(workbooks_root(book_path), SNAP_DIR_NAME)


def _snap_dir(book_path: str) -> str:
    return os.path.join(store_dir(book_path), *os.path.splitext(book_key(book_path))[0].split("/"))


def manifest_path(book_path: str) -> str:
    return os.path.join(store_dir(book_path), MANIFEST)


def md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest(book_path: str) -> dict:
    p = manifest_path(book_path)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save_manifest(book_path: str, data: dict) -> None:
    os.makedirs(store_dir(book_path), exist_ok=True)
    with open(manifest_path(book_path), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)


def snapshot(book_path: str, tag: str = "") -> str:
    """Copy the owner's current file as a rollback point; returns the snapshot path."""
    stamp = _dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out_dir = _snap_dir(book_path)
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, f"{stamp}-{md5(book_path)[:8]}{'-' + tag if tag else ''}.twbx")
    if not os.path.exists(dst):
        shutil.copy2(book_path, dst)
    return dst


KEEP_SNAPSHOTS = 10
NEVER_PRUNE = ("original", "keep")


def prune(book_path: str, keep: int = KEEP_SNAPSHOTS, dry_run: bool = False) -> dict:
    """Keep the latest `keep` snapshots; files with `keep` or `original` in the name are never deleted."""
    d = _snap_dir(book_path)
    if not os.path.isdir(d):
        return {"snapshot_count": 0, "deleted": []}
    snaps = sorted(f for f in os.listdir(d) if f.endswith(".twbx"))
    protected = [f for f in snaps if any(m in f.lower() for m in NEVER_PRUNE)]
    rest = [f for f in snaps if f not in protected]
    doomed = rest[:-keep] if keep > 0 else rest
    for f in doomed:
        if not dry_run:
            os.remove(os.path.join(d, f))
    return {"snapshot_count": len(snaps), "protected": protected,
            "deleted": doomed, "kept": len(snaps) - len(doomed)}


def last_install(book_path: str) -> dict | None:
    """Manifest record of the last install: md5, time, deliberate removals."""
    return _load_manifest(book_path).get(book_key(book_path))


def protected(path: str) -> str:
    """Why `path` is the owner's workbook that only `install` may write, or "".

    A book we installed (it has a manifest record) is always theirs; otherwise a folder listed in
    `[guard] protected` of `~/.twkit/config.toml`, minus its `[guard] writable` subfolders."""
    from . import config
    p = os.path.realpath(os.path.expanduser(path))
    if os.path.exists(p) and last_install(p):
        return "installed by owner_install"
    guard = config._section("guard")
    norm = lambda x: os.path.realpath(os.path.expanduser(x))
    inside = lambda r: p == r or p.startswith(r.rstrip(os.sep) + os.sep)
    if any(inside(norm(r)) for r in guard.get("writable") or ()):
        return ""
    hit = next((r for r in guard.get("protected") or () if inside(norm(r))), None)
    return f"inside the protected folder {hit}" if hit else ""


def check_write(path: str) -> None:
    """Refuse a direct write to the owner's workbook: it goes through `install` (snapshot + diff guard)."""
    why = protected(path)
    if why:
        raise PermissionError(f"{path} is the owner's workbook ({why}): write it through owner_install, "
                              f"which snapshots it and refuses silent losses")


def owner_touched(book_path: str) -> bool:
    """Whether the owner edited the book after our last install (no record counts as edited)."""
    rec = last_install(book_path)
    if not rec or not os.path.exists(book_path):
        return True
    return md5(book_path) != rec.get("md5")


def inventory(root) -> dict:
    """Names of sheets, pages, calcs, parameters, fields and zones (names, not counts)."""
    def named(tag):
        return sorted({e.get("name") for e in root.iter(tag) if e.get("name")})

    calcs, params, fields = set(), set(), set()
    for col in root.iter("column"):
        nm = (col.get("name") or "").strip("[]")
        if not nm:
            continue
        if col.get("param-domain-type"):
            params.add(col.get("caption") or nm)
        elif col.find("calculation") is not None:
            calcs.add(col.get("caption") or nm)
        elif not nm.startswith((":", "__tableau")):
            fields.add(nm)

    zones = set()
    for dash in root.iter("dashboard"):
        for z in dash.iter("zone"):
            key = z.get("name") or z.get("param")
            if key:
                zones.add(f"{dash.get('name')}::{key}")

    return {"sheets": named("worksheet"), "pages": named("dashboard"),
            "calculations": sorted(calcs), "parameters": sorted(params),
            "fields": sorted(fields), "zones": sorted(zones)}


def apply_renames(before: dict, renames: dict) -> dict:
    """Apply `renames` to the "before" inventory, including inside composite `page::zone` keys."""
    if not renames:
        return before
    def fix(x: str) -> str:
        if x in renames:
            return renames[x]
        head, sep, tail = x.partition("::")
        return renames[head] + sep + tail if sep and head in renames else x
    return {k: sorted({fix(x) for x in v}) for k, v in before.items()}


def regressions(before: dict, after: dict, allowed=(), renames: dict = None) -> dict:
    """Inventory items that disappeared and were neither in `allowed` nor renamed via `renames`."""
    before = apply_renames(before, renames)
    ok = set(allowed)
    out = {}
    for key, was in before.items():
        lost = [x for x in was if x not in set(after.get(key, []))
                and x not in ok and x.split("::")[-1] not in ok]
        if lost:
            out[key] = lost
    return out


LAYOUT_ZONES = ("horz", "vert")


def calc_users(root, caption: str) -> set:
    """Sheets that reference the calculation with this caption."""
    names = {(c.get("name") or "").strip("[]") for c in root.iter("column") if c.get("caption") == caption}
    names.discard("")
    return {ws.get("name") for ws in root.iter("worksheet")
            if any(f":{n}:" in t or f"[{n}]" in t for n in names
                   for t in (ci.get("name") or "" for ci in ws.iter("column-instance")))
            or any(f"[{n}]" == (c.get("name") or "") for n in names for c in ws.iter("column"))}


def calcs(root) -> dict:
    """{caption: formula} of calculated fields (parameters excluded)."""
    out = {}
    for c in root.iter("column"):
        f = c.find("calculation")
        if f is not None and not c.get("param-domain-type"):
            out.setdefault(c.get("caption") or (c.get("name") or "").strip("[]"), f.get("formula") or "")
    return out


def _params(root) -> dict:
    return {c.get("caption") or c.get("name"): tuple(m.get("value") for m in c.iter("member"))
            for c in root.iter("column") if c.get("param-domain-type")}


def suggest(before, after, sheet_key=None, normalize=None, caption_forms=None) -> dict:
    """Renames and harmless losses derived from facts; the caller decides what to pass to `install`.

    Renames: a sheet with the same identity (`sheet_key(worksheet)`, e.g. its data filter), a
    calculation with the same formula (ties broken by caption similarity), a parameter with the
    same members; zones follow their sheets. Harmless, each with its reason: unnamed layout
    containers, columns with neither caption nor formula the new source does not declare (builder
    debris), calculations no sheet uses. Nothing is applied here: an owner's unused calculation may
    be work in progress, so the guard stays explicit."""
    import difflib
    ib, ia = inventory(before), inventory(after)
    norm = normalize or (lambda f: re.sub(r"\s+(?=(?:[^']*'[^']*')*[^']*$)", "", f or ""))
    forms = caption_forms or (lambda c: (c,))
    renames, harmless = {}, {}
    if sheet_key:
        sb = {ws.get("name"): sheet_key(ws) for ws in before.iter("worksheet")}
        by_key = {sheet_key(ws): ws.get("name") for ws in after.iter("worksheet")}
        for old, k in sb.items():
            new = by_key.get(k) if k is not None else None
            if new and new != old and old not in ia["sheets"]:
                renames[old] = new
    for z in ib["zones"]:
        page, _, zn = z.partition("::")
        if zn in renames:
            renames[z] = f"{renames.get(page, page)}::{renames[zn]}"
    cb, ca = calcs(before), calcs(after)
    by_formula: dict = {}
    for k, v in ca.items():
        by_formula.setdefault(norm(v), []).append(k)
    plain = lambda t: re.sub(r"[^a-z0-9]", "", t.lower().replace("copy", "").replace("agg", ""))
    for old, f in cb.items():
        if old in ca:
            continue
        cand = [k for k in by_formula.get(norm(f), []) if k not in cb] or \
            [k for k in by_formula.get(norm(f), []) if k in ca]
        if len(cand) > 1:
            sim = lambda k: max(difflib.SequenceMatcher(None, plain(o), plain(k)).ratio() for o in forms(old))
            cand = [k for k in sorted(cand, key=lambda k: -sim(k))[:1] if sim(k) >= 0.5]
        if cand:
            renames[old] = cand[0]
        elif not calc_users(before, old):
            harmless[old] = "calculation no sheet uses"
    pb, pa = _params(before), _params(after)
    for old, mem in pb.items():
        cand = [k for k, v in pa.items() if v == mem and k not in pb] if old not in pa else []
        if len(cand) == 1:
            renames[old] = cand[0]
    for c in before.iter("column"):
        nm = (c.get("name") or "").strip("[]")
        if nm and not c.get("caption") and c.find("calculation") is None and nm not in ia["fields"] \
                and not nm.startswith((":", "__tableau")):
            harmless[nm] = "column with neither caption nor formula the new source does not declare"
    for z in LAYOUT_ZONES:
        if any(x.endswith("::" + z) for x in ib["zones"]):
            harmless[z] = "unnamed layout container"
    return {"renames": renames, "harmless": harmless}


def guard_source(book_path: str) -> dict:
    """Pre-edit check: the source is the owner's current file; reports whether they edited it since our install."""
    if not os.path.exists(book_path):
        return {"source": book_path, "exists": False}
    rec = last_install(book_path)
    touched = owner_touched(book_path)
    return {
        "source": book_path, "exists": True, "md5": md5(book_path)[:8],
        "owner_edited_since_install": touched,
        "last_install": (rec or {}).get("at", "none"),
        "reading": ("edited since our install - edit ON TOP of their version"
                    if touched else "exactly what we installed"),
    }


def install(built_path: str, book_path: str, *, allowed_losses=(),
            inventory_before: dict = None, inventory_after: dict = None,
            renames: dict = None, force: bool = False) -> dict:
    """Install the built file over the owner's: snapshot, diff guard, write, manifest."""
    for kind, p in (("built file", built_path), ("owner's workbook", book_path)):
        lock = opened_in_tableau(p)
        if lock and not force:
            raise Refused(
                f"REFUSED: the {kind} is open in Tableau ({os.path.basename(lock)}). "
                "Desktop rewrites an open workbook, so the install would not carry what "
                "was built and checked. Close Tableau and retry.")

    report = {}
    if os.path.exists(book_path):
        report["snapshot"] = snapshot(book_path)

    if inventory_before is not None and inventory_after is not None:
        lost = regressions(inventory_before, inventory_after, allowed_losses,
                           renames)
        report["losses"] = lost
        if lost and not force:
            raise Refused(
                "REFUSED: the edit removes something we did not intend to touch "
                f"(a revert of the owner's work): {lost}. Rollback point: {report.get('snapshot')}. "
                "If deliberate, rerun with force=True")

    shutil.copy2(built_path, book_path)
    data = _load_manifest(book_path)
    data[book_key(book_path)] = {
        "md5": md5(book_path),
        "at": _dt.datetime.now().isoformat(timespec="seconds"),
        "deliberately_removed": sorted(allowed_losses),
        "renamed": dict(sorted((renames or {}).items())),
    }
    _save_manifest(book_path, data)
    report["installed"] = book_path
    return report


def opened_in_tableau(path: str) -> str:
    """Tableau lock file next to the book (`.~<book>__<pid>.twbr`) held by a live process, else ""."""
    import glob
    import subprocess
    d = os.path.dirname(os.path.abspath(path))
    stem = os.path.splitext(os.path.basename(path))[0]
    locks = glob.glob(os.path.join(d, f".~{stem}__*.twbr"))
    for lock in locks:
        try:
            r = subprocess.run(["lsof", "--", lock], capture_output=True,
                               text=True, timeout=15)
        except Exception:
            return lock
        if (r.stdout or "").strip():
            return lock
    return ""


def stale_locks(path: str) -> list:
    """Lock files no process holds (safe to remove)."""
    import glob
    import subprocess
    d = os.path.dirname(os.path.abspath(path))
    stem = os.path.splitext(os.path.basename(path))[0]
    out = []
    for lock in glob.glob(os.path.join(d, f".~{stem}__*.twbr")):
        try:
            r = subprocess.run(["lsof", "--", lock], capture_output=True,
                               text=True, timeout=15)
        except Exception:
            continue
        if not (r.stdout or "").strip():
            out.append(lock)
    return out
