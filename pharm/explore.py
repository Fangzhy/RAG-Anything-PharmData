import pandas as pd
import streamlit as st

from pharm.catalog import RAW, load_json, rows


def show():
    catalog = load_json(RAW / "catalog.json")
    st.title("Explore raw data")
    st.write("Investigate dissolution, process conditions, and tablet appearance across 20 synthetic R&D batches.")
    batch = st.selectbox("Batch", catalog["batches"])
    tables, inspection, reports = st.tabs(["Instrument exports", "Inspection images", "Lab reports"])
    with tables:
        feed = st.radio("Export", ["LIMS", "ELN", "Sensor"], horizontal=True)
        raw = pd.DataFrame(rows(feed.lower()))
        subset = raw[raw.batch.replace(catalog["batch_aliases"]) == batch]
        st.caption({"ELN":"Electronic lab notebook observations", "LIMS":"Laboratory information management system · Dissolution measures the percentage released at the specified test time.", "Sensor":"Press historian · one reading per channel per minute"}[feed])
        if feed == "Sensor":
            channel = st.selectbox("Channel", ["Temperature", "Press force"])
            chart = subset[subset.channel == channel].copy()
            chart["value"] = pd.to_numeric(chart.value)
            st.line_chart(chart, x="timestamp", y="value")
        st.dataframe(subset, hide_index=True)
        st.download_button("Download original CSV", (RAW / f"{feed.lower()}.csv").read_bytes(), f"{feed.lower()}.csv")
    with inspection:
        for col, item in zip(st.columns(2), [a for a in catalog["images"] if a["batch"] == batch]):
            col.image(str(RAW / item["path"]), caption=f"{item['sample']} · {item['description']}")
    with reports:
        docs = [d for d in catalog["documents"] if d["batch"] == batch]
        if not docs:
            st.info("This batch has no standalone lab report.")
        for d in docs:
            st.subheader(d["title"])
            st.write(" ".join(d["preview"]))
            st.download_button("Download original report", (RAW / d["path"]).read_bytes(), d["path"].split("/")[-1])
