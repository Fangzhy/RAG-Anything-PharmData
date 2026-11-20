import json
from contextlib import closing

import pandas as pd
import streamlit as st

from pharm.catalog import RAW, load_json
from pharm.editors import contract_upload, graph_editor, load_demo, ontology_editor, schema_editor
from pharm.study import contracts, process_inputs, source
from pharm.validation import read_db
from pharm.workspace import current_build, demo_button, home, raw_uploader, select_build


def ledger_view(folder):
    with closing(read_db(folder/"study.sqlite")) as db:
        feeds = [r[0] for r in db.execute("SELECT DISTINCT feed FROM audit ORDER BY feed")]
        if not feeds:
            st.info("There are no tabular rows in this study.")
            return
        feed = st.selectbox("Source feed",feeds)
        ledger = pd.read_sql_query("SELECT * FROM audit WHERE feed=? ORDER BY rowid",db,params=[feed])
    counts = ledger.status.value_counts()
    for col,status in zip(st.columns(4),("Accepted","Corrected","Quarantined","Duplicate")):
        col.metric(status,int(counts.get(status,0)))
    st.caption(f"{len(ledger)} input rows · {sum(ledger.initial_errors != '[]')} failed the first schema check")
    status = st.radio("Disposition",list(counts.index),horizontal=True)
    candidates = ledger[ledger.status==status]
    locator = st.selectbox("Source row",candidates.locator.tolist())
    record = candidates[candidates.locator==locator].iloc[0]
    before,after = st.columns(2)
    before.write("Original row")
    before.json(json.loads(record.original))
    after.write("After correction")
    after.json(json.loads(record.final))
    st.json({"Initial failures":json.loads(record.initial_errors),"Applied rules":json.loads(record.corrections),"Remaining issues":json.loads(record.final_errors)})
    if status=="Quarantined":
        st.info("Resolve the remaining issues in the source record. This row is excluded from measurement queries.")


def controls():
    buttons = st.columns(3)
    demo_button("process",buttons[0])
    for col,kind in zip(buttons[1:],("schema","ontology")):
        if col.button("Use demo "+kind):
            load_demo(kind)
    raw = raw_uploader("process")
    if raw:
        catalog = load_json(raw/"catalog.json")
        st.caption("Selected data · "+("20-batch demo" if raw==RAW else ", ".join(u["name"] for u in catalog["uploads"])))
    contract_upload("schema",["json"])
    contract_upload("ontology",["json","owl","rdf","xml","ttl","nt"])
    with st.expander("Schema editor",expanded=(home()/"schema.json").exists()):
        schema = schema_editor()
    with st.expander("Ontology editor",expanded=(home()/"ontology.json").exists()):
        ontology = ontology_editor()
    ready = bool(raw and schema and ontology)
    current = current_build()
    matches = ready and current and source(current)==raw and contracts(current)==(schema,ontology)
    apply = st.button("Run pipeline to apply schema and ontology",disabled=not ready)
    online = st.checkbox("Use OpenRouter for report observation extraction",help="Sends parsed passages to your configured model.")
    embed = st.button("Run pipeline to apply parse and embed",disabled=not matches,help="Applies Docling to reports and encodes passages and inspection images.")
    if apply or embed:
        try:
            with st.spinner("Processing the selected files…"):
                folder = process_inputs(home(),raw,schema,ontology,embed=embed,previous=current if embed else None,online=online)
                select_build(folder)
            st.success("Saved processing results.")
            st.rerun()
        except Exception as exc:
            st.error(f"Processing did not finish. {exc}")


def show():
    st.title("Preprocess data")
    st.write("Follow each source row from the first schema check through correction and revalidation.")
    with st.expander("Preprocess data from raw files"):
        controls()
    folder = current_build()
    if folder is None:
        st.info("Select data, save a schema and ontology, then apply them to inspect the results.")
        return
    report = load_json(folder/"build.json")
    validation,documents,graph = st.tabs(["Validation ledger","Document parsing and vectors","Knowledge graph"])
    with validation:
        ledger_view(folder)
    with documents:
        st.caption(f"Docling · {report['chunks']} document chunks · {report['images']} image embeddings")
        files = sorted((folder/"parsed").glob("*.md"))
        if files:
            item = st.selectbox("Parsed document",files,format_func=lambda p:p.stem)
            st.markdown(item.read_text(encoding="utf-8"))
            st.download_button("Download Docling JSON",item.with_suffix(".json").read_bytes(),item.with_suffix(".json").name)
        elif not report.get("embedded",True):
            st.info("Run the parse and embed pipeline to index the selected reports and images.")
        st.json(report)
    with graph:
        graph_editor(folder,select_build)
