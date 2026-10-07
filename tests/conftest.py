import os
import sys

os.environ.setdefault("TWKIT_SCHEMA_OFFLINE", "1")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.environ["TWKIT_CATALOG"] = os.path.join(ROOT, "tests", "fixtures", "catalog")
os.environ["TWKIT_CANON"] = os.path.join(ROOT, "tests", "fixtures", "canon.json")

p = os.path.join(ROOT, "mcp")
if p not in sys.path:
    sys.path.insert(0, p)
