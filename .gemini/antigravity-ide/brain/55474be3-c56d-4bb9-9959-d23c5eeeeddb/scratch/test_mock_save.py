import sys
import os
import pandas as pd

sys.path.append("/Users/fc0kewc/Desktop/PO_Tools")

class MockSessionState(dict):
    def __getattr__(self, name):
        return self.get(name, None)
    def __setattr__(self, name, value):
        self[name] = value

import streamlit as st
st.session_state = MockSessionState()
st.session_state.custom_tables = []
st.session_state.overview_df = pd.DataFrame()
st.session_state.outlook_df = pd.DataFrame()
st.session_state.next_release_df = pd.DataFrame()

# Build table
from utils.jira_helpers import build_quarterly_epic_progress_table
from dotenv import load_dotenv

env_path = "/Users/fc0kewc/Desktop/PO_Tools/.env"
load_dotenv(dotenv_path=env_path, override=True)

server = os.getenv("JIRA_SERVER", "")
token = os.getenv("JIRA_API_TOKEN", "")
committed_label = os.getenv("COMMITTED_LABEL", "RC2_committed")
quarter_label = os.getenv("QUARTER_LABEL", "RC2_FB_18")
email = ""
auth_type = "Personal Access Token (Bearer PAT)"

new_table = build_quarterly_epic_progress_table(server, token, committed_label, quarter_label, "Epics test", "Before Demo Table", auth_type, email)

if new_table is not None:
    st.session_state.custom_tables.append(new_table)
    print("Table appended. Length:", len(st.session_state.custom_tables))
    
    # Import the function from the file
    import importlib.util
    spec = importlib.util.spec_from_file_location("sprint_review", "/Users/fc0kewc/Desktop/PO_Tools/tools/2_Sprint_Review.py")
    sprint_review = importlib.util.module_from_spec(spec)
    # We must patch st before executing module
    sys.modules["streamlit"] = st
    try:
        spec.loader.exec_module(sprint_review)
    except Exception as e:
        print("Module exec error (expected if it tries to render):", e)
        
    print("Calling save_sprint_review_shared...")
    try:
        sprint_review.save_sprint_review_shared()
        print("Save executed successfully!")
    except Exception as e:
        print("Error saving:", e)
else:
    print("Failed to build table")
