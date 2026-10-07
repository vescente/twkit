"""Pre-flight: one call instead of six, and an honest verdict on whether to hand it over."""
from __future__ import annotations

import os

CHANNELS = ("format", "csv", "meaning", "metrics", "data", "states", "dimensions",
            "view", "taste", "layout", "critic", "previews")


def _sketch_all(path: str, db: str, table: str) -> dict:
    """Sketches of all sheets."""
    from .sketch import sketch_workbook
    return sketch_workbook(path, "", db, table)


def _safe(fn, *a, **kw):
    """Run one check; its failure must not break the others."""
    try:
        return fn(*a, **kw), ""
    except Exception as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:160]}"


def preflight(path: str, db: str = "", table: str = "",
              want_shot: bool = False) -> dict:
    """Run every check and say whether the workbook can be handed over."""
    from . import canon, dryrun, lint, stylescore

    if not os.path.exists(path):
        return {"verdict": "DO NOT hand over", "why": f"file not found: {path}"}

    report: dict = {"book": os.path.basename(path), "channels": {}}
    blockers: list[str] = []
    gaps: list[str] = []

    vs, err = _safe(lint.lint, path)
    if err:
        report["channels"]["format"] = f"not run: {err}"
        gaps.append("workbook format not checked")
    else:
        errors = [v for v in vs if v.severity == "error"]
        warns = [v for v in vs if v.severity == "warn"]
        report["channels"]["format"] = (
            f"errors {len(errors)}, warnings {len(warns)}")
        if errors:
            blockers.append(f"format: {errors[0].message[:90]}")
        report["format_warnings"] = [v.message[:110] for v in warns[:5]]

    from .extract import stale_extract_refs
    sr, err = _safe(stale_extract_refs, path)
    if err or sr is None:
        report["channels"]["source"] = f"not run: {err}"
        gaps.append("workbook references to extract columns not checked")
    else:
        report["channels"]["source"] = sr["verdict"]
        if sr.get("dead"):
            blockers.append("missing from the extract: " + ", ".join(sr["dead"][:4]))

    from . import csvcheck
    cc, err = _safe(csvcheck.check_workbook, path)
    if err or cc is None:
        report["channels"]["csv"] = f"not run: {err}"
        gaps.append("CSV sources not checked; dates and numbers may arrive as Null")
    else:
        report["channels"]["csv"] = cc["verdict"]
        hard = [f for f in cc["findings"] if f["level"] == "error"]
        if hard:
            blockers.append("CSV reads as Null: " + "; ".join(
                f"{f['file']} - {f['column']}: {f['class']}"
                + (f" (first value in row {f['first_filled']} of sample "
                   f"{csvcheck.SAMPLE_ROWS})" if f["class"] == csvcheck.LEADING else "")
                for f in hard[:4]))
            report["csv_findings"] = [f["what"] for f in hard[:6]]
        gaps += [f["what"] for f in cc["findings"] if f["level"] != "error"]
        gaps += cc["not_checked"]

    res, err = _safe(canon.check_workbook, path)
    if err:
        report["channels"]["metrics"] = f"not run: {err}"
        gaps.append("metric canon not checked")
    else:
        bad = [r for r in (res or []) if getattr(r, "severity", "") == "error"]
        report["channels"]["metrics"] = f"canon violations {len(bad)}"
        if bad:
            blockers.append(f"metrics: {getattr(bad[0], 'message', '')[:90]}")

    sheets, err = _safe(dryrun.dry_run, path, db, table)
    if err or sheets is None:
        report["channels"]["data"] = f"not run: {err or 'no result'}"
        gaps.append("dry run not executed; empty sheets NOT ruled out")
    elif len(sheets) == 1 and sheets[0].sheet == "(source)":
        report["channels"]["data"] = f"NOT RUN: {sheets[0].note[:120]}"
        gaps.append("dry run executed for NO sheet; empty sheets "
                    "not ruled out")
    else:
        empty = [s for s in sheets if s.status == "empty"]
        skipped = [s for s in sheets if s.status == "skipped"]
        broken = [s for s in sheets if s.status == "error"]
        report["channels"]["data"] = (
            f"sheets {len(sheets)}, empty {len(empty)}, skipped {len(skipped)}"
            + (f", FAILED {len(broken)}" if broken else ""))
        if broken:
            blockers.append(f"dry run fails on {len(broken)} sheets: "
                            f"{broken[0].sheet} — {(broken[0].note or '')[:70]}")
        if empty:
            why, _e = _safe(dryrun.why_empty, path, db, table)
            hard = [x for x in ((why or {}).get("sheets") or []) if x.get("blocker")]
            soft = [x for x in ((why or {}).get("sheets") or []) if x.get("blocker") is False]
            if hard:
                blockers.append("empty sheets: "
                                + ", ".join(x["sheet"] for x in hard[:4]))
            if soft:
                gaps.append(f"{len(soft)} sheets are empty because of the default period "
                            f"(the extract predates the workbook dates); not a layout defect")
            if not hard and not soft:
                blockers.append(f"empty sheets: "
                                f"{', '.join(s.sheet for s in empty[:4])}")
        if skipped:
            gaps.append(f"{len(skipped)} sheets with LOD/table calculations "
                        f"not checked by the dry run")

    st, err = _safe(dryrun.dry_run_states, path, "", db, table)
    if err or st is None:
        report["channels"]["states"] = f"not run: {err or 'no result'}"
        gaps.append("switcher states not checked; half of the workbook "
                    "was not run")
    elif not st.get("states"):
        report["channels"]["states"] = st.get("why", "no switchers")
    else:
        dead = st.get("empty_in_all_states") or []
        report["channels"]["states"] = (
            f"states run {st['states']}"
            + (f", EMPTY EVERYWHERE {len(dead)}" if dead else ""))
        if dead:
            blockers.append("sheets empty in every switcher state: "
                            + ", ".join(dead[:4]))

    dd, err = _safe(dryrun.dead_dimensions, path, db, table)
    if err or dd is None:
        report["channels"]["dimensions"] = f"not run: {err}"
        gaps.append("dead filters not checked")
    elif "not checked" in dd.get("verdict", ""):
        report["channels"]["dimensions"] = dd["verdict"]
        gaps.append("dead filters not checked: no source")
    else:
        dead = dd.get("dead") or []
        report["channels"]["dimensions"] = dd["verdict"]
        if dead:
            blockers.append("dead filters: "
                            + ", ".join(d["field"] for d in dead[:4]))

    vstats, _vs_err = _safe(dryrun.visual_stats, path, db, table)
    vc, err = _safe(dryrun.visual_check, path, db, table, vstats)
    if err or vc is None:
        report["channels"]["view"] = f"not run: {err}"
        gaps.append("data-driven view not checked")
    elif "not checked" in vc.get("verdict", ""):
        report["channels"]["view"] = vc["verdict"]
        gaps.append("data-driven view not checked: no source")
    else:
        found = vc.get("findings") or []
        report["channels"]["view"] = vc["verdict"]
        if found:
            report["view_findings"] = [f["what"][:120] for f in found[:5]]

    sc, err = _safe(stylescore.score, path)
    if err or sc is None:
        report["channels"]["taste"] = f"not run: {err}"
    else:
        total, metrics, _ = sc
        worse = [m.name for m in metrics if m.verdict == "worse than almost all workbooks"]
        report["channels"]["taste"] = (
            f"{total}/100 against the strict target (corpus medians: house 33, Public 50, "
            f"vendor 41)" + (f"; WORSE THAN ALMOST ALL WORKBOOKS: {', '.join(worse)}" if worse
                             else "; no metric is worse than real workbooks"))

    sk, err = _safe(_sketch_all, path, db, table)
    if err or sk is None:
        report["channels"]["sketch"] = f"not run: {err}"
        gaps.append("sheet sketches not built; nothing is known about sheets "
                    "other than the open one")
    else:
        notes = sk.get("notes") or []
        report["channels"]["sketch"] = sk["verdict"]
        if notes:
            report["sketch_notes"] = notes[:6]

    from . import preview as PV
    th, err = _safe(PV.thumbs_state, path)
    if err or th is None:
        report["channels"]["previews"] = f"not run: {err}"
        th = {}
    else:
        report["channels"]["previews"] = th["verdict"]
        if th.get("fresh") is False and th.get("previews"):
            gaps.append("embedded previews are stale; do not read them as the picture")

    from . import render as RD
    rd, err = _safe(RD.describe, path, "", vstats)
    if err or rd is None:
        report["channels"]["layout"] = f"not run: {err}"
        gaps.append("layout not described; nothing is known about zones and sizes")
        need_shot = "not checked: take a screenshot"
    else:
        report["channels"]["layout"] = rd["verdict"]
        need_shot = rd["image"]
        if th.get("fresh") and need_shot.startswith(("LOOK", "look")):
            need_shot = ("look at the EMBEDDED render (view_thumbnails); no need to "
                         "open a window: " + need_shot)
        report["image"] = need_shot
        hard = [f for f in rd["findings"] if f["level"] == "error"]
        if hard:
            blockers.append("layout: " + hard[0]["what"][:100])
        if rd.get("sheets_off_pages"):
            gaps.append("sheets not on any page (nobody sees them): "
                        + ", ".join(rd["sheets_off_pages"][:6]))

    from . import stylecritic
    cr, err = _safe(stylecritic.critique, path)
    if err or cr is None:
        report["channels"]["critic"] = f"not run: {err}"
        gaps.append("frame view not checked; clipping, overlaps and drift not ruled out")
    else:
        report["channels"]["critic"] = cr["verdict"]
        hard = [f for f in cr["findings"] if f["level"] == "error"]
        if hard:
            blockers.append("view: " + "; ".join(
                f"{f['sheet'] or f['page']} — {f['what'][:70]}" for f in hard[:3])
                + (f" (total {len(hard)})" if len(hard) > 3 else ""))
        soft = [f for f in cr["findings"] if f["level"] == "warn"]
        if soft:
            report["critic_notes"] = [
                f"{f['class']}: {f['sheet'] or f['page']} — {f['what'][:90]}" for f in soft[:6]]
        if cr.get("images"):
            report["frame_images"] = cr["images"]
        gaps += (cr.get("not_checked") or [])[:4]

    if want_shot:
        from . import shot
        res, err = _safe(shot.shoot, path)
        if err or not (res or {}).get("ok"):
            report["channels"]["eyes"] = f"no screenshot: {err or res.get('why')}"
            gaps.append("nobody SAW the workbook; visual defects not ruled out")
        else:
            report["channels"]["eyes"] = f"screenshot: {res['file']}: OPEN and look"
            ch = res.get("change")
            if ch:
                report["channels"]["change"] = ch["verdict"]
                if ch.get("diff_map"):
                    report["diff_map"] = ch["diff_map"]
                if ch.get("changed_share") == 0.0:
                    gaps.append("the screenshot is pixel-identical to the previous one; "
                                "if the workbook was rebuilt, the screen shows the OLD picture")
            else:
                gaps.append("nothing to compare with: no previous screenshot of this workbook, "
                            "regressions were not checked on this run")
    elif need_shot.startswith("look at the EMBEDDED"):
        report["channels"]["eyes"] = need_shot
    elif need_shot.startswith(("LOOK", "look", "not checked")):
        gaps.append(f"screenshot NOT taken although needed: {need_shot}")
    else:
        report["channels"]["eyes"] = f"no screenshot required: {need_shot}"

    report["not_checked"] = gaps
    report["blockers"] = blockers
    report["verdict"] = (
        "DO NOT hand over" if blockers else
        "NOT fully checked: hand over at your own risk" if gaps else
        "OK to hand over")
    return report


def format_report(r: dict) -> str:
    lines = [f"Preflight - {r.get('book', '?')}: {r['verdict']}"]
    if r.get("image"):
        lines.append(f"  SCREENSHOT: {r['image']}")
    for name, val in (r.get("channels") or {}).items():
        lines.append(f"  {name:8s} {val}")
    for b in r.get("blockers") or []:
        lines.append(f"  x BLOCKER: {b}")
    for g in r.get("not_checked") or []:
        lines.append(f"  ? not checked: {g}")
    return "\n".join(lines)
