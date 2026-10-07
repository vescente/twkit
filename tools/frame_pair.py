"""Side-by-side image of one page: frame render | Tableau Public render.

    .venv/bin/python tools/frame_pair.py "<workbook without .twbx>" "<dashboard>" <out.jpg>
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "mcp"))

from PIL import Image  # noqa: E402

from twkit import config, frame  # noqa: E402

CORPUS = config.path("inspiration")


def main(book: str, page: str, out: str):
    r = frame.check(os.path.join(CORPUS, book + ".twbx"),
                    out_dir=os.path.join(os.path.dirname(os.path.abspath(out)), "f"),
                    default_locale="en_US")
    man = json.load(open(os.path.join(CORPUS, "_public", "manifest.json")))
    m = next(x for x in man if x["book"] == book)
    pg = next(p for p in r["pages"] if p["page"] == page)
    ref = next(d["file"] for d in m["dashboards"] if d["name"] == page)
    f = Image.open(pg["image"]).convert("RGB")
    f = f.crop((20, 20, f.width - 20, f.height - 20))
    p = Image.open(ref).convert("RGB")
    h = 800
    f = f.resize((int(f.width * h / f.height), h))
    p = p.resize((int(p.width * h / p.height), h))
    im = Image.new("RGB", (f.width + p.width + 10, h), "white")
    im.paste(f, (0, 0))
    im.paste(p, (f.width + 10, 0))
    im.save(out, quality=80)
    print(out)


if __name__ == "__main__":
    main(*sys.argv[1:4])
