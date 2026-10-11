import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))
import pytest

from twkit import config as C


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    for field in ("HOST", "PORT", "USER", "NAME", "PASSWORD", "DB", "CERT"):
        monkeypatch.delenv(C.ENV_PREFIX + field, raising=False)
        monkeypatch.delenv(C.CH_ENV_PREFIX + field, raising=False)
    monkeypatch.setattr(C, "ENV_FILE", str(tmp_path / "absent.env"))
    C.reset_cache()
    yield
    C.reset_cache()


def test_environment_wins_over_every_other_source(monkeypatch):
    monkeypatch.setenv("TWKIT_DB_HOST", "example.invalid")
    assert C.get("host") == "example.invalid"
    assert C.source_of("host") == "environment"


def test_missing_settings_report_a_reason_instead_of_crashing(monkeypatch):
    monkeypatch.setattr(C, "CONFIG_PATH", "/nonexistent/twkit.toml")
    C.reset_cache()
    assert C.get("host") == ""
    reason = C.missing_reason("host")
    assert "TWKIT_DB_HOST" in reason and "missing" in reason
    assert C.missing_reason("host") != "", "absence must be explainable, not silent"


def test_connection_in_config_toml_is_ignored_and_said(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[database]\nhost = "from-file"\n', encoding="utf-8")
    monkeypatch.setattr(C, "CONFIG_PATH", str(path))
    C.reset_cache()
    assert C.get("host") == "" and C.source_of("host") == "not configured"
    assert "[database]" in C.describe()["ignored"]


def test_password_never_appears_in_describe(monkeypatch):
    monkeypatch.setenv("TWKIT_DB_PASSWORD", "hunter2")
    C.reset_cache()
    shown = C.describe()
    assert shown["password"] == {"set": True, "from": "environment"}
    assert "hunter2" not in str(shown)


def test_unknown_setting_is_refused_loudly():
    with pytest.raises(KeyError):
        C.get("totally-made-up")


def test_untrusted_sql_gets_the_guarded_client(monkeypatch):
    from twkit import chsafe
    monkeypatch.setenv("TWKIT_CH_HOST", "example.invalid")
    C.reset_cache()
    assert isinstance(C.clickhouse(read_only=True), chsafe.ReadOnlyClient)
    assert not isinstance(C.clickhouse(), chsafe.ReadOnlyClient)


def test_settings_come_only_from_environment_and_config_file():
    assert not any(n.startswith("_") and "module" in n.lower() for n in dir(C))


def _env_file(tmp_path, monkeypatch, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(C, "ENV_FILE", str(path))
    C.reset_cache()
    return str(path)


def test_env_file_is_read_and_reported(tmp_path, monkeypatch):
    path = _env_file(tmp_path, monkeypatch, '# note\nexport TWKIT_CH_HOST="from-env-file"\nOTHER=x\n')
    assert C.get("ch_host") == "from-env-file" and C.source_of("ch_host") == path


def test_environment_beats_env_file(tmp_path, monkeypatch):
    _env_file(tmp_path, monkeypatch, "TWKIT_CH_HOST=from-env-file\nTWKIT_CH_PORT=1\n")
    assert C.get("ch_host") == "from-env-file" and C.get("ch_port") == "1"
    monkeypatch.setenv("TWKIT_CH_HOST", "from-process")
    assert C.get("ch_host") == "from-process"


def test_password_from_env_file_never_appears_in_describe(tmp_path, monkeypatch):
    _env_file(tmp_path, monkeypatch, "TWKIT_CH_PASSWORD=hunter2\n")
    shown = C.describe()
    assert shown["ch_password"]["set"] is True and "hunter2" not in str(shown)


def test_template_names_every_setting_and_holds_no_secret():
    root = os.path.join(os.path.dirname(__file__), "..")
    lines = open(os.path.join(root, "example.env"), encoding="utf-8").read().splitlines()
    pairs = dict(ln.split("=", 1) for ln in lines if ln and not ln.startswith("#"))
    assert set(pairs) == {C._env_name(f) for f in C._ALL_FIELDS}
    assert all(v == "" for k, v in pairs.items() if k.endswith("PASSWORD"))


def test_no_environment_file_but_the_template_is_tracked():
    import subprocess
    root = os.path.join(os.path.dirname(__file__), "..")
    tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout
    envs = [f for f in tracked.splitlines() if os.path.basename(f).startswith(".env") or f.endswith(".env")]
    assert envs in ([], ["example.env"])
