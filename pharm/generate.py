"""Regenerate the deterministic synthetic study with python -m pharm.generate."""
import csv
import hashlib
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from docx import Document
from PIL import Image, ImageDraw, ImageFilter
from reportlab.lib import colors
from reportlab.pdfgen.canvas import Canvas

from pharm.catalog import DATA, RAW, save_json


def write_csv(name, records):
    with (RAW / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def tablet(path, appearance, seed):
    rng = random.Random(seed)
    image = Image.new("RGB", (320, 220), "#243237")
    draw = ImageDraw.Draw(image)
    dx, dy = rng.randint(-10, 10), rng.randint(-8, 8)
    draw.ellipse((62+dx, 57+dy, 267+dx, 177+dy), fill="#17272a")
    draw.ellipse((58+dx, 48+dy, 260+dx, 167+dy), fill="#e4d9be", outline="#c0ad90", width=4)
    draw.line((159+dx, 60+dy, 159+dx, 153+dy), fill="#bba992", width=3)
    if appearance == "chipped":
        draw.polygon([(54+dx, 68+dy), (99+dx, 70+dy), (85+dx, 92+dy), (65+dx, 99+dy), (50+dx, 112+dy)], fill="#243237")
    if appearance == "mottled":
        for _ in range(40):
            x, y = rng.randint(98, 215)+dx, rng.randint(76, 135)+dy
            draw.ellipse((x,y,x+4,y+3), fill="#ab977c")
    image.filter(ImageFilter.GaussianBlur(0.8)).save(path)


def report(path, title, body, sample, appearance):
    if path.suffix == ".pdf":
        canvas = Canvas(str(path), invariant=True, pagesize=(595, 842))
        canvas.setFillColor(colors.HexColor("#18534c"))
        canvas.setFont("Helvetica-Bold", 18)
        canvas.drawString(48, 756, title)
        canvas.setFont("Helvetica", 12)
        for i, line in enumerate(body):
            canvas.drawString(48, 710-i*24, line)
        canvas.save()
    else:
        doc = Document()
        doc.add_heading(title, 0)
        for line in body:
            doc.add_paragraph(line)
        table = doc.add_table(rows=2, cols=2)
        for row, values in zip(table.rows, [("Sample", "Appearance"), (sample, appearance)]):
            for cell, value in zip(row.cells, values):
                cell.text = value
        doc.save(path)


def generate():
    for folder in ("images", "reports"):
        (RAW / folder).mkdir(parents=True, exist_ok=True)
    rng = random.Random(581)
    feeds = {name: [] for name in ("eln", "lims", "sensor")}
    assets, documents, aliases, batches = [], [], {}, []
    for number in range(1, 21):
        batch, run = f"B-{number:03}", f"RUN-{number:03}"
        batches.append(batch)
        aliases[f"LOT{number:03}"] = batch
        start = datetime(2026, 3, number, 8, tzinfo=timezone.utc)
        appearance = "chipped" if number in (1, 2) else "mottled" if number % 4 == 0 else "intact"
        note = f"Visual inspection recorded a {appearance} tablet surface."
        feeds["eln"].append(dict(id=f"E-{number:03}", batch=batch, run=run, timestamp=start.isoformat(), operator=f"Analyst-{number%3+1}", note=note))
        for suffix in ("A", "B"):
            sample = f"S-{number:03}-{suffix}"
            img = f"images/{sample}.png"
            tablet(RAW / img, appearance, f"{sample}-image")
            assets.append(dict(id=f"IMG-{sample}", batch=batch, sample=sample, path=img, description=note))
            for test, method, time_min in [("Dissolution", "D30", 30), ("Assay", "A01", 0)]:
                value = (72.5 if number == 1 else round(rng.uniform(86, 96), 1)) if method == "D30" else round(rng.uniform(98, 102), 1)
                feeds["lims"].append(dict(id=f"{sample}-{method}", batch=batch, sample=sample, test=test, value=value, unit="%", method=method, time_min=time_min, timestamp=(start+timedelta(hours=2)).isoformat()))
        for minute in range(60):
            for channel, unit, val in [("Temperature", "Cel", 26), ("Press force", "kN", 11)]:
                excursion = 7 if number == 1 and channel == "Temperature" and 25 <= minute < 36 else 0
                feeds["sensor"].append(dict(id=f"H-{len(feeds['sensor'])+1:04}", batch=batch, run=run, channel=channel, value=round(val+excursion+rng.uniform(-0.4,0.4), 2), unit=unit, timestamp=(start+timedelta(minutes=minute)).isoformat(), equipment="Press-01"))
        if number <= 6:
            sample = f"S-{number:03}-A"
            title = f"Inspection report | {batch}"
            body = [f"Sample {sample} was collected during {run}.", note,
                    "A temperature excursion was recorded during this run." if number == 1 else "The observer recorded the appearance during routine sampling.",
                    "The inspection establishes appearance only."]
            path = f"reports/{batch}." + ("pdf" if number % 2 else "docx")
            report(RAW / path, title, body, sample, appearance)
            documents.append(dict(id=f"DOC-{batch}", batch=batch, sample=sample, path=path, title=title, preview=body))
    expected = {}
    for feed, records in feeds.items():
        n = len(records)
        repairable = [i for i,r in enumerate(records) if feed != "sensor" or r["channel"] == "Temperature"]
        repairs = set(rng.sample(repairable, round(n*0.15)))
        candidates = [i for i,r in enumerate(records) if i not in repairs and (feed != "sensor" or r["channel"] == "Press force") and (feed != "lims" or (r["method"] == "D30" and r["batch"] not in ("B-001","B-002")))]
        rejects = set(rng.sample(candidates, round(n*0.05)))
        expected[feed] = {"corrected": [], "quarantined": []}
        for i in sorted(repairs):
            r = records[i]
            expected[feed]["corrected"].append(r["id"])
            if feed == "eln":
                r["batch"] = "LOT" + r["batch"][-3:]
            else:
                r["unit"] = "percent" if feed == "lims" else "deg C"
        for i in sorted(rejects):
            r = records[i]
            expected[feed]["quarantined"].append(r["id"])
            r[{"eln":"run", "lims":"value", "sensor":"unit"}[feed]] = ""
        if feed == "sensor":
            records.append(records[0].copy())
        write_csv(feed, records)
    save_json(RAW / "catalog.json", dict(version="study-1", batches=batches, batch_aliases=aliases, images=assets, documents=documents))
    save_json(DATA / "evaluation" / "expected.json", expected)
    tablet(DATA / "evaluation" / "query-chipped.png", "chipped", 783)
    files = sorted(p for p in RAW.rglob("*") if p.is_file())
    save_json(DATA / "manifest.json", {p.relative_to(RAW).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


if __name__ == "__main__":
    generate()
