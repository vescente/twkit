"""Database table schema → Tableau fields."""
from __future__ import annotations

import json
import os


def catalog_dir() -> str:
    from . import config                    # noqa: PLC0415
    return config.path("catalog", "~/.twkit/catalog")


_FORCE_DIMENSION = {"updated_at", "_loaded", "_row_hash"}
_ID_SUFFIXES = ("_id", "_key", "_uuid")
_FLAG_PREFIXES = ("is_", "has_", "flag_")

GEO_ROLES = {
    "country": "[Country].[ISO3166_2]",
    "city": "[City].[Name]",
    "state": "[State].[Name]",
    "zipcode": "[ZipCode].[Name]",
    "latitude": "[Geographical].[Latitude]",
    "longitude": "[Geographical].[Longitude]",
    "geometry": "[Geographical].[Geometry]",
}

_GEO_BY_NAME = (
    (("user_country", "traffic_geo", "country", "geo", "campaign_country"), "country"),
    (("city", "user_city"), "city"),
    (("state", "province", "region_state"), "state"),
    (("zip", "zipcode", "postal_code"), "zipcode"),
    (("lat", "latitude"), "latitude"),
    (("lon", "lng", "longitude"), "longitude"),
)


def infer_geo_role(name: str, tableau_type: str) -> str:
    """Geographic role by column name, or an empty string."""
    low = name.lower()
    for names, role in _GEO_BY_NAME:
        if low in names:
            if role in ("latitude", "longitude") and tableau_type not in ("real", "integer"):
                return ""
            return GEO_ROLES[role]
    return ""


def ch_type_to_tableau(ch_type: str) -> str:
    """ClickHouse type -> Tableau type."""
    t = ch_type
    for wrapper in ("Nullable(", "LowCardinality("):
        while t.startswith(wrapper):
            t = t[len(wrapper):-1]
    if t.startswith(("Int", "UInt")):
        return "integer"
    if t.startswith(("Float", "Decimal")):
        return "real"
    if t.startswith("Date") and not t.startswith("DateTime"):
        return "date"
    if t.startswith("DateTime"):
        return "datetime"
    if t.startswith("Bool"):
        return "boolean"
    return "string"


def infer_role(name: str, tableau_type: str) -> str:
    """dimension/measure."""
    low = name.lower()
    if name in _FORCE_DIMENSION or low.endswith(_ID_SUFFIXES) or low.startswith(_FLAG_PREFIXES):
        return "dimension"
    return "measure" if tableau_type in ("integer", "real") else "dimension"


def _cache_path(db: str, table: str) -> str:
    return os.path.join(catalog_dir(), f"{db}.{table}.json")


def fetch_schema(db: str, table: str, use_cache: bool = True) -> list[dict]:
    """Table fields for Tableau: [{name, datatype, role, comment}, ...]."""
    fields = None
    if os.environ.get("TWKIT_SCHEMA_OFFLINE") == "1" and use_cache:
        path = _cache_path(db, table)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        raise RuntimeError(f"TWKIT_SCHEMA_OFFLINE=1 but no cached schema: {path}")
    try:
        from . import config                # noqa: PLC0415 — local by design

        rows = config.clickhouse().execute(
            "SELECT name, type, comment FROM system.columns "
            f"WHERE database='{db}' AND table='{table}' ORDER BY position"
        )
        fields = [
            {
                "name": n,
                "datatype": ch_type_to_tableau(t),
                "role": infer_role(n, ch_type_to_tableau(t)),
                "comment": c,
            }
            for n, t, c in rows
        ]
        if fields:
            os.makedirs(catalog_dir(), exist_ok=True)
            with open(_cache_path(db, table), "w", encoding="utf-8") as f:
                json.dump(fields, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        if not use_cache:
            raise
        path = _cache_path(db, table)
        if not os.path.exists(path):
            raise RuntimeError(f"ClickHouse unavailable ({type(exc).__name__}) and no cached schema: {path}") from exc
        with open(path, encoding="utf-8") as f:
            fields = json.load(f)
    return fields


def apply_to_workbook(editor, fields: list[dict]) -> str:
    """Load the fields into the workbook."""
    from .conn import register
    register(editor, [{k: v for k, v in f.items() if k != "comment"} for f in fields])
    geo = apply_geo_roles(editor, fields)
    dims = sum(1 for f in fields if f["role"] == "dimension")
    tail = f", geo roles {geo}" if geo else ""
    return (f"fields loaded: {len(fields)} ({dims} dimensions, "
            f"{len(fields) - dims} measures{tail})")


def apply_geo_roles(editor, fields: list[dict]) -> int:
    """Set `semantic-role` on geographic columns."""
    ds = getattr(editor, "datasource", None)
    if ds is None:
        return 0
    done = 0
    for f in fields:
        role = f.get("semantic_role") or infer_geo_role(f["name"], f["datatype"])
        if not role:
            continue
        col = ds.find(f"column[@name='[{f['name']}]']")
        if col is None or col.get("semantic-role"):
            continue
        col.set("semantic-role", role)
        done += 1
    return done
