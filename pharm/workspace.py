"""Immutable input snapshots for a single Streamlit session."""
import csv
import hashlib
import io
import shutil
import uuid
from pathlib import Path

import streamlit as st
from PIL import Image

from pharm.catalog import DATA, RAW, load_json, save_json

IMAGES = {"png","jpeg","jpg","webp"}
TYPES = ["csv","pdf","docx",*sorted(IMAGES)]
FEEDS = ("lims","eln","sensor")


def home():
    if "study_workspace" not in st.session_state:
        st.session_state.study_workspace = DATA/"workspaces"/uuid.uuid4().hex
    return st.session_state.study_workspace


def invalidate():
    for key in ("search_result","ask_result","comparison","study_build"):
        st.session_state.pop(key,None)


def current_build():
    if "study_build" in st.session_state:
        return st.session_state.study_build
    if st.session_state.get("raw_selection",RAW)==RAW:
        from pharm.prepare import active
        return active()
    return None


def select_build(folder):
    invalidate()
    st.session_state.study_build = folder


def set_raw(path):
    invalidate()
    st.session_state.raw_selection = path


def demo_button(prefix,container=st):
    if container.button("Use Demo Data",key=prefix+"-demo"):
        set_raw(RAW)


def csv_content(content):
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"),newline=""))
    headers = reader.fieldnames or []
    if not headers or any(not h.strip() for h in headers) or len(set(headers))!=len(headers):
        raise ValueError("CSV files need unique, nonempty column headers.")
    records = list(reader)
    if any(None in row for row in records):
        raise ValueError("A CSV row contains more values than headers.")
    return headers,records


def feed_type(name,headers,choice):
    if choice!="Auto-detect":
        return choice.lower()
    for feed,marker in (("lims","test"),("sensor","channel"),("eln","operator")):
        if feed in Path(name).stem.lower() or marker in headers:
            return feed
    raise ValueError(f"Select the CSV source type for {name}.")


def import_files(destination,previous,files,choice,batch="",sample=""):
    destination.mkdir(parents=True)
    catalog = dict(version="uploaded study",batches=[],batch_aliases={},images=[],documents=[],uploads=[])
    if previous and previous!=RAW:
        shutil.copytree(previous,destination,dirs_exist_ok=True)
        catalog = load_json(destination/"catalog.json")
    for name,content in files:
        name = Path(name.replace("\\","/")).name
        suffix = Path(name).suffix.lower().lstrip(".")
        if suffix not in TYPES:
            raise ValueError(f"Unsupported file type for {name}.")
        digest = hashlib.sha256(content).hexdigest()
        if suffix=="csv":
            headers,records = csv_content(content)
            kind = feed_type(name,headers,choice)
        else:
            kind = "images" if suffix in IMAGES else "documents"
        if any(u["hash"]==digest and u["kind"]==kind and u["batch"]==batch and u["sample"]==sample for u in catalog["uploads"]):
            continue
        tag = uuid.uuid4().hex[:12]
        relative = f"originals/{tag}.{suffix}"
        path = destination/relative
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
        catalog["uploads"].append(dict(name=name,path=relative,hash=digest,kind=kind,batch=batch,sample=sample))
        if suffix=="csv":
            feed = destination/f"{kind}.csv"
            if feed.exists():
                old_headers,old = csv_content(feed.read_bytes())
                headers = list(dict.fromkeys(old_headers+headers))
                records = old+records
            with feed.open("w",encoding="utf-8",newline="") as out:
                writer = csv.DictWriter(out,headers)
                writer.writeheader()
                writer.writerows(records)
            catalog["batches"].extend(r["batch"] for r in records if r.get("batch"))
        else:
            if kind=="images":
                with Image.open(path) as image:
                    image.verify()
            item = dict(id=("IMG-" if kind=="images" else "DOC-")+tag,batch=batch,sample=sample,path=relative,title=name,description=name,preview=[])
            catalog[kind].append(item)
            if batch:
                catalog["batches"].append(batch)
    catalog["batches"] = sorted(set(catalog["batches"]))
    save_json(destination/"catalog.json",catalog)
    return destination


def raw_uploader(prefix):
    files = st.file_uploader("Upload raw data",type=TYPES,accept_multiple_files=True,key=prefix+"-files",help="LIMS, ELN or sensor CSVs, inspection images, and PDF or Word reports.")
    if files:
        choice = "Auto-detect"
        batch = sample = ""
        if any(f.name.lower().endswith(".csv") for f in files):
            choice = st.selectbox("CSV source type",["Auto-detect","LIMS","ELN","Sensor"],key=prefix+"-type")
        if any(not f.name.lower().endswith(".csv") for f in files):
            left,right = st.columns(2)
            batch = left.text_input("Batch for these attachments (optional)",key=prefix+"-batch").strip()
            sample = right.text_input("Sample for these attachments (optional)",key=prefix+"-sample").strip()
        if st.button("Load uploaded files",key=prefix+"-load"):
            try:
                path = home()/("raw-"+uuid.uuid4().hex)
                set_raw(import_files(path,st.session_state.get("raw_selection"),[(f.name,f.getvalue()) for f in files],choice,batch,sample))
                st.success("Uploaded files loaded.")
            except (ValueError,OSError,csv.Error) as exc:
                st.error(str(exc))
    return st.session_state.get("raw_selection")
