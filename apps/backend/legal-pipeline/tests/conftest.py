from pathlib import Path
import json
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_fixture(name: str):
    path = PROJECT_ROOT / "tests" / "fixtures" / name
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)