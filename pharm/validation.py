import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pharm.catalog import DOCS, RAW, load_json, rows

FEEDS = ("eln", "lims", "sensor")


def issues(feed, row, schema, catalog):
    errors = [f"Missing {k}" for k in schema[feed]["required"] if not row.get(k)]
    batch = row.get("batch")
    if batch not in catalog["batches"]:
        errors.append("Unknown batch identifier")
    if feed in ("eln","sensor") and row.get("run") != "RUN-" + batch.removeprefix("B-"):
        errors.append("Run must belong to the recorded batch")
    try:
        if datetime.fromisoformat(row["timestamp"]).utcoffset() is None:
            errors.append("Timestamp requires UTC offset")
    except (ValueError, KeyError):
        errors.append("Invalid timestamp")
    if feed == "eln":
        return errors
    try:
        if not math.isfinite(float(row["value"])):
            errors.append("Non-finite measurement")
    except (KeyError, ValueError):
        errors.append("Numeric measurement required")
    kind = row.get("test" if feed == "lims" else "channel")
    unit = schema[feed]["units"].get(kind)
    if not unit or row.get("unit") != unit:
        errors.append("Unit or measurement type outside channel/method contract")
    if feed == "lims":
        if not any(a["sample"] == row.get("sample") and a["batch"] == batch for a in catalog["images"]):
            errors.append("Unknown sample for batch")
        rule = schema["criteria"].get(row.get("method"), {})
        if rule.get("test") != kind or str(rule.get("time_min")) != row.get("time_min"):
            errors.append("Method or test time mismatch")
    return errors


def load_database(path):
    catalog = load_json(RAW / "catalog.json")
    schema = load_json(DOCS / "feed_schemas.json")
    db = sqlite3.connect(path)
    try:
        db.executescript((DOCS / "schema.sql").read_text())
        db.executemany("INSERT INTO batches VALUES (?)", [(b,) for b in catalog["batches"]])
        db.executemany("INSERT INTO runs VALUES (?,?)", [("RUN-"+b[2:],b) for b in catalog["batches"]])
        db.executemany("INSERT INTO samples VALUES (?,?)", [(a["sample"],a["batch"]) for a in catalog["images"]])
        for kind in ("images","documents"):
            db.executemany("INSERT INTO assets VALUES (?,?,?,?,?)", [(a["id"],a["batch"],a["sample"],a["path"],kind) for a in catalog[kind]])
        for rule in schema["criteria"].values():
            db.execute("INSERT INTO criteria VALUES (?,?,?,?,?)", [rule.get(k) for k in ("method","test","time_min","unit","lower_bound")])
        for feed in FEEDS:
            records = rows(feed)
            variants = defaultdict(set)
            for row in records:
                variants[row["id"]].add(tuple(row.items()))
            seen = set()
            for line, original in enumerate(records, 2):
                row = original.copy()
                locator = f"{feed}.csv#{line}"
                initial = issues(feed,row,schema,catalog)
                corrections = []
                rule = schema["corrections"][feed]
                field = rule["field"]
                aliases = catalog["batch_aliases"] if feed == "eln" else rule["aliases"]
                if initial and row[field] in aliases:
                    value = aliases[row[field]]
                    corrections.append(dict(field=field, before=row[field], after=value, rule=f"{feed}.{field}@{schema['version']}", evidence=rule.get("lookup","docs/feed_schemas.json")))
                    row[field] = value
                remaining = issues(feed,row,schema,catalog)
                if len(variants[row["id"]]) > 1:
                    remaining.append("Conflicting source records share the same ID")
                identity = tuple(original.items())
                if identity in seen:
                    status = "Duplicate"
                elif remaining:
                    status = "Quarantined"
                elif initial:
                    status = "Corrected"
                else:
                    status = "Accepted"
                seen.add(identity)
                db.execute("INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?)", (locator,feed,row["id"],status,*map(json.dumps,(original,row,initial,remaining,corrections))))
                if status in ("Accepted","Corrected"):
                    fields = schema[feed]["required"]
                    row["timestamp"] = datetime.fromisoformat(row["timestamp"]).astimezone(timezone.utc).isoformat()
                    columns = ",".join(fields + ["locator"])
                    placeholders = ",".join("?" for _ in range(len(fields)+1))
                    db.execute(f"INSERT INTO {feed} ({columns}) VALUES ({placeholders})", [row[k] for k in fields]+[locator])
        db.commit()
    finally:
        db.close()


def read_db(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db
