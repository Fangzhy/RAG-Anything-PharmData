"""Publish isolated, immutable processing results for the selected raw snapshot."""
import asyncio
import shutil
import uuid
from contextlib import closing
from pathlib import Path

import numpy as np
from PIL import Image

from pharm.catalog import DOCS, RAW, load_json, save_json
from pharm.encoders import encode_text, encode_visual
from pharm.graph import build_graph, project_graph
from pharm.prepare import active, parse_reports
from pharm.validation import load_database, read_db


def source(folder):
    info = folder/"input.json"
    return Path(load_json(info)["raw"]) if info.exists() else RAW


def contracts(folder):
    schema = folder/"schema.json"
    onto = folder/"ontology.json"
    return load_json(schema if schema.exists() else DOCS/"feed_schemas.json"),load_json(onto if onto.exists() else DOCS/"ontology.json")


def media(folder,raw,catalog,chunks,embed):
    images = [dict(id=a["id"],kind="image",batch=a["batch"],sample=a["sample"],path=a["path"],locator=a["path"],text=a["description"]) for a in catalog["images"]] if embed else []
    notes = [dict(a,id="NOTE-"+a["id"],kind="note",locator="catalog.json#"+a["id"]) for a in images]
    text = chunks+notes
    save_json(folder/"items.json",{"text":text,"visual":images+notes})
    visual = []
    if images:
        for start in range(0,len(images),8):
            pixels = []
            for a in images[start:start+8]:
                with Image.open(raw/a["path"]) as img:
                    pixels.append(img.convert("RGB"))
            visual.append(encode_visual(pixels,images=True))
        visual.append(encode_visual([a["text"] for a in notes]))
    np.savez_compressed(folder/"vectors.npz",
        text=encode_text([a["text"] for a in text]) if text else np.empty((0,384),dtype="float32"),
        visual=np.concatenate(visual) if visual else np.empty((0,512),dtype="float32"))


def validate_graph(graph,onto):
    nodes,edges = graph["nodes"],graph["edges"]
    if any(not isinstance(n,str) or not n.strip() or t not in onto["classes"] for n,t in nodes.items()):
        raise ValueError("Each entity needs a unique ID and a declared ontology class.")
    ids = set()
    for edge in edges:
        if not all(isinstance(edge.get(k),str) and edge[k].strip() for k in ("id","src","tgt","predicate","text","locator")) or edge["id"] in ids:
            raise ValueError("Each relationship needs a unique ID, endpoints, predicate, assertion and source.")
        ids.add(edge["id"])
        if [nodes.get(edge["src"]),nodes.get(edge["tgt"])]!=onto["predicates"].get(edge["predicate"]):
            raise ValueError(f"Check endpoints and ontology domain/range on {edge['id']}.")
    return graph


def merge_edits(previous,generated):
    base = load_json(previous/"base_graph.json")
    edited = load_json(previous/"graph.json")
    for section in ("nodes","edges"):
        def keyed(g):
            return g[section] if section=="nodes" else {e["id"]:e for e in g[section]}
        before,after,now = keyed(base),keyed(edited),dict(keyed(generated))
        for k in before.keys()-after.keys():
            now.pop(k,None)
        now.update({k:v for k,v in after.items() if before.get(k)!=v})
        generated[section] = now if section=="nodes" else [e for e in now.values() if e["src"] in generated["nodes"] and e["tgt"] in generated["nodes"]]
    return generated


def process_inputs(root,raw,schema,ontology,*,embed=False,previous=None,online=False):
    folder = root/("study-"+uuid.uuid4().hex)
    folder.mkdir(parents=True)
    catalog = load_json(raw/"catalog.json")
    save_json(folder/"input.json",{"raw":str(raw)})
    save_json(folder/"schema.json",schema)
    save_json(folder/"ontology.json",ontology)
    if embed and previous:
        if source(previous)!=raw or contracts(previous)!=(schema,ontology):
            raise ValueError("Apply the current schema and ontology to these inputs first.")
        shutil.copyfile(previous/"study.sqlite",folder/"study.sqlite")
    else:
        load_database(folder/"study.sqlite",raw,schema)
    chunks = parse_reports(catalog,folder,raw) if embed and catalog["documents"] else []
    media(folder,raw,catalog,chunks,embed)
    with closing(read_db(folder/"study.sqlite")) as db:
        graph = asyncio.run(build_graph(catalog,chunks,db,online,ontology))
    save_json(folder/"base_graph.json",graph)
    if embed and previous and (previous/"base_graph.json").exists():
        graph = merge_edits(previous,graph)
    publish_graph(folder,graph,ontology)
    save_json(folder/"build.json",dict(study=catalog["version"],schema=schema["version"],chunks=len(chunks),images=len(catalog["images"]) if embed else 0,
        edges=len(graph["edges"]),extraction=graph["extraction"],embedded=embed))
    return folder


def publish_graph(folder,graph,ontology):
    validate_graph(graph,ontology)
    asyncio.run(project_graph(graph,folder/"lightrag"))
    save_json(folder/"graph.json",graph)


def save_graph(root,previous,graph):
    _,ontology = contracts(previous)
    validate_graph(graph,ontology)
    folder = root/("study-"+uuid.uuid4().hex)
    shutil.copytree(previous,folder,ignore=shutil.ignore_patterns("lightrag"))
    if not (folder/"base_graph.json").exists():
        shutil.copyfile(previous/"graph.json",folder/"base_graph.json")
    publish_graph(folder,graph,ontology)
    info = load_json(folder/"build.json")
    save_json(folder/"build.json",dict(info,edges=len(graph["edges"])))
    return folder
