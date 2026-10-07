"""Ask REAL workbooks how something is done in Tableau."""
import glob
import os
import re

from lxml import etree

from . import safexml

def _corpus() -> tuple:
    """Where workbooks for idiom search live: the user's corpora (`config.path`) and Tableau's own repository."""
    from . import config
    pats = [os.path.expanduser("~/Documents/My Tableau Repository/Workbooks/*.twbx")]
    for name, pat in (("corpus", "*.twbx"), ("inspiration", "*.twbx"), ("reference", "**/*.twbx")):
        if config.path(name):
            pats.append(os.path.join(config.path(name), pat))
    return tuple(pats)


_SECRET = re.compile(r"((?:password|pwd|token|secret|access[-_]?key)\s*=\s*)(['\"]?)([^'\"\s;&]+)",
                     re.I)


def scrub(text: str) -> str:
    return _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}[HIDDEN]", text)


IDIOMS = (
    {
        "name": "conditional color by sign (separate legends)",
        "keys": ("color", "sign", "conditional", "legend", "measure values", "delta"),
        "xpath": ".//style-rule[@element='mark']/encoding[@attr='color'][@center]",
        "purpose": "color comes from the value itself, each measure has its own scale",
    },
    {
        "name": "measure on color but CONSTANT (named palette)",
        "keys": ("constant", "just black", "palette", "named"),
        "xpath": ".//style-rule[@element='mark']/encoding[@attr='color'][@palette]",
        "purpose": "measure on Color but one color: switches conditional color off for some columns",
    },
    {
        "name": "two measures side by side, each with its own axis (butterfly)",
        "keys": ("butterfly", "two measures", "side by side", "axis", "inflow", "outflow"),
        "xpath": ".//pane[@x-axis-name]",
        "purpose": "measures joined with + on the shelf, one pane each",
    },
    {
        "name": "KPI tile: a large number as the mark label",
        "keys": ("kpi", "tile", "ban", "big number", "number"),
        "xpath": ".//customized-label",
        "purpose": "the value is printed as its own label with its own size, not as cell text",
    },
    {
        "name": "sheet title from parameters",
        "keys": ("title", "parameter", "period", "date"),
        "xpath": ".//layout-options/title/formatted-text",
        "purpose": "the title shows the selected parameter value",
    },
    {
        "name": "how a sheet fills its zone (Fit)",
        "keys": ("fit", "stretch", "zone", "entire view", "scroll"),
        "xpath": ".//window[@class='dashboard']/viewpoints/viewpoint/zoom",
        "purpose": "the Fit of a sheet ON A PAGE lives here, not on the sheet tab",
    },
    {
        "name": "stretchable page canvas",
        "keys": ("canvas", "size", "sizing", "range", "stretch"),
        "xpath": ".//dashboard/size[@sizing-mode!='fixed']",
        "purpose": "51 of 61 corpus pages are not fixed",
    },
    {
        "name": "number mask: delta with arrows",
        "keys": ("mask", "format", "arrow", "percent", "number"),
        "xpath": ".//format[@attr='text-format']|.//column[contains(@default-format,'↑')]",
        "purpose": "the mask itself carries the direction, no calculations",
    },
    {
        "name": "filter and parameter card",
        "keys": ("card", "filter", "border", "control", "panel"),
        "xpath": ".//style-rule[@element='quick-filter']|.//style-rule[@element='parameter-ctrl']",
        "purpose": "control panel styling",
    },
    {
        "name": "heat fill of table cells",
        "keys": ("heat", "fill", "highlight", "cell background"),
        "xpath": ".//encoding[@attr='color'][@type='interpolated']",
        "purpose": "intensity instead of a bar: how matrices are read",
    },
    {
        "name": "table calculation",
        "keys": ("table calc", "calculation", "running", "rank", "% of total"),
        "xpath": ".//column[@name][contains(@name,'pcto:')]|.//table-calc",
        "purpose": "computed over the drawn table; direction matters most",
    },
)


def _books() -> list:
    seen, out = set(), []
    from . import config
    chosen = tuple(os.path.realpath(config.path(n)) for n in ("corpus", "inspiration", "reference")
                   if config.path(n))
    for pat in _corpus():
        for p in glob.glob(pat, recursive=True):
            rp = os.path.realpath(p)
            if rp not in seen and ("/_ai/" not in rp or rp.startswith(chosen)):
                seen.add(rp)
                out.append(p)
    return sorted(out)


def _pick(query: str) -> list:
    """Which idioms a query asks for."""
    q = (query or "").lower()
    if not q.strip():
        return list(IDIOMS)
    scored = []
    for it in IDIOMS:
        hits = sum(1 for k in it["keys"] if k in q)
        if it["name"].lower() in q:
            hits += 5
        if hits:
            scored.append((hits, it))
    scored.sort(key=lambda x: -x[0])
    return [it for _, it in scored]


def _where(node) -> str:
    """Name of the sheet or page that holds a node."""
    cur = node
    while cur is not None:
        tag = etree.QName(cur).localname if isinstance(cur.tag, str) else ""
        if tag in ("worksheet", "dashboard") and cur.get("name"):
            return f"{tag} {cur.get('name')!r}"
        cur = cur.getparent()
    return "—"


