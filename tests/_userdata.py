import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp"))

from twkit import config  # noqa: E402

_ABSENT = os.path.join(HERE, "_absent")

FIXTURES = config.path("fixtures") or _ABSENT
CORPUS = config.path("corpus") or _ABSENT
INSPIRATION = config.path("inspiration") or _ABSENT
