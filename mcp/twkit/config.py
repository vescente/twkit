"""Where twkit gets its settings from.

Connections and secrets: the environment, then `~/.twkit/.env` (template `example.env`).
Paths and guards: `~/.twkit/config.toml`, which never holds a connection or a password.
"""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache

from . import chclient, chsafe

ENV_PREFIX = "TWKIT_DB_"
CONFIG_PATH = os.path.expanduser("~/.twkit/config.toml")
ENV_FILE = os.path.expanduser("~/.twkit/.env")

_FIELDS = ("host", "port", "user", "name", "password")
_CH_FIELDS = ("ch_host", "ch_port", "ch_user", "ch_db", "ch_password", "ch_cert")
_ALL_FIELDS = _FIELDS + _CH_FIELDS
CH_ENV_PREFIX = "TWKIT_CH_"
SECRET_FIELDS = frozenset({"password", "ch_password"})


def _prefix(field: str) -> str:
    return CH_ENV_PREFIX if field in _CH_FIELDS else ENV_PREFIX


def _env_name(field: str) -> str:
    """`ch_host` → `TWKIT_CH_HOST`, `host` → `TWKIT_DB_HOST`."""
    bare = field[3:] if field in _CH_FIELDS else field
    return _prefix(field) + bare.upper()


@lru_cache(maxsize=1)
def _from_env_file() -> dict:
    """`TWKIT_*` assignments in `~/.twkit/.env` (template: `example.env`); other lines are ignored."""
    try:
        with open(ENV_FILE, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return {}
    out = {}
    for line in lines:
        key, sep, value = line.strip().removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if sep and key.startswith("TWKIT_"):
            out[key] = value
    return out


def env_file_values() -> dict:
    """Every `TWKIT_*` value of `~/.twkit/.env`; for the commit guard, never for display."""
    return dict(_from_env_file())


def _env(key: str) -> str:
    """A `TWKIT_*` value from the process environment, then from `~/.twkit/.env`."""
    return os.environ.get(key) or _from_env_file().get(key) or ""


@lru_cache(maxsize=None)
def _section(name: str) -> dict:
    try:
        with open(CONFIG_PATH, "rb") as fh:
            return dict(tomllib.load(fh).get(name) or {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def path(name: str, default: str = "") -> str:
    """Location of user data kept outside the repository."""
    value = _env(f"TWKIT_{name.upper()}") or _section("paths").get(name) or default
    return os.path.expanduser(value) if value else ""


def get(field: str, default: str = "") -> str:
    """One setting, from the first source that has it."""
    if field not in _ALL_FIELDS:
        raise KeyError(f"unknown setting {field!r}; known: {sorted(_ALL_FIELDS)}")
    return _env(_env_name(field)) or default


def source_of(field: str) -> str:
    """Which source answered — useful when the value is not what someone expected."""
    if os.environ.get(_env_name(field)):
        return "environment"
    if _from_env_file().get(_env_name(field)):
        return ENV_FILE
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
    ignored = [f"[{s}]" for s in ("clickhouse", "database") if _section(s)]
    if ignored:
        out["ignored"] = (f"{', '.join(ignored)} in {CONFIG_PATH} is not read; "
                          f"move the connection to {ENV_FILE}")
    return out


def missing_reason(*fields: str) -> str:
    """A sentence a human can act on, or empty when everything needed is present."""
    absent = [f for f in (fields or tuple(_ALL_FIELDS)) if not get(f)]
    if not absent:
        return ""
    return (f"database settings missing: {', '.join(absent)}. "
            f"Set {', '.join(_env_name(f) for f in absent)} in the environment or in "
            f"{ENV_FILE} (template: example.env)")


def reset_cache() -> None:
    """Forget cached sources."""
    for source in (_from_env_file, _section):
        source.cache_clear()


def clickhouse(db: str = "", read_only: bool = False):
    """The ClickHouse connection every twkit module should ask for.

    `read_only` is for untrusted SQL: queries run with `readonly=1`, and each one passes the
    lexical guard and ClickHouse's own parse (`EXPLAIN AST`) before it runs.
    """
    host = get("ch_host")
    if not host:
        raise RuntimeError(missing_reason("ch_host", "ch_user", "ch_password"))
    cert = get("ch_cert")
    client = chclient.HttpClickhouse(
        host=host, port=get("ch_port"), user=get("ch_user"),
        password=get("ch_password"), db=db or get("ch_db"),
        cert=os.path.expanduser(cert) if cert else "", read_only=read_only)
    return chsafe.ReadOnlyClient(client) if read_only else client
