import io
import re
from collections import defaultdict
from contextlib import closing
from functools import lru_cache

import numpy as np
from PIL import Image

from pharm.catalog import load_json
from pharm.encoders import encode_text, encode_visual
from pharm.validation import read_db

SOURCES = ("SQL", "Vector", "Graph")
OPENING = "Which batches had low dissolution results, and what did the lab notes and inspection images show?"


def identifiers(question, batch=None):
    text = question.upper()
    sample = re.search(r"\bS-\d{3}-[AB]\b", text)
    batch_match = re.search(r"\bB-\d{3}\b", text)
    return batch or (batch_match.group() if batch_match else None), sample.group() if sample else None


def evidence(identifier, source, batch, sample, text, locator, **extra):
    return dict(id=identifier, source=source, batch=batch, sample=sample, text=text, locator=locator, **extra)


def sql_search(folder, question, batch=None, limit=12):
    batch, sample = identifiers(question,batch)
    q = question.lower()
    scoped = bool(batch or sample)
    sensor = any(w in q for w in ("sensor","temperature","force","excursion"))
    eln = any(w in q for w in ("notebook","eln","observation","lab note"))
    lab = any(w in q for w in ("assay","dissol","measured","result","below","low"))
    found = []
    with closing(read_db(folder / "study.sqlite")) as db:
        if lab or (scoped and not sensor and not eln):
            test = "Assay" if "assay" in q and "dissol" not in q else "Dissolution"
            low_only = any(w in q for w in ("low","below","flag","failed"))
            query = """SELECT l.*, c.lower_bound FROM lims l JOIN criteria c USING(method)
                       WHERE l.test=? COLLATE NOCASE AND (? IS NULL OR l.batch=?) AND (? IS NULL OR sample=?)
                       AND (?=0 OR value<c.lower_bound) ORDER BY value,id LIMIT ?"""
            params = (test,batch,batch,sample,sample,int(low_only),limit)
            for r in db.execute(query,params):
                label = f" at {r['time_min']} min" if test == "Dissolution" else ""
                criterion = f" (study lower bound {r['lower_bound']:g}{r['unit']})" if r["lower_bound"] is not None else ""
                found.append(evidence("SQL-"+r["id"],"SQL",r["batch"],r["sample"],f"{r['sample']} {r['test']}{label}: {r['value']:g}{r['unit']}{criterion}.",r["locator"],query=query,parameters=params,kind="result"))
        target = batch or ("B-"+sample.split("-")[1] if sample else None)
        # Scope follow-up records to the batches established by the measurement query.
        scopes = [target] if target else (list(dict.fromkeys(i["batch"] for i in found)) if lab else [None])
        for scope in scopes:
            if sensor:
                channel = "Press force" if "force" in q else "Temperature"
                query = """SELECT batch,run,channel,unit,count(*) AS n,min(value) AS lo,max(value) AS hi,
                           min(timestamp) AS start,max(timestamp) AS end FROM sensor
                           WHERE channel=? AND (? IS NULL OR batch=?) GROUP BY batch,run,channel,unit ORDER BY batch LIMIT ?"""
                params = (channel,scope,scope,limit)
                for r in db.execute(query, params):
                    found.append(evidence(f"SQL-{r['run']}-{channel}","SQL",r["batch"],None,
                        f"{r['run']} {channel}: {r['lo']:g} to {r['hi']:g} {r['unit']} across {r['n']} accepted readings.",
                        f"sensor.csv · {r['start']} to {r['end']}",kind="interval",query=query,parameters=params))
            if eln:
                query = "SELECT * FROM eln WHERE (? IS NULL OR batch=?) ORDER BY id LIMIT ?"
                params = (scope,scope,limit)
                for r in db.execute(query,params):
                    found.append(evidence("SQL-"+r["id"],"SQL",r["batch"],None,r["note"],r["locator"],kind="note",query=query,parameters=params))
    return found[:limit]


