import streamlit as st

from pharm.answers import answer
from pharm.retrieval import SOURCES
from pharm.search import display_items


def render(result, prefix, folder=None):
    st.caption(f"{' + '.join(result['sources'])} · {result['model']} · {result['seconds']:.2f} s")
    if result["error"]:
        st.warning(result["error"])
    for claim in result["claims"]:
        st.write(claim["text"])
        st.caption(" · ".join(claim["citations"]))
    for gap in result["gaps"]:
        st.info("Evidence gap in this retrieval · "+gap)
    st.subheader("Retrieved evidence")
    display_items(result["records"],prefix,folder)


def select_sources(container, label, default):
    # Streamlit removes hidden widgets. Keep selections when switching modes.
    selections = st.session_state.setdefault("source_selections", {})
    selected = container.multiselect(label, SOURCES, default=selections.get(label, default), key=f"sources-{label}")
    selections[label] = selected
    return selected


def show_chat(folder, request):
    sources = select_sources(st, "Retrieval sources", SOURCES)
    if st.button("Generate answer",type="primary",disabled=not sources or not (request.question or request.image or request.batch)):
        st.session_state.pop("ask_result",None)
        with st.spinner("Retrieving and checking cited evidence…"):
            st.session_state.ask_result = answer(folder,request,sources)
    if "ask_result" in st.session_state:
        result = st.session_state.ask_result
        st.write(result["question"] or "Image investigation")
        render(result,"ask-hit",folder)
