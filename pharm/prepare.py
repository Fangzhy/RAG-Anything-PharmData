"""Build a portable, versioned investigation bundle with python -m pharm.prepare."""
import asyncio
import hashlib
import importlib.metadata
import os
import shutil
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

import numpy as np
from PIL import Image

from pharm.catalog import BUILD, DATA, RAW, load_json, save_json
from pharm.encoders import CLIP_REV, TEXT_REV, encode_text, encode_visual
from pharm.graph import build_graph, project_graph
from pharm.validation import load_database, read_db


def active():
    return BUILD / load_json(BUILD / "active.json")["build"]


def parse_reports(catalog, folder):
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter, NativePdfFormatOption
    converter = DocumentConverter(format_options={InputFormat.PDF: NativePdfFormatOption()})
    chunks = []
    for report in catalog["documents"]:
        doc = converter.convert(RAW / report["path"]).document
        destination = folder / "parsed" / report["id"]
        destination.parent.mkdir(exist_ok=True)
        doc.save_as_json(destination.with_suffix(".json"))
        doc.save_as_markdown(destination.with_suffix(".md"))
        for item, _ in doc.iterate_items():
            text = getattr(item,"text","")
            if item.label.value == "table":
                text = item.export_to_markdown(doc=doc)
            if not text.strip():
                continue
            where = f"page {item.prov[0].page_no}, " if item.prov else ""
            chunks.append(dict(id=f"C-{len(chunks)+1:03}", document=report["id"], kind="passage", batch=report["batch"],
                sample=report["sample"], path=report["path"], locator=f"{report['path']}#{where}{item.self_ref}", text=text))
    return chunks


@contextmanager
def staging_directory():
    # Inherit the workspace ACL so a published Windows bundle can be opened by other runtimes.
    directory = BUILD / (".stage-" + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def build(*, online=False):
    BUILD.mkdir(parents=True, exist_ok=True)
    # A fresh directory is published only after all build artifacts are complete.
    with staging_directory() as stage:
        folder = Path(stage) / "bundle"
        folder.mkdir()
        catalog = load_json(RAW / "catalog.json")
        for path, digest in load_json(DATA / "manifest.json").items():
            if hashlib.sha256((RAW / path).read_bytes()).hexdigest() != digest:
                raise ValueError(f"Source checksum mismatch for {path}")
        load_database(folder / "study.sqlite")
        chunks = parse_reports(catalog, folder)
        images = [dict(id=a["id"],kind="image",batch=a["batch"],sample=a["sample"],path=a["path"],locator=a["path"],text=a["description"]) for a in catalog["images"]]
        notes = [dict(a,id="NOTE-"+a["sample"],kind="note",locator="catalog.json#"+a["id"]) for a in images]
        texts = chunks + notes
        visual = images + notes
        save_json(folder / "items.json", {"text":texts,"visual":visual})
        pixels = []
        for item in images:
            with Image.open(RAW / item["path"]) as img:
                pixels.append(img.convert("RGB"))
        np.savez_compressed(folder / "vectors.npz", text=encode_text([i["text"] for i in texts]),
            visual=np.concatenate([encode_visual(pixels,images=True),encode_visual([a["text"] for a in notes])]))
        with closing(read_db(folder / "study.sqlite")) as db:
            graph = asyncio.run(build_graph(catalog,chunks,db,online))
        save_json(folder / "graph.json",graph)
        asyncio.run(project_graph(graph,folder / "lightrag"))
        save_json(folder / "build.json",dict(study=catalog["version"], schema="1.0",text_revision=TEXT_REV,clip_revision=CLIP_REV,
            chunks=len(chunks),images=len(images),edges=len(graph["edges"]),extraction=graph["extraction"],
            packages={name:importlib.metadata.version(name) for name in ("docling","lightrag-hku","sentence-transformers","open-clip-torch")}))
        name = "study-"+uuid.uuid4().hex[:12]
        folder.rename(BUILD / name)
        pointer = Path(stage) / "active.json"
        save_json(pointer, {"build":name})
        os.replace(pointer,BUILD / "active.json")
    return active()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--online",action="store_true",help="Use OpenRouter for source-supported observation extraction")
    print(build(online=parser.parse_args().online))
