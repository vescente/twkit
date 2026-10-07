import csv
import io
import os
import zipfile

import pytest

from twkit import csvcheck as C

HEAD = ["sheet", "dim_1", "date", "measure", "value"]
TYPES = {"sheet": "string", "dim_1": "string", "date": "date", "measure": "string",
         "value": "real"}


def _csv_text(rows, head=HEAD, sep=","):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=sep, lineterminator="\n")
    w.writerow(head)
    w.writerows(rows)
    return buf.getvalue()


def _rows(undated: int, dated: int, date="2026-09-29 00:00:00"):
    return ([("Table", f"p{i}", "", "FTD", "1.0") for i in range(undated)]
            + [("Cumulative", f"p{i}", date, "FTD", "2.0") for i in range(dated)])


def _twb(fname="data.csv", types=TYPES, head=HEAD, sep=",", directory="",
         extract=False):
    rel = f"[{fname}]"
    cols = "".join(f'<column datatype="{types[h]}" name="{h}" ordinal="{i}"/>'
                   for i, h in enumerate(head) if h in types)
    maps = "".join(f'<map key="[{h}]" value="{rel}.[{h}]"/>' for h in head)
    ex = ('<extract enabled="true"><connection class="hyper" '
          'dbname="Data/Extracts/x.hyper"/></extract>' if extract else "")
    return f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version="18.1"><datasources>
<datasource caption="data" inline="true" name="federated.abc" version="18.1">
<connection class="federated"><named-connections>
<named-connection caption="data" name="textscan.1"><connection class="textscan"
 directory="{directory}" filename="{fname}" password="" server=""/></named-connection>
