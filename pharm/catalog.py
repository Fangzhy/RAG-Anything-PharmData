import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
DOCS = ROOT / "docs"
BUILD = DATA / "prepared"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def rows(feed):
    with (RAW / f"{feed}.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))
