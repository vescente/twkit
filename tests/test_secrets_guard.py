import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import check_secrets as S  # noqa: E402


def test_env_files_and_guarded_values_are_found_by_name_only():
    values = {"TWKIT_CH_PASSWORD": "pa55-word-x", "TWKIT_CH_HOST": "db.internal.example"}
    files = {"example.env": "TWKIT_CH_PASSWORD=\n", ".env": "x", "conf/prod.env": "x",
             "mcp/a.py": "host = 'db.internal.example'", "README.md": "nothing here"}
    found = S.findings(files, values)
    assert sorted(found) == [(".env", "an environment file"), ("conf/prod.env", "an environment file"),
                             ("mcp/a.py", "the value of TWKIT_CH_HOST")]
    assert not any(v in reason for _, reason in found for v in values.values())


@pytest.mark.skipif(not S.guarded_values(), reason="no ~/.twkit/.env on this machine")
def test_no_tracked_file_carries_a_local_secret():
    assert S.findings(S._files(staged=False), S.guarded_values()) == []