@lru_cache(maxsize=2)
def indexes(folder):
    with np.load(folder / "vectors.npz", allow_pickle=False) as vectors:
        return load_json(folder / "items.json"), {name:vectors[name] for name in vectors.files}


def image_input(content):
    if len(content) > 8_000_000:
        raise ValueError("Select an image under 8 MB.")
    with Image.open(io.BytesIO(content)) as img:
        if img.width * img.height > 16_000_000:
            raise ValueError("Select an image under 16 megapixels.")
        return img.convert("RGB")


def vector_search(folder, question, image=None, batch=None, weight=0.5, limit=5):
    items, vectors = indexes(folder)
    batch, sample = identifiers(question,batch)
    w = weight if question.strip() else 0.0
    if not question.strip() and image is None:
        return []
    scores = defaultdict(float)
    matched = defaultdict(dict)

    def rank(space, query, share):
        ordered = np.argsort(-(vectors[space] @ query),kind="stable")
        ranks = {}
        for idx in ordered:
            item = items[space][idx]
            if (batch and item["batch"] != batch) or (sample and item["sample"] != sample):
                continue
            group = item["sample"] or item["path"]
            if group not in ranks:
                ranks[group] = len(ranks)+1
                scores[group] += share / (60+ranks[group])
            key = (space,item["kind"])
            matched[group].setdefault(key,item)

    if w > 0 and items["text"]:
        rank("text",encode_text([question])[0],w)
    if w < 1 and items["visual"]:
        parts = []
        if question.strip():
            parts.append(encode_visual([question])[0])
        if image is not None:
            parts.append(encode_visual([image_input(image)],images=True)[0])
        q = np.mean(parts,axis=0)
        rank("visual",q / max(np.linalg.norm(q),1e-9),1-w)
    found = []
    for group in sorted(scores,key=lambda g:(-scores[g],g))[:limit]:
        direct = {}
        for (space,_),item in matched[group].items():
            if item["id"] in direct:
                direct[item["id"]]["channel"] += " + "+space
            else:
                direct[item["id"]] = dict(item,source="Vector",channel=space,score=round(scores[group],6))
        found.extend(direct.values())
        if image is not None and not any(i["kind"] == "passage" for i in direct.values()):
            linked = next((i for i in items["text"] if i["kind"]=="passage" and i["sample"]==group and "inspection recorded" in i["text"].lower()),None)
            if linked:
                found.append(dict(linked,source="Vector",channel="linked by sample",score=round(scores[group],6)))
    return found


def graph_search(folder, question, batch=None, limit=10):
    batch, sample = identifiers(question,batch)
    edges = load_json(folder / "graph.json")["edges"]
    q = question.lower()
    tokens = set(re.findall(r"[a-z]{3,}",q)) - {"the","and","which","did","show","what","for","had","are","with"}
    preference = set()
    if any(k in q for k in ("appearance","image","inspection","observation","chipped","mottled","lab notes")):
        preference.update(("hasObservation","depicts","documents"))
    if "run" in q or "process" in q:
        preference.add("processes")
    if any(k in q for k in ("sample","result","test","dissolution")):
        preference.update(("hasSample","hasResult"))
    candidates = []
    for e in edges:
        if (batch and e["batch"] != batch) or (sample and sample not in (e["src"],e["tgt"])):
            continue
        matches = tokens.intersection(re.findall(r"[a-z]{3,}",e["text"].lower()))
        score = len(matches) + 2*(e["predicate"] in preference) + (e["predicate"]=="hasObservation" and bool(preference))
        if score or batch or sample:
            candidates.append((score,e))
    candidates.sort(key=lambda pair:(-pair[0],pair[1]["id"]))
    return [evidence(e["id"],"Graph",e["batch"],sample,f"{e['src']} → {e['predicate']} → {e['tgt']}. {e['text']}",e["locator"],kind="relationship") for _,e in candidates[:limit]]
