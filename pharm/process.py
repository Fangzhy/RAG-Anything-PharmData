import json
from contextlib import closing
import importlib.util

import pandas as pd
import streamlit as st

from pharm.catalog import BUILD, load_json
from pharm.prepare import active, build
from pharm.validation import FEEDS, read_db


def show():
    st.title("Process data")
    st.write("Follow each source row from the first schema check through correction and revalidation.")
    with st.expander("Rebuild study from raw files"):
        if importlib.util.find_spec("docling"):
            online = st.checkbox("Use OpenRouter for report observation extraction")
            if st.button("Run processing pipeline"):
                try:
                    with st.spinner("Validating, parsing, embedding and building the graph…"):
                        build(online=online)
                    st.success("Published the new study build.")
                except Exception as exc:
                    st.error(f"Build did not finish. {exc}")
        else:
            st.info("This installation serves the prepared run. Install requirements-dev.txt locally to rebuild.")
    if not (BUILD / "active.json").is_file():
        st.info("Run the processing pipeline to create the first study build.")
        return
    folder = active()
    report = load_json(folder / "build.json")
    validation, documents, graph = st.tabs(["Validation ledger", "Document parsing and vectors", "Knowledge graph"])
    with validation, closing(read_db(folder / "study.sqlite")) as db:
        feed = st.selectbox("Source feed", FEEDS)
        ledger = pd.read_sql_query("SELECT * FROM audit WHERE feed=? ORDER BY rowid",db,params=[feed])
        counts = ledger.status.value_counts()
        cols = st.columns(4)
        for col, status in zip(cols, ("Accepted","Corrected","Quarantined","Duplicate")):
            col.metric(status,int(counts.get(status,0)))
        st.caption(f"{len(ledger)} input rows · {sum(ledger.initial_errors != '[]')} failed the first schema check")
        status = st.radio("Disposition", list(counts.index), horizontal=True)
        candidates = ledger[ledger.status == status]
        locator = st.selectbox("Source row", candidates.locator.tolist())
        record = candidates[candidates.locator == locator].iloc[0]
        before, after = st.columns(2)
        before.write("Original row")
        before.json(json.loads(record.original))
        after.write("After correction")
        after.json(json.loads(record.final))
        details = {"Initial failures":json.loads(record.initial_errors),"Applied rules":json.loads(record.corrections),"Remaining issues":json.loads(record.final_errors)}
        st.json(details)
        if status == "Quarantined":
            st.info("Resolve the remaining issues using the original instrument or notebook record. This row is excluded from measurement queries.")
    with documents:
        st.caption(f"Docling · {report['chunks']} document chunks · {report['images']} image embeddings")
        files = sorted((folder / "parsed").glob("*.md"))
        item = st.selectbox("Parsed document", files, format_func=lambda path:path.stem)
        st.markdown(item.read_text(encoding="utf-8"))
        st.download_button("Download Docling JSON", item.with_suffix(".json").read_bytes(), item.with_suffix(".json").name)
        st.json(report)
    with graph:
        graph_data = load_json(folder / "graph.json")
        st.caption(f"{len(graph_data['nodes'])} entities · {report['edges']} cited relationships · {report['extraction']}")
        st.dataframe(graph_data["edges"], hide_index=True)
