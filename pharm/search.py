import json
from pathlib import Path

import streamlit as st

from pharm.catalog import RAW, load_json, rows
from pharm.prepare import active
from pharm.retrieval import graph_search, sql_search, vector_search


def inputs(prefix, default):
    query = st.text_input("Question or search terms", default, key=prefix+"query")
    left, right = st.columns(2)
    batch = left.selectbox("Batch filter", ["All batches"]+load_json(RAW / "catalog.json")["batches"],key=prefix+"batch")
    weight = right.slider("Text weight (%)",0,100,50,help="0 uses OpenCLIP only. 100 uses sentence-transformer text only.",key=prefix+"weight")
    upload = st.file_uploader("Optional inspection image",type=["png","jpg","jpeg","webp"],max_upload_size=8,key=prefix+"image")
    return query.strip(), upload.getvalue() if upload else None, None if batch=="All batches" else batch, weight/100


def display_items(items, prefix):
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
            raw = RAW / path
            if path.endswith(".csv") and anchor.isdigit():
                st.json(rows(Path(path).stem)[int(anchor)-2], expanded=False)
            if item.get("kind") == "image":
                st.image(str(RAW / item["path"]),width=250)
            if raw.is_file():
                st.download_button("Open original file", raw.read_bytes(),raw.name,key=f"{prefix}-{i}-{item['id']}")


def show():
    st.title("Search evidence")
    source = st.radio("Search source",["Vector","SQL","Graph"],horizontal=True)
    query, image, batch, weight = inputs("search","chipped tablet appearance")
    if st.button("Search",type="primary"):
        st.session_state.pop("search_result",None)
        if image is None and not query and not batch:
            st.warning("Enter a question, select a batch, or upload an image.")
        elif image and source != "Vector" and not (query or batch):
            st.info("Use Vector to find a similar sample, then select its batch for SQL or graph search.")
        else:
            try:
                folder = active()
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
