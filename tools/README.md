# tools: developer scripts

Run from the repo root with the project venv. `selfcheck` requires every script here to be listed.

| script | purpose | usage |
|---|---|---|
| `frame_corpus.py` | frame regression gate over the inspiration corpus vs Tableau Public renders; a zone that went empty is redrawn once before it counts | `.venv/bin/python tools/frame_corpus.py [--save-baseline] [--only "WHOLE BOOK NAME"]` |
| `frame_pair.py` | one page side by side: frame render and Tableau Public render | `.venv/bin/python tools/frame_pair.py "<workbook>" "<dashboard>" out.jpg` |
| `study_workbooks.py` | measure a folder of workbooks (forms, layout, formatting) as markdown | `.venv/bin/python tools/study_workbooks.py <folder> --label NAME [--json out.json]` |
| `xsd_notes.py` | generate `docs/FORMAT_NOTES.md`: XSD vs what Tableau writes vs what we write | `.venv/bin/python tools/xsd_notes.py > docs/FORMAT_NOTES.md` |

Corpus paths come from `~/.twkit/config.toml` (`[paths]`), never from code.
