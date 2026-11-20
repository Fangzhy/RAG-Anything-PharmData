import pandas as pd
import streamlit as st

from pharm.catalog import load_json
from pharm.workspace import FEEDS, csv_content, demo_button, raw_uploader


def show():
    st.title("Explore raw data")
    st.write("Explore lab records, process readings, inspection images, and reports. Use the 20-batch demo or load your own files.")
    demo_button("explore")
    raw = raw_uploader("explore")
    if not raw:
        return
    catalog = load_json(raw/"catalog.json")
    batches = catalog["batches"]
    if "uploads" in catalog:
        batches = ["All batches"]+batches
        st.caption("Uploaded study · "+", ".join(u["name"] for u in catalog["uploads"]))
    batch = st.selectbox("Batch",batches)
    tables,inspection,reports = st.tabs(["Instrument exports","Inspection images","Lab reports"])
    with tables:
        feeds = [f for f in FEEDS if (raw/f"{f}.csv").exists()]
        if feeds:
            feed = st.radio("Export",[f.upper() if f!="sensor" else "Sensor" for f in feeds],horizontal=True).lower()
            path = raw/f"{feed}.csv"
            headers,records = csv_content(path.read_bytes())
            frame = pd.DataFrame(records,columns=headers)
            if batch!="All batches" and "batch" in frame:
                frame = frame[frame.batch.replace(catalog["batch_aliases"])==batch]
            if feed=="sensor" and {"channel","timestamp","value"}<=set(frame) and not frame.empty:
                channel = st.selectbox("Channel",frame.channel.dropna().unique())
                chart = frame[frame.channel==channel].copy()
                chart["value"] = pd.to_numeric(chart.value,errors="coerce")
                st.line_chart(chart,x="timestamp",y="value")
            st.dataframe(frame,hide_index=True)
            st.download_button("Download CSV",path.read_bytes(),path.name)
        else:
            st.info("No tabular exports loaded.")
    with inspection:
        assets = [a for a in catalog["images"] if batch=="All batches" or a["batch"]==batch]
        columns = st.columns(2)
        for i,item in enumerate(assets):
            columns[i%2].image(str(raw/item["path"]),caption=f"{item['sample']} · {item['description']}")
        if not assets:
            st.caption("No inspection images for this selection.")
    with reports:
        docs = [d for d in catalog["documents"] if batch=="All batches" or d["batch"]==batch]
        if not docs:
            st.info("This batch has no standalone lab report.")
        for d in docs:
            st.subheader(d["title"])
            st.write(" ".join(d["preview"]))
            st.download_button("Download original report",(raw/d["path"]).read_bytes(),d["title"] if "uploads" in catalog else d["path"].split("/")[-1],key="report-"+d["id"])
