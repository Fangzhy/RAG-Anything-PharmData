import json
from pathlib import Path

import streamlit as st

from contextlib import closing

from pharm.catalog import DATA, load_json
from pharm.study import source as raw_source
from pharm.validation import read_db
from pharm.workspace import current_build, csv_content
from pharm.retrieval import graph_search, sql_search, vector_search


def inputs(prefix, default, folder=None, *, demo_image=False):
    folder = folder or current_build()
    query = st.text_input("Question or search terms", default, key=prefix+"query")
    left, right = st.columns(2)
    with closing(read_db(folder/"study.sqlite")) as db:
        batches = [r[0] for r in db.execute("SELECT batch FROM batches ORDER BY batch")]
    batch = left.selectbox("Batch filter", ["All batches"]+batches,key=prefix+"batch")
    weight = right.slider("Text weight (%)",0,100,50,help="0 uses OpenCLIP only. 100 uses sentence-transformer text only.",key=prefix+"weight")
    pick = prefix+"-demo-selected"
    def uploaded():
        st.session_state[pick] = False
    box, controls = st.columns([3,1],vertical_alignment="center") if demo_image else (st,None)
    upload = box.file_uploader("Optional inspection image",type=["png","jpg","jpeg","webp"],max_upload_size=8,key=prefix+"image",on_change=uploaded)
    if controls and controls.button("Use demo image",key=prefix+"-demo-image"):
        st.session_state[pick] = True
    image = upload.getvalue() if upload else None
    if demo_image and st.session_state.get(pick):
        if controls.button("Clear demo image",key=prefix+"-clear-image"):
            st.session_state[pick] = False
        else:
            image = (DATA/"evaluation/query-chipped.png").read_bytes()
            box.image(image,caption="Demo query · chipped tablet",width=160)
    return query.strip(),image,None if batch=="All batches" else batch,weight/100


def display_items(items, prefix, folder=None):
    raw_dir = raw_source(folder or current_build())
    catalog = load_json(raw_dir/"catalog.json")
    paths = {"catalog.json","eln.csv","lims.csv","sensor.csv"}
    paths.update(a["path"] for a in catalog["images"]+catalog["documents"])
    for i, item in enumerate(items):
        with st.expander(f"{item['id']} · {item['batch']} · {item['kind']}",expanded=i==0):
            st.write(item["text"])
            st.caption(item["locator"])
            if "channel" in item:
                st.caption(f"Match: {item['channel']} · group score {item['score']:.5f}")
            if "query" in item:
                st.code(item["query"].strip(),language="sql")
                st.caption(json.dumps(item["parameters"]))
            path, _, anchor = item["locator"].partition("#")
            if path not in paths:
                continue
            raw = raw_dir/path
            if not raw.is_file():
                continue
            if path.endswith(".csv") and anchor.isdigit():
                records = csv_content(raw.read_bytes())[1]
                index = int(anchor)-2
                if 0<=index<len(records):
                    st.json(records[index],expanded=False)
            if item.get("kind")=="image" and item.get("path") in paths:
                st.image(str(raw_dir/item["path"]),width=250)
            if raw.is_file():
                st.download_button("Open original file", raw.read_bytes(),raw.name,key=f"{prefix}-{i}-{item['id']}")


def show():
    st.title("Search evidence")
    source = st.radio("Search source",["Vector","SQL","Graph"],horizontal=True)
    folder = current_build()
    if folder is None:
        st.info("Apply a schema and ontology on Process data to search this study.")
        return
    query, image, batch, weight = inputs("search","chipped tablet appearance",folder,demo_image=True)
    if st.button("Search",type="primary"):
        st.session_state.pop("search_result",None)
        if image is None and not query and not batch:
            st.warning("Enter a question, select a batch, or upload an image.")
        elif image and source != "Vector" and not (query or batch):
            st.info("Use Vector to find a similar sample, then select its batch for SQL or graph search.")
        else:
            try:
                if source == "Vector":
                    result = vector_search(folder,query,image,batch,weight)
                elif source == "SQL":
                    result = sql_search(folder,query,batch)
                else:
                    result = graph_search(folder,query,batch)
                st.session_state.search_result = (source,result)
            except (ValueError,OSError,RuntimeError) as exc:
                st.error(f"Search unavailable. {exc}")
    if "search_result" in st.session_state:
        selected, result = st.session_state.search_result
        st.caption(f"{len(result)} evidence items · {selected}")
        if not result:
            st.info("No matching evidence. Try a batch ID, dissolution result, sensor channel, or visual description.")
        display_items(result,"search-hit")
