import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))
import pytest

from twkit import config as C


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for field in ("HOST", "PORT", "USER", "NAME", "PASSWORD"):
        monkeypatch.delenv(C.ENV_PREFIX + field, raising=False)
    C.reset_cache()
    yield
    C.reset_cache()


def test_environment_wins_over_every_other_source(monkeypatch):
    monkeypatch.setenv("TWKIT_DB_HOST", "example.invalid")
    assert C.get("host") == "example.invalid"
    assert C.source_of("host") == "environment"


def test_missing_settings_report_a_reason_instead_of_crashing(monkeypatch):
    monkeypatch.setattr(C, "CONFIG_PATH", "/nonexistent/twkit.toml")
    monkeypatch.setattr(C, "_from_private_module", lambda: {})
    C.reset_cache()
    assert C.get("host") == ""
    reason = C.missing_reason("host")
    assert "TWKIT_DB_HOST" in reason and "missing" in reason
    assert C.missing_reason("host") != "", "absence must be explainable, not silent"


def test_config_file_is_read_when_environment_is_empty(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[database]\nhost = "from-file"\nport = 3306\n', encoding="utf-8")
    monkeypatch.setattr(C, "CONFIG_PATH", str(path))
    monkeypatch.setattr(C, "_from_private_module", lambda: {})
    C.reset_cache()
    assert C.get("host") == "from-file" and C.get("port") == "3306"
    assert C.source_of("host") == str(path)


def test_password_never_appears_in_describe(monkeypatch):
    monkeypatch.setenv("TWKIT_DB_PASSWORD", "hunter2")
    C.reset_cache()
    shown = C.describe()
    assert shown["password"] == {"set": True, "from": "environment"}
    assert "hunter2" not in str(shown)


def test_unknown_setting_is_refused_loudly():
    with pytest.raises(KeyError):
        C.get("totally-made-up")
