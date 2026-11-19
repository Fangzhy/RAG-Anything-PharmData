import streamlit as st

from pharm.answers import Investigation, answer
from pharm.prepare import active
from pharm.retrieval import OPENING, SOURCES
from pharm.search import display_items, inputs


def render(result, prefix):
    st.caption(f"{' + '.join(result['sources'])} · {result['model']} · {result['seconds']:.2f} s")
    if result["error"]:
        st.warning(result["error"])
    for claim in result["claims"]:
        st.write(claim["text"])
        st.caption(" · ".join(claim["citations"]))
    for gap in result["gaps"]:
        st.info("Evidence gap in this retrieval · "+gap)
    st.subheader("Retrieved evidence")
    display_items(result["records"],prefix)


def show():
    st.title("Ask a question")
    request = Investigation(*inputs("ask",OPENING))
    sources = st.multiselect("Retrieval sources",SOURCES,default=SOURCES)
    if st.button("Generate answer",type="primary",disabled=not sources or not (request.question or request.image or request.batch)):
        st.session_state.pop("ask_result",None)
        with st.spinner("Retrieving and checking cited evidence…"):
            st.session_state.ask_result = answer(active(),request,sources)
    if "ask_result" in st.session_state:
        result = st.session_state.ask_result
        st.write(result["question"] or "Image investigation")
        render(result,"ask-hit")
