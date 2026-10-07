import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))
from twkit import idiom as ID


def test_empty_query_returns_idiom_catalog():
    assert ID._pick("") == list(ID.IDIOMS)


def test_query_finds_idiom_by_meaning():
    names = [it["name"] for it in ID._pick("conditional color by delta sign")]
    assert names and "color" in names[0]
    assert ID._pick("green frogs in a pond") == []


def test_connection_strings_not_exposed():
    raw = "<connection password='hunter2' token=\"abc123\" server='db'/>"
    out = ID.scrub(raw)
    assert "hunter2" not in out and "abc123" not in out
    assert "[HIDDEN]" in out and "server='db'" in out


def test_corpus_found_without_rollback_snapshots():
    books = ID._books()
    assert len(books) > 20
    from twkit import config
    chosen = tuple(os.path.realpath(config.path(n)) for n in ("corpus", "inspiration", "reference")
                   if config.path(n))
    assert not [b for b in books
                if "/_ai/" in os.path.realpath(b) and not os.path.realpath(b).startswith(chosen)]
