"""Where twkit gets its database settings from."""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache

from . import chclient

ENV_PREFIX = "TWKIT_DB_"
CONFIG_PATH = os.path.expanduser("~/.twkit/config.toml")

_FIELDS = {
    "host": "_CH_MYSQL_HOST",
    "port": "_CH_MYSQL_PORT",
    "user": "_CH_MYSQL_USER",
    "name": "_CH_MYSQL_DB",
    "password": "_CH_MYSQL_PASSWORD",
}
_CH_FIELDS = {
    "ch_host": "_CH_HOST",
    "ch_port": "_CH_PORT",
    "ch_user": "_CH_USER",
    "ch_db": "_CH_DB",
    "ch_password": "_CH_PASSWORD",
    "ch_cert": "_CH_CERT",
}
_ALL_FIELDS = {**_FIELDS, **_CH_FIELDS}
CH_ENV_PREFIX = "TWKIT_CH_"
SECRET_FIELDS = frozenset({"password", "ch_password"})


def _prefix(field: str) -> str:
    return CH_ENV_PREFIX if field in _CH_FIELDS else ENV_PREFIX


def _env_name(field: str) -> str:
    """`ch_host` → `TWKIT_CH_HOST`, `host` → `TWKIT_DB_HOST`."""
    bare = field[3:] if field in _CH_FIELDS else field
    return _prefix(field) + bare.upper()


@lru_cache(maxsize=1)
def _from_file() -> dict:
    try:
        with open(CONFIG_PATH, "rb") as fh:
            raw = tomllib.load(fh)
            merged = dict(raw.get("database", {}))
            for key, value in (raw.get("clickhouse") or {}).items():
                merged[key if key in _CH_FIELDS else f"ch_{key}"] = value
            return merged
    except (OSError, tomllib.TOMLDecodeError):
        return {}


@lru_cache(maxsize=None)
def _section(name: str) -> dict:
    try:
        with open(CONFIG_PATH, "rb") as fh:
            return dict(tomllib.load(fh).get(name) or {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def path(name: str, default: str = "") -> str:
    """Location of user data kept outside the repository."""
    value = os.environ.get(f"TWKIT_{name.upper()}") or _section("paths").get(name) or default
    return os.path.expanduser(value) if value else ""


@lru_cache(maxsize=1)
def _settings_module():
    """The optional settings module, or None."""
    import importlib                             # noqa: PLC0415 — local by design
    import sys                                   # noqa: PLC0415 — local by design
    section = _section("settings")
    name = os.environ.get("TWKIT_SETTINGS_MODULE") or section.get("module") or ""
    where = os.path.expanduser(os.environ.get("TWKIT_SETTINGS_PATH") or section.get("path") or "")
    if not name:
        return None
    added = bool(where) and where not in sys.path
    if added:
        sys.path.insert(0, where)
    try:
        return importlib.import_module(name)
    except Exception:
        return None
    finally:
        if added and where in sys.path:
            sys.path.remove(where)


@lru_cache(maxsize=1)
def _from_private_module() -> dict:
    """Settings read from the settings module."""
    mod = _settings_module()
    if mod is None:
        return {}
    return {key: getattr(mod, attr) for key, attr in _ALL_FIELDS.items() if hasattr(mod, attr)}


def get(field: str, default: str = "") -> str:
    """One setting, from the first source that has it."""
    if field not in _ALL_FIELDS:
        raise KeyError(f"unknown setting {field!r}; known: {sorted(_ALL_FIELDS)}")
    env = os.environ.get(_env_name(field))
    if env:
        return env
    for source in (_from_file(), _from_private_module()):
        value = source.get(field)
        if value not in (None, ""):
            return str(value)
    return default


def source_of(field: str) -> str:
    """Which source answered — useful when the value is not what someone expected."""
    if os.environ.get(_env_name(field)):
        return "environment"
    if _from_file().get(field) not in (None, ""):
        return CONFIG_PATH
    if _from_private_module().get(field) not in (None, ""):
        return "settings module"
    return "not configured"


def describe() -> dict:
    """What is configured and where it came from."""
    out = {}
    for field in _ALL_FIELDS:
        if field in SECRET_FIELDS:
            out[field] = {"set": bool(get(field)), "from": source_of(field)}
        else:
            out[field] = {"value": get(field), "from": source_of(field)}
    out["not_configured"] = [f for f in _ALL_FIELDS if not get(f)]
    return out


def missing_reason(*fields: str) -> str:
    """A sentence a human can act on, or empty when everything needed is present."""
    absent = [f for f in (fields or tuple(_ALL_FIELDS)) if not get(f)]
    if not absent:
        return ""
    section = "[clickhouse]" if all(f in _CH_FIELDS for f in absent) else "[database]"
    return (f"database settings missing: {', '.join(absent)}. "
            f"Set {', '.join(_env_name(f) for f in absent)}, "
            f"or add a {section} section to {CONFIG_PATH}")


def reset_cache() -> None:
    """Forget cached sources."""
    for source in (_from_file, _section, _settings_module, _from_private_module, _private_conn):
        clear = getattr(source, "cache_clear", None)
        if clear:
            clear()


def clickhouse(db: str = "", read_only: bool = False):
    """The ClickHouse connection every twkit module should ask for.

    `read_only` asks the built-in client to run queries with `readonly=1`; a settings-module
    client is used as it is, so untrusted SQL still goes through `chsafe.read_only` first.
    """
    private = _private_conn()
    if private is not None:
        return private(db) if db else private()
    host = get("ch_host")
    if not host:
        raise RuntimeError(missing_reason("ch_host", "ch_user", "ch_password"))
    return chclient.HttpClickhouse(
        host=host, port=get("ch_port"), user=get("ch_user"),
        password=get("ch_password"), db=db or get("ch_db"), cert=get("ch_cert"),
        read_only=read_only)


@lru_cache(maxsize=1)
def _private_conn():
    """`ClickhouseConn` from the settings module, or None."""
    return getattr(_settings_module(), "ClickhouseConn", None)