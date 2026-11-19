import streamlit as st

from pharm import explore

st.set_page_config(page_title="Batch investigation", page_icon="🔬", layout="wide")
st.sidebar.title("Batch investigation")
page = st.sidebar.radio("Workspace", ["Explore raw data", "Process data"])
if page == "Explore raw data":
    explore.show()
elif page == "Process data":
    from pharm import process
    process.show()
