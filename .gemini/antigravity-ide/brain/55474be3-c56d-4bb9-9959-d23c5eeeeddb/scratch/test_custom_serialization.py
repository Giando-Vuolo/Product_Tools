import sys
import os
sys.path.append("/Users/fc0kewc/Desktop/PO_Tools")

import pandas as pd
from utils.persistence import save_custom_tables_to_json, load_custom_tables_from_json
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
    print("Table built successfully. Attempting serialization to test_custom_tables.json...")
    try:
        save_custom_tables_to_json([new_table], "test_custom_tables.json")
        print("Serialization successful!")
        
        print("Attempting deserialization...")
        loaded = load_custom_tables_from_json("test_custom_tables.json")
        print("Deserialization successful! Rows loaded:", len(loaded[0]["df"]))
    except Exception as e:
        print("FAIL:", e)
else:
    print("Failed to build table")
