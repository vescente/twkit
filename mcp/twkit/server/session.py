"""The workbook a client is working on, shared by every tool of one server process."""
from __future__ import annotations

_active = {"book": None}


def current():
    """The active workbook; `create_workbook` or `open_workbook` starts one."""
    book = _active["book"]
    if book is None:
        raise RuntimeError("no active workbook: call create_workbook or open_workbook first")
    return book


def use(book):
    _active["book"] = book
    return book


def active():
    return _active["book"]
