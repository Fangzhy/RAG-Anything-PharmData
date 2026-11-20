import streamlit as st

from pharm.answers import Investigation, answer
from pharm.ask import render
from pharm.workspace import current_build
from pharm.retrieval import OPENING, SOURCES
from pharm.search import inputs


def compare(folder, request, left, right):
    return {
        "folder":folder, "request":request,
        "panels":[answer(folder,request,left),answer(folder,request,right)]
    }


def evidence_sets(panels):
    left, right = ({r["id"] for r in p["records"]} for p in panels)
    return sorted(left & right),sorted(left-right),sorted(right-left)


def show():
    st.title("Compare answers")
    st.write("Run one investigation against two source selections. Inspect the citations to see what each selection contributes.")
    folder = current_build()
    if folder is None:
        st.info("Apply a schema and ontology on Preprocess data to compare this study.")
        return
    request = Investigation(*inputs("compare",OPENING,folder,demo_image=True))
    left,right = st.columns(2)
    first = left.multiselect("Left sources",SOURCES,default=["SQL"])
    second = right.multiselect("Right sources",SOURCES,default=SOURCES)
    ready = bool(first and second and (request.question or request.image or request.batch))
    if st.button("Run comparison",type="primary",disabled=not ready):
        with st.spinner("Running both evidence selections…"):
            st.session_state.comparison = compare(folder,request,first,second)
    if "comparison" not in st.session_state:
        return
    run = st.session_state.comparison
    original = run["request"]
    panels = run["panels"]
    st.subheader(original.question or "Image investigation")
    st.caption(f"{run['folder'].name} · {original.batch or 'All batches'} · Text weight {original.weight:.0%} · {'With image' if original.image else 'Text query'}")
    common, left_only, right_only = evidence_sets(panels)
    with st.expander(f"Evidence overlap · {len(common)} shared, {len(left_only)} left only, {len(right_only)} right only"):
        for label, ids in (("Shared",common),("Left only",left_only),("Right only",right_only)):
            st.write(f"**{label}**")
            st.caption(", ".join(ids) or "None")
    for i,column in enumerate(st.columns(2)):
        with column:
            st.subheader("Left answer" if i==0 else "Right answer")
            result = panels[i]
            if result["error"] and st.button("Retry this answer",key=f"retry-{i}"):
                with st.spinner("Retrying with the original evidence…"):
                    panels[i] = answer(run["folder"],original,result["sources"],records=result["records"])
                    st.session_state.comparison = run
                st.rerun()
            render(result,f"compare-{i}",run["folder"])
