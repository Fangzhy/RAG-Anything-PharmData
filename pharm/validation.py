import csv
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pharm.catalog import DOCS, RAW, load_json

FEEDS = ("eln","lims","sensor")


def issues(feed,row,schema,catalog):
    required = set(schema[feed]["required"]) | {"id","batch","timestamp"}
    errors = [f"Missing {k}" for k in sorted(required) if not row.get(k)]
    batch = row.get("batch")
    if batch not in catalog["batches"]:
        errors.append("Unknown batch identifier")
    if feed in ("eln","sensor") and (not row.get("run") or catalog["runs"].get(row["run"])!=batch):
        errors.append("Run must belong to the recorded batch")
    try:
        if datetime.fromisoformat(row.get("timestamp") or "").utcoffset() is None:
            errors.append("Timestamp requires UTC offset")
    except ValueError:
        errors.append("Invalid timestamp")
    if feed=="eln":
        return errors
    try:
        if not math.isfinite(float(row.get("value") or "")):
            errors.append("Non-finite measurement")
    except ValueError:
        errors.append("Numeric measurement required")
    kind = row.get("test" if feed=="lims" else "channel")
    unit = schema[feed]["units"].get(kind)
    if not unit or row.get("unit")!=unit:
        errors.append("Unit or measurement type outside channel/method contract")
    if feed=="lims":
        if not row.get("sample") or catalog["samples"].get(row["sample"])!=batch:
            errors.append("Unknown sample for batch")
        rule = schema["criteria"].get(row.get("method"),{})
        if rule.get("test")!=kind or str(rule.get("time_min"))!=row.get("time_min"):
            errors.append("Method or test time mismatch")
    return errors


def records_by_feed(raw):
    data = {}
    for feed in FEEDS:
        path = raw/f"{feed}.csv"
        if path.exists():
            with path.open(encoding="utf-8-sig",newline="") as stream:
                data[feed] = list(csv.DictReader(stream))
        else:
            data[feed] = []
    return data


def mapped(original,contract):
    mapping = contract.get("columns",{})
    return {mapping.get(k,k):v for k,v in original.items()}


def reference_catalog(catalog,records,schema):
    samples = defaultdict(set)
    runs = defaultdict(set)
    batches = set(catalog["batches"])
    for a in catalog["images"]+catalog["documents"]:
        if a["sample"] and a["batch"]:
            samples[a["sample"]].add(a["batch"])
    if "uploads" in catalog:
        for feed,rows in records.items():
            for original in rows:
                row = mapped(original,schema[feed])
                batch = row.get("batch")
                if not batch:
                    continue
                batches.add(batch)
                for field,lookup in (("sample",samples),("run",runs)):
                    if row.get(field):
                        lookup[row[field]].add(batch)
    else:
        for b in batches:
            runs["RUN-"+b[2:]].add(b)
    def unambiguous(lookup):
        return {key:next(iter(v)) for key,v in lookup.items() if len(v)==1}
    return dict(catalog,batches=sorted(batches),samples=unambiguous(samples),runs=unambiguous(runs))


def load_database(path,raw=RAW,schema=None):
    schema = schema or load_json(DOCS/"feed_schemas.json")
    records = records_by_feed(raw)
    catalog = reference_catalog(load_json(raw/"catalog.json"),records,schema)
    db = sqlite3.connect(path)
    try:
        db.executescript((DOCS/"schema.sql").read_text())
        db.executemany("INSERT INTO batches VALUES (?)", [(b,) for b in catalog["batches"]])
        db.executemany("INSERT INTO runs VALUES (?,?)", catalog["runs"].items())
        db.executemany("INSERT INTO samples VALUES (?,?)", catalog["samples"].items())
        for kind in ("images","documents"):
            for a in catalog[kind]:
                sample = a["sample"] if catalog["samples"].get(a["sample"])==a["batch"] and a["sample"] else None
                db.execute("INSERT INTO assets VALUES (?,?,?,?,?)",(a["id"],a["batch"] or None,sample,a["path"],kind))
        for rule in schema["criteria"].values():
            db.execute("INSERT INTO criteria VALUES (?,?,?,?,?)",[rule.get(k) for k in ("method","test","time_min","unit","lower_bound")])
        for feed in FEEDS:
            columns = [r[1] for r in db.execute(f"PRAGMA table_info({feed})") if r[1]!="locator"]
            variants = defaultdict(set)
            for original in records[feed]:
                variants[mapped(original,schema[feed]).get("id")].add(tuple(original.items()))
            seen = set()
            for line,original in enumerate(records[feed],2):
                row = mapped(original,schema[feed])
                locator = f"{feed}.csv#{line}"
                initial = issues(feed,row,schema,catalog)
                corrections = []
                rule = schema.get("corrections",{}).get(feed,{})
                field = rule.get("field")
                aliases = catalog["batch_aliases"] if rule.get("lookup")=="catalog.batch_aliases" else rule.get("aliases",{})
                if initial and row.get(field) in aliases:
                    before = row[field]
                    row[field] = aliases[before]
                    corrections.append(dict(field=field,before=before,after=row[field],rule=f"{feed}.{field}@{schema['version']}",evidence=rule.get("lookup","saved schema")))
                remaining = issues(feed,row,schema,catalog)
                if len(variants[row.get("id")])>1:
                    remaining.append("Conflicting source records share the same ID")
                identity = tuple(original.items())
                status = "Duplicate" if identity in seen else "Quarantined" if remaining else "Corrected" if initial else "Accepted"
                seen.add(identity)
                db.execute("INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?)",(locator,feed,row.get("id"),status,*map(json.dumps,(original,row,initial,remaining,corrections))))
                if status in ("Accepted","Corrected"):
                    row["timestamp"] = datetime.fromisoformat(row["timestamp"]).astimezone(timezone.utc).isoformat()
                    db.execute(f"INSERT INTO {feed} ({','.join(columns)},locator) VALUES ({','.join('?' for _ in range(len(columns)+1))})",[row.get(k) for k in columns]+[locator])
        db.commit()
    finally:
        db.close()


def read_db(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)
    db.row_factory = sqlite3.Row
    return db
