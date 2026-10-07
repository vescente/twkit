"""Run the frame over the inspiration corpus against Tableau Public renders, with a regression gate.

Usage:
    .venv/bin/python tools/frame_corpus.py                  # run and compare with the baseline
    .venv/bin/python tools/frame_corpus.py --save-baseline  # accept the run as the new baseline

A zone that went empty is drawn once more before it counts as worse (`framecmp.gate`).
"""
import argparse
import collections
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "mcp"))

from twkit import cdp, config, framecmp  # noqa: E402

CORPUS = config.path("inspiration")
PUB = os.path.join(CORPUS, "_public")
BASELINE = os.path.join(PUB, "baseline.json")


def _classes(snap: dict) -> dict:
    c = collections.Counter(k for v in snap["books"].values()
                            for pg in v.get("pages", {}).values()
                            for z in pg["zones"] for k in z["classes"])
    return {k: c.get(k, 0) for k in framecmp.CLASSES}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save-baseline", action="store_true")
    ap.add_argument("--only", action="append")
    a = ap.parse_args()
    work = os.path.join(tempfile.gettempdir(), "twkit_frame_corpus")
    os.makedirs(work, exist_ok=True)
    run = os.path.join(work, "run.json")
    if a.only and os.path.exists(BASELINE):
        shutil.copy(BASELINE, run)
    manifest, frames = os.path.join(PUB, "manifest.json"), os.path.join(work, "frames")
    r = framecmp.corpus(manifest, CORPUS, run, out_dir=frames, only=a.only)
    print(f"books {r['book_count']}, failures {r['failures']}; classes {_classes(r)}")
    if os.path.exists(BASELINE):
        d = framecmp.gate(BASELINE, run, lambda books: framecmp.corpus(
            manifest, CORPUS, run, out_dir=frames, only=books))
        print({k: v for k, v in d.items() if k not in ("worse_zones", "recovered")})
        for z in d["recovered"]:
            print("  REDRAWN", z, "(empty on the first draw, clean on the second)")
        for z in d["worse_zones"][:40]:
            print("  WORSE", z["book"][:40], "|", z["page"][:25], "|", z["zone"][:30],
                  z["before"], "→", z["after"])
    if a.save_baseline:
        shutil.copy(run, BASELINE)
        print("baseline updated:", BASELINE)
    cdp.shutdown()


if __name__ == "__main__":
    main()
