"""The Tableau log as a feedback channel: what the product itself says about a book."""
from __future__ import annotations

import json
import os
import re

LOG = os.path.expanduser("~/Documents/My Tableau Repository/Logs/log.txt")

NOISE = ("endeavour-edpa", "InfoUtils::Lookup", "downloading pipeline configuration",
         "Post spans request", "entitlement", "FeatureFID", "stream truncated",
         "connector-plugin-error")


def read_log(tail_bytes: int = 400_000, path: str = "",
             book_hint: str = "") -> list[dict]:
    """Parse the log tail (JSON lines; unparseable lines are skipped), optionally filtered by book name."""
    path = path or LOG
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - tail_bytes))
        chunk = f.read().decode("utf-8", "replace")

    out: list[dict] = []
    for line in chunk.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if book_hint and book_hint.lower() not in line.lower():
            continue
        out.append(rec)
    return out


def _message(rec: dict) -> str:
    v = rec.get("v")
    if isinstance(v, dict):
        return str(v.get("excp-msg") or v.get("msg") or v.get("error") or v)[:300]
    return str(v)[:300]


LOAD_FAILURE = (
    "is not declared for element",
    "not able to complete",
    "Errors occurred while trying to load",
    "Unable to complete action",
    "Error Code:",
)


def load_failures(tail_bytes: int = 400_000, path: str = "") -> list:
    """Messages meaning the workbook failed to load (matched by text, not severity)."""
    raw = _raw_tail(tail_bytes, path)
    out, seen = [], set()
    for line in raw.splitlines():
        for marker in LOAD_FAILURE:
            if marker in line:
                for piece in line.replace("\\n", "\n").split("\n"):
                    if marker not in piece:
                        continue
                    m = re.search(r"(Error\(|Errors occurred|Unable to complete|Error Code:).*",
                                  piece)
                    text = (m.group(0) if m else piece).strip().rstrip('"},')
                    if text and text not in seen:
                        seen.add(text)
                        out.append(text[:300])
                break
    return out


def _raw_tail(tail_bytes: int, path: str = "") -> str:
    p = path or LOG
    if not os.path.exists(p):
        return ""
    with open(p, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - tail_bytes))
        return f.read().decode("utf-8", "replace")


_DIALOG_RE = re.compile(r'error-short-message=\\?"(.*?)\\?" issue-helper-links')


def error_dialogs(tail_bytes: int = 400_000, path: str = "") -> list:
    """Short text of Tableau error dialogs, read from the log (the show-detailed-error-dialog command args)."""
    out = []
    for rec in read_log(tail_bytes, path):
        v = rec.get("v")
        if not isinstance(v, dict) or v.get("name") != "tabdoc:show-detailed-error-dialog":
            continue
        args = str(v.get("args", ""))
        m = _DIALOG_RE.search(args)
        text = (m.group(1) if m else args[:300]).replace('\\"', '"').replace('\\', '')
        out.append({"ts": rec.get("ts"), "text": text,
                    "warning": text.lower().startswith("warnings")})
    return out


def problems(book_path: str = "", tail_bytes: int = 400_000) -> dict:
    """What Tableau said when opening the book: significant errors/warnings plus a verdict."""
    hint = os.path.splitext(os.path.basename(book_path))[0] if book_path else ""
    records = read_log(tail_bytes)
    errors, warns, seen = [], [], set()
    for rec in records:
        sev = rec.get("sev")
        if sev not in ("error", "warn", "fatal"):
            continue
        msg = _message(rec)
        if any(n in msg for n in NOISE) or any(n in str(rec.get("k", "")) for n in NOISE):
            continue
        key = msg[:140]
        if key in seen:
            continue
        seen.add(key)
        item = {"sev": sev, "kind": rec.get("k", ""), "msg": msg}
        (errors if sev in ("error", "fatal") else warns).append(item)

    mentions = sum(1 for r in read_log(tail_bytes, book_hint=hint)) if hint else 0
    fails = load_failures(tail_bytes)
    dialogs = [d for d in error_dialogs(tail_bytes) if not hint or hint in d["text"]]
    return {
        "book": os.path.basename(book_path) if book_path else "(whole session)",
        "log_mentions": mentions,
        "error_count": len(errors), "warning_count": len(warns),
        "verdict": ("WORKBOOK FAILED TO LOAD" if fails else
                    "Tableau showed a warnings dialog on load" if dialogs else
                    "Tableau did not open it or complained" if errors else
                    "Tableau opened it without errors" if mentions or records else
                    "no log records - the workbook was not opened"),
        "load_failures": fails[:10],
        "dialogs": dialogs[-5:],
        "errors": errors[:10], "warns": warns[:10],
    }


def format_report(book_path: str = "") -> str:
    p = problems(book_path)
    lines = [f"Tableau log - {p['book']}: {p['verdict']} "
             f"(errors {p['error_count']}, warnings {p['warning_count']}, "
             f"book mentions {p['log_mentions']})"]
    for d in p.get("dialogs", []):
        lines.append(f"  [DIALOG] {d['text'][:200]}")
    for msg in p.get("load_failures", []):
        lines.append(f"  [LOAD] {msg[:150]}")
    for item in p["errors"] + p["warns"]:
        lines.append(f"  [{item['sev']:5s}] {item['kind'][:24]:24s} {item['msg'][:110]}")
    if not p["errors"] and not p["warns"]:
        lines.append("  startup noise filtered out, nothing substantive")
    return "\n".join(lines)