def search(query: str = "", limit_books: int = 0, samples: int = 3,
           max_mb: int = 40) -> dict:
    """Find an idiom in working workbooks: shape, workbook, sheet, frequency."""
    wanted = _pick(query)
    if not wanted:
        return {"query": query, "found": {},
                "hint": "nothing matched; call without a query to see the catalog",
                "catalog": [it["name"] for it in IDIOMS]}

    books = _books()
    if limit_books:
        books = books[:limit_books]
    found = {it["name"]: {"book_count": set(), "purpose": it["purpose"], "examples": []} for it in wanted}
    skipped, broken = [], []

    for path in books:
        try:
            if os.path.getsize(path) > max_mb * 1024 * 1024:
                skipped.append(os.path.basename(path))
                continue
            root = safexml.from_twbx(path)
        except Exception as exc:
            broken.append(f"{os.path.basename(path)}: {type(exc).__name__}")
            continue
        for it in wanted:
            try:
                nodes = root.xpath(it["xpath"])
            except etree.XPathEvalError:
                continue
            if not nodes:
                continue
            rec = found[it["name"]]
            rec["book_count"].add(os.path.basename(path))
            if len(rec["examples"]) < samples:
                xml = etree.tostring(nodes[0], encoding="unicode", pretty_print=True)
                rec["examples"].append({
                    "book": os.path.basename(path),
                    "where": _where(nodes[0]),
                    "xml": scrub(xml)[:2000],
                })

    out = {}
    for name, rec in found.items():
        if not rec["book_count"]:
            continue
        out[name] = {"books_in_corpus": len(rec["book_count"]), "purpose": rec["purpose"],
                     "books": sorted(rec["book_count"])[:8], "examples": rec["examples"]}
    res = {"query": query, "books_scanned": len(books) - len(skipped) - len(broken),
           "found": out}
    if not out:
        res["not_found"] = [it["name"] for it in wanted]
    if skipped:
        res["not_checked_over_limit"] = skipped
    if broken:
        res["unreadable"] = broken
    return res


NOISE_ATTRS = frozenset((
    "uuid", "id", "simple-id", "x", "y", "w", "h", "maxheight", "maxwidth",
    "minheight", "minwidth", "fixed-size", "extract-refresh-time", "timestamp",
    "created", "modified", "version",
))
NOISE_TAGS = frozenset(("simple-id", "layout-cache", "repository-location", "thumbnails"))


def _key(node) -> str:
    """Node path in the tree, without noise segments and indexes."""
    parts = []
    cur = node
    while cur is not None and isinstance(cur.tag, str):
        tag = etree.QName(cur).localname
        mark = cur.get("name") or cur.get("class") or cur.get("element") or cur.get("attr")
        parts.append(f"{tag}[{mark}]" if mark else tag)
        cur = cur.getparent()
    return "/".join(reversed(parts))


def _attrs(node) -> dict:
    return {k: v for k, v in node.attrib.items() if k not in NOISE_ATTRS}


def _index(root) -> dict:
    out = {}
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        if etree.QName(node).localname in NOISE_TAGS:
            continue
        k = _key(node)
        if k in out:
            out[k].append(_attrs(node))
        else:
            out[k] = [_attrs(node)]
    return out


def diff_books(before: str, after: str) -> dict:
    """What ONE Desktop action changed in the XML."""
    a, b = _index(safexml.from_twbx(before)), _index(safexml.from_twbx(after))
    appeared, vanished, changed = [], [], []
    for k in b:
        if k not in a:
            for at in b[k]:
                appeared.append({"node": k, **{kk: scrub(vv) for kk, vv in at.items()}})
    for k in a:
        if k not in b:
            for at in a[k]:
                vanished.append({"node": k, **{kk: scrub(vv) for kk, vv in at.items()}})
    for k in a:
        if k not in b:
            continue
        was, now = a[k], b[k]
        if was != now:
            changed.append({"node": k,
                               "before": [{kk: scrub(vv) for kk, vv in x.items()} for x in was][:3],
                               "after": [{kk: scrub(vv) for kk, vv in x.items()} for x in now][:3]})
    n = len(appeared) + len(vanished) + len(changed)
    verdict = "no differences: the action left no trace in the XML" if not n else f"differences: {n}"
    return {"verdict": verdict, "appeared": appeared,
            "vanished": vanished, "changed": changed}


def find_pair(pair_dir: str):
    """`before`/`after` in a reference directory."""
    def one(stem):
        for ext in (".twbx", ".twb"):
            p = os.path.join(pair_dir, stem + ext)
            if os.path.exists(p):
                return p
        return None
    return one("before"), one("after")


def list_pairs(ref_dir: str) -> dict:
    """Which reference pairs are complete and which are missing a side."""
    complete, partial = [], []
    for name in sorted(os.listdir(ref_dir)) if os.path.isdir(ref_dir) else []:
        d = os.path.join(ref_dir, name)
        if not os.path.isdir(d):
            continue
        b, a = find_pair(d)
        (complete if (b and a) else partial).append(
            name if (b and a) else {"reference": name,
                                    "missing": "after" if b else "before"})
    return {"catalog": ref_dir, "complete": complete, "partial": partial}