</named-connections>
<relation connection="textscan.1" name="{fname}" table="[data#csv]" type="table">
<columns character-set="UTF-8" header="yes" locale="en_US" separator="{sep}">{cols}</columns>
</relation><cols>{maps}</cols></connection>{ex}
<column datatype="date" name="[date]" role="dimension" type="ordinal"/>
</datasource></datasources><worksheets/></workbook>"""


def _book(tmp_path, rows=None, text=None, name="book.twbx", packaged=True, **kw):
    text = text if text is not None else _csv_text(rows)
    fname = kw.pop("fname", "data.csv")
    out = tmp_path / name
    if name.endswith(".twbx"):
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("book.twb", _twb(fname=fname, **kw))
            if packaged:
                z.writestr(fname, text)
    else:
        out.write_text(_twb(fname=fname, **kw), encoding="utf-8")
        (tmp_path / fname).write_text(text, encoding="utf-8")
    return str(out)


def _only(res, klass):
    return [f for f in res["findings"] if f["class"] == klass]


def test_date_beyond_tableau_sample_is_blocker(tmp_path):
    res = C.check_workbook(_book(tmp_path, _rows(1100, 50)))
    hits = _only(res, C.LEADING)
    assert len(hits) == 1, res
    f = hits[0]
    assert (f["column"], f["level"], f["first_filled"]) == ("date", "error", 1101)
    assert f["type_from"] == "book"
    assert "Null" in res["verdict"]


def test_dated_rows_first_clears_finding(tmp_path):
    rows = _rows(1100, 50)
    rows = rows[1100:] + rows[:1100]
    res = C.check_workbook(_book(tmp_path, rows))
    assert res["findings"] == [], res
    assert res["verdict"].endswith("clean")


def test_date_in_second_half_of_sample_not_checked(tmp_path):
    res = C.check_workbook(_book(tmp_path, _rows(700, 50)))
    f = _only(res, C.LEADING)[0]
    assert f["level"] == "warn" and f["first_filled"] == 701
    assert "not checked" in f["what"]


def test_string_column_with_leading_empty_not_finding(tmp_path):
    rows = [("Table", "", "2026-09-29 00:00:00", "FTD", "1")] * 1100 + \
           [("Table", "Germany", "2026-09-29 00:00:00", "FTD", "1")]
    assert C.check_workbook(_book(tmp_path, rows))["findings"] == []


def test_number_with_leading_empty_flagged(tmp_path):
    rows = [("Table", "p", "2026-09-29", "FTD", "")] * 1100 + \
           [("Table", "p", "2026-09-29", "FTD", "5")]
    f = _only(C.check_workbook(_book(tmp_path, rows)), C.LEADING)
    assert [x["column"] for x in f] == ["value"]


def test_null_sentinel_not_value(tmp_path):
    rows = [("Table", "p", "%null%", "FTD", "1")] * 1100 + \
           [("Table", "p", "2026-09-29", "FTD", "1")]
    f = _only(C.check_workbook(_book(tmp_path, rows)), C.LEADING)
    assert f and f[0]["first_filled"] == 1101


def test_mixed_date_format_is_blocker(tmp_path):
    rows = (_rows(0, 10, "2026-09-29 00:00:00") + _rows(0, 3, "2026-09-29"))
    res = C.check_workbook(_book(tmp_path, rows))
    f = _only(res, C.MIXED)
    assert len(f) == 1 and f[0]["level"] == "error" and f[0]["format_count"] == 2
    assert any("'2026-09-29'" in e for e in f[0]["examples"])
    assert any("'2026-09-29 00:00:00'" in e for e in f[0]["examples"])


def test_different_digit_lengths_one_format(tmp_path):
    rows = [("C", "p", d, "FTD", "1") for d in ("2026-9-1", "2026-10-12", "2026-1-31")]
    assert C.check_workbook(_book(tmp_path, rows))["findings"] == []


def test_text_in_numeric_column(tmp_path):
    rows = [("C", "p", "2026-09-29", "FTD", v) for v in ("1.5", "12,5", "n/a", "%null%", "-3e2")]
    f = _only(C.check_workbook(_book(tmp_path, rows)), C.TEXT_NUMBERS)
    assert len(f) == 1 and f[0]["non_numbers"] == 2, f
    assert "'12,5'" in f[0]["what"]


def test_type_by_content_when_undeclared(tmp_path):
    types = {"sheet": "string", "dim_1": "string", "measure": "string", "value": "real"}
    path = _book(tmp_path, _rows(1100, 50), types=types)
    with zipfile.ZipFile(path) as z:
        twb = z.read("book.twb").decode().replace(
            '<column datatype="date" name="[date]" role="dimension" type="ordinal"/>', "")
        data = z.read("data.csv")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("book.twb", twb)
        z.writestr("data.csv", data)
    f = _only(C.check_workbook(path), C.LEADING)
    assert f and f[0]["column"] == "date" and f[0]["type_from"] == "content"


def test_twb_reads_csv_from_disk(tmp_path):
    path = _book(tmp_path, _rows(1100, 5), name="book.twb", directory=str(tmp_path))
    assert _only(C.check_workbook(path), C.LEADING)


def test_separator_from_declaration(tmp_path):
    text = _csv_text(_rows(1100, 5), sep=";")
    path = _book(tmp_path, text=text, sep=";")
    assert _only(C.check_workbook(path), C.LEADING)


def test_csv_not_found_is_not_checked(tmp_path):
    res = C.check_workbook(_book(tmp_path, _rows(1, 1), packaged=False,
                                 directory="/nonexistent"))
    assert res["findings"] == [] and res["not_checked"], res


def test_extract_source_not_checked(tmp_path):
    res = C.check_workbook(_book(tmp_path, _rows(1100, 5), packaged=False, extract=True))
    assert res["findings"] == [] and res["not_checked"] == []
    assert "extract" in res["verdict"]


def test_engine_built_book(tmp_path):
    from twkit.book import Book

    data = tmp_path / "eng.csv"
    data.write_text(_csv_text(_rows(1100, 20)), encoding="utf-8")
    ed = Book()
    ed.set_csv_connection(str(data), fields=[
        {"name": h, "datatype": TYPES[h],
         "role": "measure" if h == "value" else "dimension",
         "field_type": "quantitative" if h == "value" else "nominal"} for h in HEAD])
    out = tmp_path / "eng.twbx"
    ed.save(str(out))
    srcs = C.csv_sources(str(out))
    assert srcs and srcs[0]["types"].get("date") == "date", srcs
    f = _only(C.check_workbook(str(out)), C.LEADING)
    assert f and f[0]["first_filled"] == 1101


def test_preflight_blocks_book_with_null_dates(tmp_path, monkeypatch):
    from twkit import preflight as PF

    book = _book(tmp_path, _rows(1100, 50) + _rows(0, 1, "2026-09-29"))
    import twkit.canon as canon
    import twkit.dryrun as dryrun
    import twkit.extract as extract
    import twkit.lint as lint
    import twkit.preview as preview
    import twkit.render as render
    import twkit.stylescore as stylescore

    def boom(*a, **k):
        raise RuntimeError("stubbed in test")
    for mod, fn in ((lint, "lint"), (extract, "stale_extract_refs"),
                    (canon, "check_workbook"), (dryrun, "dry_run"),
                    (dryrun, "dry_run_states"), (dryrun, "dead_dimensions"),
                    (dryrun, "visual_stats"), (dryrun, "visual_check"),
                    (stylescore, "score"), (preview, "thumbs_state"),
                    (render, "describe")):
        monkeypatch.setattr(mod, fn, boom)
    monkeypatch.setattr(PF, "_sketch_all", boom)

    r = PF.preflight(book)
    assert r["verdict"] == "DO NOT hand over", r
    assert any(b.startswith("CSV reads as Null") and "leading empty" in b
               and "mixed format" in b for b in r["blockers"]), r["blockers"]
    assert "Null" in r["channels"]["csv"]

    warn_book = _book(tmp_path, _rows(700, 50), name="warn.twbx")
    r = PF.preflight(warn_book)
    assert not any(b.startswith("CSV") for b in r["blockers"]), r["blockers"]
    assert any("not checked" in g and "date" in g for g in r["not_checked"])
