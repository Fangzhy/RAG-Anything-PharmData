import streamlit as st

from pharm import explore

st.set_page_config(page_title="Chat With Pharma Data", page_icon="🔬", layout="wide")
from pharm.workspace import restore_workspace

restore_workspace()
st.sidebar.title("Chat With Pharma Data")
page = st.sidebar.radio("Workspace", ["Explore data", "Process data", "Search evidence", "Ask a question", "Compare answers"])
if page == "Explore data":
    explore.show()
elif page == "Process data":
    from pharm import process
    process.show()
elif page == "Search evidence":
    from pharm import search
    search.show()
elif page == "Ask a question":
    from pharm import ask
    ask.show()
elif page == "Compare answers":
    from pharm import compare
    compare.show()
