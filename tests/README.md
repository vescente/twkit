# tests

One suite; it must be green.

```bash
.venv/bin/python -m pytest tests/ -q
```

- `conftest.py` sets `TWKIT_SCHEMA_OFFLINE=1` and points the schema catalog and metric canon at
  `fixtures/`: the suite never touches a database.
- `_userdata.py` resolves the private corpora (`fixtures`, `corpus`, `inspiration`) from
  `~/.twkit/config.toml`; tests that need them are skipped when they are absent.
- `_matrix_book.py` builds a small CSV workbook (table, bars, switcher, trend, KPI) for tool-against-frame
  tests; `test_tools_in_frame.py` must classify every MCP tool that changes a workbook.
- A test for a fix must fail without the fix.
- New rules are calibrated on the corpora first: a rule that flags working workbooks is wrong.
