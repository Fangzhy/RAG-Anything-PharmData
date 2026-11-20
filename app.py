import streamlit as st

from pharm import explore

st.set_page_config(page_title="Chat With Pharma Data", page_icon="🔬", layout="wide")
from pharm.workspace import restore_workspace

restore_workspace()
st.sidebar.title("Chat With Pharma Data")
page = st.sidebar.radio("Workspace", ["Explore data", "Preprocess data", "Search data", "Chat & Compare"])
if page == "Explore data":
    explore.show()
elif page == "Preprocess data":
    from pharm import process
    process.show()
elif page == "Search data":
    from pharm import search
    search.show()
elif page == "Chat & Compare":
    from pharm import compare
    compare.show()
