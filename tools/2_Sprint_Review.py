import streamlit as st
import pandas as pd
import requests
import os
import io
import re
import base64
from dotenv import load_dotenv
from PIL import Image as PILImage

# ReportLab imports for beautiful PDF generation
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Line, PolyLine

# ---------------------------------------------------------
# 1. Environment Loading & Session Setup
# ---------------------------------------------------------
load_dotenv(override=True)

# Configuration: Presets for item types to include during ingestion
env_types = os.getenv("DEFAULT_INCLUDED_TYPES")
if env_types:
    DEFAULT_INCLUDED_TYPES = [t.strip() for t in env_types.split(",") if t.strip()]
else:
    DEFAULT_INCLUDED_TYPES = ["User Story", "Task", "Technical Task", "Technical Sub-task", "Bug"]

# Read default environment variables if provided
default_jira_server = os.getenv("JIRA_SERVER", "")
default_jira_token = os.getenv("JIRA_API_TOKEN", "")
default_jira_auth_method = os.getenv("JIRA_AUTH_METHOD", "Jira Server Token (Bearer)")
default_jira_email = os.getenv("JIRA_EMAIL", "")

# Initialize all required Session State keys
default_conf_server = os.getenv("CONFLUENCE_SERVER", "")
default_conf_token = os.getenv("CONFLUENCE_API_TOKEN", "")
default_conf_space = os.getenv("CONFLUENCE_SPACE", "DS")
default_conf_page = os.getenv("CONFLUENCE_PAGE", "Release Notes")

default_project_name = os.getenv("PROJECT_NAME", "PO Tools Enterprise")
default_primary_color = os.getenv("PRIMARY_COLOR", "#3B82F6")

default_filename_sr = os.getenv("DEFAULT_FILENAME_SPRINT_REVIEW", "Sprint_Review_Report")
default_filename_rn = os.getenv("DEFAULT_FILENAME_RELEASE_NOTES", "Release_Notes")

default_release_notes_intro = os.getenv("RELEASE_NOTES_INTRO", """### Dear Users & Partners,

We are excited to share the **Release Notes** for our latest development cycle. In this iteration, our engineering team focused on bolstering platform security, optimizing database transaction queries, and releasing crucial merchant billing integrations.

**Delivered Highlights:**
* **Enhanced Security:** Implemented Google & GitHub OAuth2 Single Sign-On (SSO).
* **Payment Processing:** Integrated recurrent merchant subscription flows via Stripe.
* **Document Services:** Finalized robust PDF invoicing exporters inside staging.

Thank you for your continuous feedback, which drives our iterative development process.

*Best Regards,*  
**The Product Management Team**""")
if default_release_notes_intro:
    default_release_notes_intro = default_release_notes_intro.replace("\\n", "\n")

default_sprint_number = os.getenv("COVER_SPRINT_NAME", "Sprint 14")
default_sprint_welcome_message = os.getenv("SPRINT_WELCOME_MESSAGE", "Welcome to the Sprint Review session. This document consolidates our delivered sprint capabilities, scheduled target releases, and interactive product demo presentations. We thank our engineering team and product stakeholders for their collaborative efforts.")
if default_sprint_welcome_message:
    default_sprint_welcome_message = default_sprint_welcome_message.replace("\\n", "\n")

default_logo_temp_path = os.getenv("LOGO_IMAGE_PATH", "")
if default_logo_temp_path == "":
    default_logo_temp_path = None

default_cover_temp_path = os.getenv("COVER_IMAGE_PATH", "")
if default_cover_temp_path == "":
    default_cover_temp_path = None

default_ov_sprint_num = os.getenv("OVERVIEW_SPRINT_NUM", "1")
default_ot_sprint_num = os.getenv("OUTLOOK_SPRINT_NUM", "2")

# Initialize all required Session State keys
if 'jira_server' not in st.session_state:
    st.session_state.jira_server = default_jira_server
if 'jira_token' not in st.session_state:
    st.session_state.jira_token = default_jira_token
if 'jira_auth_method' not in st.session_state:
    st.session_state.jira_auth_method = default_jira_auth_method
if 'jira_email' not in st.session_state:
    st.session_state.jira_email = default_jira_email

if 'conf_server' not in st.session_state:
    st.session_state.conf_server = default_conf_server
if 'conf_token' not in st.session_state:
    st.session_state.conf_token = default_conf_token
if 'conf_space_key' not in st.session_state:
    st.session_state.conf_space_key = default_conf_space
if 'conf_page_name' not in st.session_state:
    st.session_state.conf_page_name = default_conf_page

if 'overview_df' not in st.session_state:
    st.session_state.overview_df = None
if 'outlook_df' not in st.session_state:
    st.session_state.outlook_df = None

if 'project_name' not in st.session_state:
    st.session_state.project_name = default_project_name
if 'filename_sr' not in st.session_state:
    st.session_state.filename_sr = default_filename_sr
if 'filename_rn' not in st.session_state:
    st.session_state.filename_rn = default_filename_rn
if 'next_release_df' not in st.session_state:
    st.session_state.next_release_df = pd.DataFrame([
        {
            "Version": "v1.3.0",
            "Target Date": "2026-06-15",
            "Comments": "Major central dashboard UI redesign, EKS migration, and compliance preparations."
        }
    ])
if 'primary_color' not in st.session_state or st.session_state.get('prev_env_color') != default_primary_color:
    st.session_state.primary_color = default_primary_color
    st.session_state.prev_env_color = default_primary_color
if 'release_notes_intro' not in st.session_state:
    st.session_state.release_notes_intro = default_release_notes_intro

# Page state for dynamic programmatic navigation
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = "🔌 Ingestion"

# Temporary logo file management
if 'logo_temp_path' not in st.session_state:
    st.session_state.logo_temp_path = default_logo_temp_path

# Starting Cover Page welcome message and cover image states (NEW requested states)
if 'sprint_number' not in st.session_state:
    st.session_state.sprint_number = default_sprint_number

if 'sprint_welcome_message' not in st.session_state:
    st.session_state.sprint_welcome_message = default_sprint_welcome_message

if 'cover_temp_path' not in st.session_state:
    st.session_state.cover_temp_path = default_cover_temp_path

if 'ov_sprint_num' not in st.session_state:
    st.session_state.ov_sprint_num = default_ov_sprint_num
if 'ot_sprint_num' not in st.session_state:
    st.session_state.ot_sprint_num = default_ot_sprint_num

if 'extra_table_df' not in st.session_state:
    st.session_state.extra_table_df = None
if 'extra_table_title' not in st.session_state:
    st.session_state.extra_table_title = ""
if 'custom_tables' not in st.session_state:
    st.session_state.custom_tables = []


# ---------------------------------------------------------
# 2. Custom CSS styling (Premium dark SaaS UI)
# ---------------------------------------------------------

st.markdown("""
    <style>
         /* General dark theme override */
         .main, .block-container, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
             background-color: #27272E !important;
             color: #F8FAFC !important;
         }
         
         /* High visibility and premium SaaS styling for file uploader */
         [data-testid="stFileUploadDropzone"] {
             background-color: #18181D !important;
             border: 1px dashed #60A5FA !important;
             border-radius: 12px !important;
         }
         [data-testid="stFileUploadDropzone"] * {
             color: #F8FAFC !important;
         }
         [data-testid="stFileUploaderFileName"], 
         .stFileUploaderFileName, 
         .uploadedFileName {
             color: #FFFFFF !important;
             font-weight: 600 !important;
         }
         [data-testid="stFileUploader"] section {
             background-color: #18181D !important;
             border: 1px solid #3E3E4A !important;
             border-radius: 12px !important;
         }
         [data-testid="stFileUploader"] section * {
             color: #FFFFFF !important;
         }
         
         /* Typography high-contrast styles */
         h1, h2, h3, h4, h5, h6 {
             color: #FFFFFF !important;
             font-weight: 700 !important;
         }
         .stMarkdown p, .stMarkdown li, .stMarkdown span {
             color: #F8FAFC !important;
         }
         label, .stWidgetLabel {
             color: #FFFFFF !important;
             font-weight: 600 !important;
         }
         
         /* Sidebar Toggle Button */
         button[data-testid="collapsedControl"], button[kind="header"] {
             color: #60A5FA !important;
         }
         button[data-testid="collapsedControl"] svg, button[kind="header"] svg {
             fill: #60A5FA !important;
         }
         
         /* File Uploader small limit text */
         [data-testid="stFileUploadDropzone"] small {
             color: #94A3B8 !important;
             font-weight: 500 !important;
         }
         
         /* Sidebar dark theme label improvements */
         section[data-testid="stSidebar"] {
             background-color: #18181D !important;
             border-right: 1px solid #3E3E4A !important;
         }
         section[data-testid="stSidebar"] h1,
         section[data-testid="stSidebar"] h2,
         section[data-testid="stSidebar"] h3,
         section[data-testid="stSidebar"] h4,
         section[data-testid="stSidebar"] label,
         section[data-testid="stSidebar"] .stMarkdown {
             color: #FFFFFF !important;
         }
         
         /* Rounded borders and shadows for dataframes and tables */
         div[data-testid="stDataFrame"] { 
             border-radius: 12px; 
             overflow: hidden; 
             border: 1px solid #3E3E4A !important;
             box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5);
             background-color: #18181D;
         }
         div[data-testid="stExpander"] { 
             border-radius: 12px !important; 
             border: 1px solid #3E3E4A !important; 
             background-color: #18181D !important;
             box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.4);
             margin-bottom: 1rem;
             overflow: hidden;
         }
         div[data-testid="stExpander"] > details {
             background-color: #18181D !important;
         }
         div[data-testid="stExpander"] summary {
             background-color: #18181D !important;
             color: #FFFFFF !important;
             font-weight: 600;
         }
         div[data-testid="stExpander"] summary:hover {
             background-color: #2D2D38 !important;
         }
         div[data-testid="stExpander"] .stMarkdown {
             color: #F8FAFC !important;
         }
         
         /* General bordered container style */
         div[data-testid="stVerticalBlockBorderWrapper"],
         div.stVerticalBlockBorder {
             border: 1px solid #3E3E4A !important;
             border-radius: 12px !important;
             background-color: #18181D !important;
             padding: 1.5rem !important;
             box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5) !important;
         }
         
         /* Premium button styles with interactive glow and forced high-contrast text */
         .stButton>button, .stDownloadButton>button, button[data-testid="stBaseButton-secondary"] { 
             border-radius: 24px; 
             border: none; 
             background: linear-gradient(135deg, #3B82F6 0%, #1D4ED8 100%) !important; 
             color: #FFFFFF !important; 
             padding: 0.5rem 0.75rem; 
             font-weight: 600;
             box-shadow: none !important;
             transition: all 0.2s ease-in-out;
         }
         .stButton>button:hover, .stDownloadButton>button:hover, button[data-testid="stBaseButton-secondary"]:hover { 
             background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%) !important;
             color: #FFFFFF !important;
             box-shadow: none !important;
             transform: translateY(-1px);
         }
         .stButton>button:disabled, .stDownloadButton>button:disabled, button[data-testid="stBaseButton-secondary"]:disabled {
             background: #3E3E4A !important;
             color: #8E8E9F !important;
             cursor: not-allowed;
             opacity: 0.6;
             transform: none !important;
         }
         
         /* Custom card layouts for exports */
         .export-card {
             background-color: #18181D !important;
             border: 1px solid #3E3E4A !important;
             border-radius: 12px !important;
             padding: 1.2rem !important;
             margin-bottom: 0.8rem;
             transition: all 0.2s ease-in-out;
             box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.4);
         }
         .export-card h3 {
             margin-top: 0 !important;
             color: #FFFFFF !important;
         }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 3. High-Quality Sprint Mock Datasets
# ---------------------------------------------------------
def generate_mock_overview_data():
    return pd.DataFrame([
        {
            "Key": "PROJ-101",
            "Summary": "Integrate Google & GitHub Social Login (OAuth2)",
            "Epic": "Authentication & Identity",
            "Status": "Done",
            "Fix Version": "v1.2.0-beta",
            "Outlook": "Completed successfully. Ready for deployment.",
            "Sprint Review": True,
            "Release Notes": True,
            "Assignee": "Ana Martinez",
            "Demo": True,
            "Type": "User Story",
            "Labels": "security, frontend, oauth"
        },
        {
            "Key": "PROJ-103",
            "Summary": "Set up Stripe recurrent billing and subscriptions",
            "Epic": "Billing & Core Payments",
            "Status": "Done",
            "Fix Version": "v1.2.0-beta",
            "Outlook": "Finance confirmed production API sandbox keys.",
            "Sprint Review": True,
            "Release Notes": True,
            "Assignee": "Elena Gomez",
            "Demo": True,
            "Type": "User Story",
            "Labels": "billing, stripe, backend"
        },
        {
            "Key": "PROJ-106",
            "Summary": "Develop monthly client invoice PDF generator",
            "Epic": "Billing & Core Payments",
            "Status": "Done",
            "Fix Version": "v1.2.0-beta",
            "Outlook": "Resolved minor page layout issues in Staging environment.",
            "Sprint Review": True,
            "Release Notes": True,
            "Assignee": "Sofia Torres",
            "Demo": True,
            "Type": "Task",
            "Labels": "billing, pdf-generation"
        },
        {
            "Key": "PROJ-110",
            "Summary": "Resolve security vulnerabilities and patch NPM packages",
            "Epic": "Technical Debt",
            "Status": "Done",
            "Fix Version": "v1.1.9",
            "Outlook": "Completed technical debt ticket without incident.",
            "Sprint Review": False,
            "Release Notes": False,
            "Assignee": "Diego Diaz",
            "Demo": False,
            "Type": "Technical Task",
            "Labels": "security, tech-debt"
        },
        {
            "Key": "PROJ-111",
            "Summary": "Fix session expiration memory leak on staging site",
            "Epic": "Authentication & Identity",
            "Status": "Done",
            "Fix Version": "v1.2.0-beta",
            "Outlook": "Patched express-session cookie expiration handlers.",
            "Sprint Review": True,
            "Release Notes": True,
            "Assignee": "Ana Martinez",
            "Demo": False,
            "Type": "Bug",
            "Labels": "bugfix, auth, memory-leak"
        }
    ])

def generate_mock_outlook_data():
    return pd.DataFrame([
        {
            "Key": "PROJ-102",
            "Summary": "Design and mockup central control panel dashboard",
            "Epic": "UI/UX Redesign",
            "Status": "To Do",
            "Fix Version": "v1.3.0",
            "Assignee": "Carlos Ruiz",
            "Sprint Review": True,
            "Release Notes": True,
            "Type": "User Story",
            "Labels": "ui-ux, frontend"
        },
        {
            "Key": "PROJ-105",
            "Summary": "Optimize PostgreSQL finance query index structures",
            "Epic": "Performance & Scaling",
            "Status": "To Do",
            "Fix Version": "v1.3.0",
            "Assignee": "Javier Lopez",
            "Sprint Review": True,
            "Release Notes": False,
            "Type": "Technical Task",
            "Labels": "database, performance"
        },
        {
            "Key": "PROJ-107",
            "Summary": "Migrate on-prem servers to Amazon EKS (Kubernetes)",
            "Epic": "Cloud & Operations",
            "Status": "In Progress",
            "Fix Version": "v1.3.0",
            "Assignee": "Diego Diaz",
            "Sprint Review": True,
            "Release Notes": True,
            "Type": "Task",
            "Labels": "devops, aws, eks"
        },
        {
            "Key": "PROJ-112",
            "Summary": "Fix Stripe webhook signature validation crash in production sandbox",
            "Epic": "Billing & Core Payments",
            "Status": "To Do",
            "Fix Version": "v1.3.0",
            "Assignee": "Elena Gomez",
            "Sprint Review": True,
            "Release Notes": False,
            "Type": "Bug",
            "Labels": "bugfix, stripe, billing"
        }
    ])

# Helper to extract only the numeric part of a version string (e.g., "1.3.0" from "v1.3.0")
def extract_numeric_version(v_val):
    if pd.isna(v_val):
        return ""
    v_str = str(v_val).strip()
    if not v_str or v_str.lower() in ["n/a", "none", "-", "nan", "general"]:
        return ""
    import re
    matches = re.findall(r'\d+(?:[\.\-]\d+)*', v_str)
    if matches:
        return ", ".join(matches)
    return ""

# Callback to load mock sprint datasets securely before widget instantiation
def load_mock_sprint_data():
    st.session_state.overview_df = generate_mock_overview_data()
    st.session_state.outlook_df = generate_mock_outlook_data()
    
    # Filter by user checkboxes if key exists, otherwise use DEFAULT_INCLUDED_TYPES preset
    inc_all = st.session_state.get("inc_all", False)
    if not inc_all:
        selected_types = []
        if st.session_state.get("inc_story", "User Story" in DEFAULT_INCLUDED_TYPES): selected_types.append("User Story")
        if st.session_state.get("inc_task", "Task" in DEFAULT_INCLUDED_TYPES): selected_types.append("Task")
        if st.session_state.get("inc_tech", "Technical Task" in DEFAULT_INCLUDED_TYPES): selected_types.append("Technical Task")
        if st.session_state.get("inc_subtask", "Technical Sub-task" in DEFAULT_INCLUDED_TYPES): selected_types.append("Technical Sub-task")
        if st.session_state.get("inc_bug", "Bug" in DEFAULT_INCLUDED_TYPES): selected_types.append("Bug")
        
        if st.session_state.overview_df is not None and not st.session_state.overview_df.empty:
            st.session_state.overview_df = st.session_state.overview_df[st.session_state.overview_df["Type"].isin(selected_types)].reset_index(drop=True)
        if st.session_state.outlook_df is not None and not st.session_state.outlook_df.empty:
            st.session_state.outlook_df = st.session_state.outlook_df[st.session_state.outlook_df["Type"].isin(selected_types)].reset_index(drop=True)

    if 'Fix Version' in st.session_state.overview_df.columns:
        st.session_state.overview_df['Fix Version'] = st.session_state.overview_df['Fix Version'].apply(extract_numeric_version)
    if 'Fix Version' in st.session_state.outlook_df.columns:
        st.session_state.outlook_df['Fix Version'] = st.session_state.outlook_df['Fix Version'].apply(extract_numeric_version)
    st.session_state.ov_sprint_num = "12"
    st.session_state.ot_sprint_num = "13"
    st.session_state.custom_tables = [
        {
            "title": "Special Performance Metrics",
            "df": pd.DataFrame([
                {"Select": False, "Key": "PROJ-201", "Metric Name": "API Response Time (p95)", "Value": "180ms", "Status": "Done"},
                {"Select": False, "Key": "PROJ-202", "Metric Name": "Database CPU Load", "Value": "24%", "Status": "In Progress"}
            ]),
            "position": "Before Demo Table"
        }
    ]
    st.toast("🚀 Loaded mock datasets successfully!", icon="🔥")

# ---------------------------------------------------------

# 4. Jira Connection API Fetcher (Bearer Token Auth PAT)
# ---------------------------------------------------------
def fetch_jira_tickets_dataset(server, token, query_val, is_sprint=True, auth_type="Personal Access Token (Bearer PAT)", email=""):
    if not server or not token:
        st.error("Please provide Jira Server URL and Personal Access Token (PAT).")
        return None
        
    # Safe cleanup of token inputs (removes accidental whitespaces or prepended 'Bearer ')
    token_clean = token.strip()
    if token_clean.lower().startswith("bearer "):
        token_clean = token_clean[7:].strip()
        
    if is_sprint:
        if query_val.isdigit():
            jql = f"sprint = {query_val}"
        else:
            jql = f"sprint = '{query_val}'"
    else:
        jql = query_val
        
    url = f"{server.rstrip('/')}/rest/api/2/search"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Atlassian-Token": "no-check"
    }

    
    auth = None
    if auth_type == "Corporate Login (Username + Password)" or auth_type == "Jira Cloud/Server Basic (Email/User + Token)":
        auth = (email.strip(), token_clean)
    else:
        headers["Authorization"] = f"Bearer {token_clean}"
        
    params = {
        "jql": jql,
        "maxResults": 100,
        "fields": "key,summary,status,fixVersions,parent,customfield_10000,customfield_10008,customfield_10009,customfield_10014,assignee,issuetype,labels"
    }

    
    try:
        if auth:
            response = requests.get(url, headers=headers, params=params, auth=auth, timeout=15)
        else:
            response = requests.get(url, headers=headers, params=params, timeout=15)

        
        if response.status_code != 200:
            st.error(f"Jira API connection failed ({response.status_code}): {response.text}")
            return None
            
        try:
            data = response.json()
        except ValueError as json_err:
            st.error("⚠️ **Jira returned a non-JSON response (Status 200 OK).**")
            st.warning("This usually happens when your company's Single Sign-On (SSO) gateway, Proxy, or Firewall intercepts the API call and redirects it to a login webpage or CAPTCHA screen.")
            st.write("**First 1000 characters of the intercepted response:**")
            st.code(response.text[:1000], language="html")
            return None
            
        issues = data.get("issues", [])

        
        if not issues:
            st.warning("No issues found matching the query parameters.")
            return pd.DataFrame()
            
        rows = []
        for issue in issues:
            fields = issue.get("fields", {})
            key = issue.get("key", "N/A")
            summary = fields.get("summary", "Untitled Task")
            
            # Status
            status_obj = fields.get("status") or {}
            status = status_obj.get("name", "To Do")
            
            # Fix Version
            fix_versions = fields.get("fixVersions", [])
            raw_fix_version = ", ".join([v.get("name", "") for v in fix_versions]) if fix_versions else ""
            fix_version = extract_numeric_version(raw_fix_version)
            
            # Assignee
            assignee_obj = fields.get("assignee")
            assignee = assignee_obj.get("displayName", "Unassigned") if assignee_obj else "Unassigned"
            
            # Epic detection
            epic = "-"
            epic_key = None
            
            for custom_field in ["customfield_10014", "customfield_10000", "customfield_10008", "customfield_10009"]:
                cf_val = fields.get(custom_field)
                if cf_val:
                    if isinstance(cf_val, dict):
                        epic_key = cf_val.get("key") or str(cf_val)
                    else:
                        epic_key = str(cf_val)
                    break
            
            parent_summary = None
            parent = fields.get("parent")
            if parent:
                parent_key = parent.get("key")
                parent_fields = parent.get("fields") or {}
                parent_summary = parent_fields.get("summary")
                if not epic_key:
                    epic_key = parent_key
            
            if epic_key:
                if parent and epic_key == parent.get("key") and parent_summary:
                    epic = f"{epic_key} - {parent_summary}"
                else:
                    epic = epic_key
                        
            # Issue Type detection & mapping
            issue_type_obj = fields.get("issuetype") or {}
            issue_type_raw = issue_type_obj.get("name", "Task")
            
            raw_lower = issue_type_raw.lower()
            issue_type = None
            if "technical sub-task" in raw_lower or "tech sub-task" in raw_lower or "technical subtask" in raw_lower or "tech subtask" in raw_lower or ("sub-task" in raw_lower and ("tech" in raw_lower or "technical" in raw_lower)):
                issue_type = "Technical Sub-task"
            elif "story" in raw_lower:
                issue_type = "User Story"
            elif "bug" in raw_lower:
                issue_type = "Bug"
            elif "technical" in raw_lower or "tech" in raw_lower or "performance" in raw_lower or "scaling" in raw_lower or "infrastructure" in raw_lower:
                issue_type = "Technical Task"
            elif "task" in raw_lower or "sub-task" in raw_lower:
                issue_type = "Task"
            else:
                issue_type = issue_type_raw if st.session_state.get("inc_all", False) else "Technical Task"
                
            # Labels
            labels_list = fields.get("labels", [])
            labels_str = ", ".join(labels_list) if isinstance(labels_list, list) else ""
                
            rows.append({
                "Key": key,
                "Summary": summary,
                "Epic": epic,
                "Status": status,
                "Fix Version": fix_version,
                "Outlook": "",
                "Sprint Review": True,
                "Release Notes": True,
                "Assignee": assignee,
                "Demo": False,
                "Type": issue_type,
                "Labels": labels_str
            })
            
        # Bulk resolve Epic summaries from Jira
        epic_keys_to_resolve = set()
        for r in rows:
            ep_val = r["Epic"]
            if ep_val != "-" and " - " not in ep_val:
                epic_keys_to_resolve.add(ep_val)
                
        if epic_keys_to_resolve:
            try:
                keys_str = ",".join([f"'{k}'" for k in epic_keys_to_resolve])
                epic_jql = f"key in ({keys_str})"
                epic_url = f"{server.rstrip('/')}/rest/api/2/search"
                epic_params = {
                    "jql": epic_jql,
                    "fields": "key,summary",
                    "maxResults": 100
                }
                if auth:
                    epic_resp = requests.get(epic_url, headers=headers, params=epic_params, auth=auth, timeout=10)
                else:
                    epic_resp = requests.get(epic_url, headers=headers, params=epic_params, timeout=10)
                
                if epic_resp.status_code == 200:
                    epic_data = epic_resp.json()
                    epic_map = {}
                    for epic_issue in epic_data.get("issues", []):
                        e_key = epic_issue.get("key")
                        e_fields = epic_issue.get("fields") or {}
                        e_summary = e_fields.get("summary")
                        if e_key and e_summary:
                            epic_map[e_key] = f"{e_key} - {e_summary}"
                            
                    for r in rows:
                        ep_val = r["Epic"]
                        if ep_val in epic_map:
                            r["Epic"] = epic_map[ep_val]
            except Exception:
                pass
                
        return pd.DataFrame(rows)
    except Exception as e:
        st.error(f"Exception connecting to Jira: {str(e)}")
        return None

def upload_pdf_to_confluence(server_url, auth_type, token, email, space_key, page_title, pdf_bytes, filename):
    """
    Finds or creates a Confluence page with the given page_title in space_key,
    then uploads pdf_bytes as a versioned attachment with filename.
    Returns the URL to the viewable Confluence page.
    """
    if not server_url or not token or not space_key or not page_title:
        raise Exception("Required configuration fields (URL, Token, Space Key, Page Title) cannot be empty.")
        
    base_url = server_url.rstrip("/")
    # Autocorrect typical Cloud URL structures if user missed '/wiki'
    if "atlassian.net" in base_url and not base_url.endswith("/wiki"):
        base_url = base_url + "/wiki"
        
    headers = {
        "Accept": "application/json"
    }
    
    auth = None
    if auth_type == "Corporate Login (Username + Password)" or auth_type == "Jira Cloud (Email + API Token)":
        if not email:
            raise Exception("Username/Email is required for Confluence Basic authentication.")
        auth = (email, token)
    else:
        # Bearer token PAT auth
        headers["Authorization"] = f"Bearer {token}"

        
    # Step 1: Find the target page by title in the specified space
    find_url = f"{base_url}/rest/api/content"
    params = {
        "title": page_title,
        "spaceKey": space_key,
        "expand": "version"
    }
    
    try:
        if auth:
            resp = requests.get(find_url, headers=headers, params=params, auth=auth, timeout=15)
        else:
            resp = requests.get(find_url, headers=headers, params=params, timeout=15)
    except Exception as e:
        raise Exception(f"Failed to connect to Confluence server: {str(e)}")
        
    if resp.status_code != 200:
        raise Exception(f"Failed to query Confluence page ({resp.status_code}): {resp.text}")
        
    results = resp.json().get("results", [])
    page_id = None
    
    body_html = (
        "<p>This page acts as a repository for automatically generated Sprint Reviews and Release Notes PDFs.</p>"
        "<p><strong>📂 Attached PDF Documents (Click to download):</strong></p>"
        "<ac:structured-macro ac:name=\"attachments\"></ac:structured-macro>"
    )
    
    if results:
        page_id = results[0]["id"]
        current_version = results[0]["version"]["number"]
        
        # Step 2a: Update existing page body to ensure the attachments macro is rendered
        update_url = f"{base_url}/rest/api/content/{page_id}"
        update_payload = {
            "id": page_id,
            "type": "page",
            "title": page_title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body_html,
                    "representation": "storage"
                }
            },
            "version": {
                "number": current_version + 1
            }
        }
        
        update_headers = headers.copy()
        update_headers["Content-Type"] = "application/json"
        
        try:
            if auth:
                requests.put(update_url, headers=update_headers, json=update_payload, auth=auth, timeout=15)
            else:
                requests.put(update_url, headers=update_headers, json=update_payload, timeout=15)
        except Exception:
            pass # Non-blocking update failure; proceed to upload attachment
    else:
        # Step 2b: Create the page if it doesn't exist
        create_url = f"{base_url}/rest/api/content"
        create_payload = {
            "type": "page",
            "title": page_title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body_html,
                    "representation": "storage"
                }
            }
        }
        
        # Prepare page creation headers (adding content-type)
        create_headers = headers.copy()
        create_headers["Content-Type"] = "application/json"
        
        if auth:
            cr_resp = requests.post(create_url, headers=create_headers, json=create_payload, auth=auth, timeout=15)
        else:
            cr_resp = requests.post(create_url, headers=create_headers, json=create_payload, timeout=15)
            
        if cr_resp.status_code not in (200, 201):
            raise Exception(f"Failed to create new Confluence page ({cr_resp.status_code}): {cr_resp.text}")
            
        page_id = cr_resp.json().get("id")

        
    if not page_id:
        raise Exception("Could not retrieve or create a valid Confluence Page ID.")
        
    # Step 3: Check if the attachment already exists on this page
    att_url = f"{base_url}/rest/api/content/{page_id}/child/attachment"
    att_params = {"limit": 100}
    
    if auth:
        ar_resp = requests.get(att_url, headers=headers, params=att_params, auth=auth, timeout=15)
    else:
        ar_resp = requests.get(att_url, headers=headers, params=att_params, timeout=15)
        
    att_results = ar_resp.json().get("results", []) if ar_resp.status_code == 200 else []
    attachment_id = None
    for att in att_results:
        if att.get("title") == filename:
            attachment_id = att.get("id")
            break
            
    # Step 4: Upload PDF bytes as attachment (handling new vs update/versioning)
    upload_headers = {
        "Accept": "application/json",
        "X-Atlassian-Token": "no-check" # Critical CSRF bypass for attachments API
    }
    if auth_type == "Personal Access Token (Bearer PAT)" or auth_type == "Jira Server Token (Bearer)":
        upload_headers["Authorization"] = f"Bearer {token}"

        
    files = {
        "file": (filename, pdf_bytes, "application/pdf")
    }
    
    if attachment_id:
        # Update existing attachment (increments version)
        upload_url = f"{base_url}/rest/api/content/{page_id}/child/attachment/{attachment_id}/data"
    else:
        # Create new attachment
        upload_url = f"{base_url}/rest/api/content/{page_id}/child/attachment"
        
    if auth:
        up_resp = requests.post(upload_url, headers=upload_headers, files=files, auth=auth, timeout=20)
    else:
        up_resp = requests.post(upload_url, headers=upload_headers, files=files, timeout=20)
        
    if up_resp.status_code not in (200, 201):
        raise Exception(f"Failed to upload attachment to Confluence ({up_resp.status_code}): {up_resp.text}")
        
    page_link = f"{base_url}/pages/viewpage.action?pageId={page_id}"
    return page_link

# Helper to transform Hex colors into ReportLab Color objects

def hex_to_reportlab_color(hex_str, default="#3B82F6"):
    if not hex_str:
        return colors.HexColor(default)
    try:
        return colors.HexColor(hex_str)
    except Exception:
        return colors.HexColor(default)

# Simple Markdown to HTML formatter for ReportLab
def convert_markdown_to_pdf_rich_text(md_text):
    if not md_text:
        return ""
    html = md_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html)
    html = re.sub(r'\*(.*?)\*', r'<i>\1</i>', html)
    html = re.sub(r'^\*\s+(.*?)$', r'• \1', html, flags=re.MULTILINE)
    html = re.sub(r'^-\s+(.*?)$', r'• \1', html, flags=re.MULTILINE)
    html = html.replace("\n", "<br/>")
    return html

# Helper to separate bugs from other topics
def split_bugs_and_topics(df):
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame()
    if 'Type' not in df.columns:
        return df.copy(), pd.DataFrame()
    is_bug = df['Type'].astype(str).str.strip().str.lower() == 'bug'
    bugs_df = df[is_bug]
    topics_df = df[~is_bug]
    return topics_df, bugs_df

# Helper to sort items by Type order (User Story -> Task -> Technical Task) and then Epic
def sort_items_by_type_and_epic(df):
    if df is None or df.empty:
        return df
    if 'Type' not in df.columns:
        return df.sort_values("Epic")
        
    def get_sort_order(item_type):
        val = str(item_type).strip().lower()
        if "story" in val:
            return 1
        elif "bug" in val:
            return 4
        elif "technical" in val:
            return 3
        elif "task" in val:
            return 2
        else:
            return 3 # Default other types to Technical Task level
            
    df_copy = df.copy()
    df_copy['_type_sort_order'] = df_copy['Type'].apply(get_sort_order)
    df_copy.sort_values(by=['Epic', '_type_sort_order', 'Key'], inplace=True)
    df_copy.drop(columns=['_type_sort_order'], inplace=True)
    return df_copy

# ---------------------------------------------------------
# 5. PDF Generation Custom Canvas & Background Callbacks (Header, Footer, Branding)
# ---------------------------------------------------------
def draw_background_landscape(canvas_obj, doc_obj):
    primary_color_hex = st.session_state.primary_color
    primary_color = hex_to_reportlab_color(primary_color_hex)
    
    canvas_obj.saveState()
    width, height = doc_obj.pagesize
    
    # Subtle corporate background color fill
    canvas_obj.setFillColor(colors.HexColor("#F8FAFC"))
    canvas_obj.rect(0, 0, width, height, stroke=0, fill=1)
    
    # Solid vertical branding accent band on the far left edge
    canvas_obj.setFillColor(primary_color)
    canvas_obj.rect(0, 0, 8, height, stroke=0, fill=1)
    
    if doc_obj.page == 1:
        # Cover page background frame:
        # Top banner of primary color
        canvas_obj.setFillColor(primary_color)
        canvas_obj.rect(8, height - 20, width - 8, 20, stroke=0, fill=1)
        
        # Dark gray bottom bar for footer metadata
        canvas_obj.setFillColor(colors.HexColor("#E2E8F0"))
        canvas_obj.rect(8, 0, width - 8, 30, stroke=0, fill=1)
    else:
        # Content slide top header banner background
        canvas_obj.setFillColor(colors.white)
        canvas_obj.rect(8, height - 48, width - 8, 48, stroke=0, fill=1)
        
        canvas_obj.setStrokeColor(colors.HexColor("#E2E8F0"))
        canvas_obj.setLineWidth(1)
        canvas_obj.line(8, height - 48, width, height - 48)
        
    canvas_obj.restoreState()

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        primary_color_hex = st.session_state.primary_color
        primary_color = hex_to_reportlab_color(primary_color_hex)
        project_name = st.session_state.project_name
        logo_path = st.session_state.logo_temp_path
        
        self.saveState()
        
        # Get dynamic page dimensions
        width, height = self._pagesize
        is_landscape = width > height
        
        if is_landscape:
            # --- LANDSCAPE SLIDES SETUP ---
            if self._pageNumber == 1:
                # Page 1 is the starting cover page.
                self.restoreState()
                return
                
            right_margin = width - 54
            top_header_y = height - 28
            logo_y = height - 36
            logo_x = right_margin - 68
            
        else:
            # --- STANDARD PORTRAIT PORTRAIT SETUP ---
            if self._pageNumber == 1:
                self.restoreState()
                return
                
            right_margin = width - 54
            top_header_y = height - 42
            line_header_y = height - 52
            logo_y = height - 35
            logo_x = right_margin - 68
            
            # Horizontal branding separator line
            self.setStrokeColor(primary_color)
            self.setLineWidth(1)
            self.line(54, line_header_y, right_margin, line_header_y)
            
        # 2. Draw Header Content
        self.setFont("Helvetica-Bold", 9.5)
        self.setFillColor(primary_color)
        self.drawString(54, top_header_y, project_name.upper())
        
        self.setFont("Helvetica", 8.5)
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Draw logo image in header if loaded
        if logo_path and os.path.exists(logo_path):
            try:
                self.drawImage(logo_path, logo_x, logo_y, width=68, height=22, mask='auto', preserveAspectRatio=True)
            except Exception:
                pass
                
        # 3. Draw Footer Content
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(54, 50, right_margin, 50)
        
        self.setFont("Helvetica", 8.5)
        self.setFillColor(colors.HexColor("#94A3B8"))
        self.drawRightString(right_margin, 36, f"Page {self._pageNumber} of {page_count}")
        
        # Date in the footer on the left
        from datetime import datetime
        current_date = datetime.now().strftime("%d-%m-%Y")
        self.drawString(54, 36, f"Date: {current_date}")
        
        self.restoreState()

# Helper to build "Apartado de Demos" block (common to both PDFs if items are selected)
def build_demos_pdf_block(df, primary_color, styles, sub_section_style=None, is_landscape=False):
    demo_items = df[df["Demo"] == True] if "Demo" in df.columns else pd.DataFrame()
    if demo_items.empty:
        return []
    block_elements = []
    # Custom styling
    # Let's adjust sizes for landscape presentation grade view
    font_size_header = 9 if is_landscape else 8
    font_size_body = 8.5 if is_landscape else 7.5
    padding_val = 4 if is_landscape else 3
    
    section_title_style = ParagraphStyle(
        'DemoSecTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=16 if is_landscape else 13,
        leading=20 if is_landscape else 16,
        textColor=primary_color,
        spaceBefore=18,
        spaceAfter=6
    )
    
    intro_style = ParagraphStyle(
        'DemoIntro',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10 if is_landscape else 8.5,
        leading=14 if is_landscape else 12,
        textColor=colors.HexColor("#475569"),
        spaceAfter=10
    )
    
    cell_header_style = ParagraphStyle(
        'DemoCellHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=font_size_header,
        leading=font_size_header + 3,
        textColor=colors.white
    )
    
    cell_body_style = ParagraphStyle(
        'DemoCellBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=font_size_body,
        leading=font_size_body + 3,
        textColor=colors.HexColor("#1E293B")
    )
    
    cell_body_bold_style = ParagraphStyle(
        'DemoCellBodyBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=font_size_body,
        leading=font_size_body + 3,
        textColor=colors.HexColor("#1E293B")
    )
    
    if sub_section_style is not None:
        block_elements.append(Paragraph("Product Demos", sub_section_style))
    else:
        block_elements.append(Paragraph("Product Demos", section_title_style))
 
    block_elements.append(Paragraph(
        "The following live product demonstrations have been scheduled. The listed feature owners will present these deliverables:",
        intro_style
    ))
    
    # Table layout
    table_data = [[
        Paragraph("Key", cell_header_style),
        Paragraph("Summary", cell_header_style),
        Paragraph("Epic", cell_header_style),
        Paragraph("Presenter 👤", cell_header_style)
    ]]
    
    for _, row in demo_items.iterrows():
        presenter = str(row['Assignee']) if pd.notna(row['Assignee']) and str(row['Assignee']).strip() != "" else "Unassigned"
        table_data.append([
            Paragraph(str(row['Key']), cell_body_bold_style),
            Paragraph(str(row['Summary']), cell_body_style),
            Paragraph(str(row['Epic']), cell_body_style),
            Paragraph(presenter, cell_body_bold_style)
        ])
        
    # Col Widths: Total = 504pt (Portrait) or 684pt (Landscape)
    if is_landscape:
        col_widths = [95, 269, 160, 160]
    else:
        col_widths = [95, 169, 120, 120]
        
    demo_table = Table(
        table_data,
        colWidths=col_widths
    )
    
    demo_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), padding_val),
        ('BOTTOMPADDING', (0, 0), (-1, -1), padding_val),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.8 if is_landscape else 0.5, colors.HexColor("#E2E8F0") if is_landscape else colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    
    block_elements.append(demo_table)
    block_elements.append(Spacer(1, 15))
    
    return [KeepTogether(block_elements)]

# Helper to build Target Release versions table block in PDFs (NEW requested table)
def build_next_releases_pdf_block(df, primary_color, styles, is_landscape=False):
    if df is None or df.empty:
        return []
        
    block_elements = []
    
    font_size_header = 9 if is_landscape else 8
    font_size_body = 8.5 if is_landscape else 7.5
    padding_val = 4 if is_landscape else 3
    
    cell_header_style = ParagraphStyle(
        'RelCellHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=font_size_header,
        leading=font_size_header + 3,
        textColor=colors.white
    )
    
    cell_body_style = ParagraphStyle(
        'RelCellBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=font_size_body,
        leading=font_size_body + 3,
        textColor=colors.HexColor("#1E293B")
    )
    
    cell_body_bold_style = ParagraphStyle(
        'RelCellBodyBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=font_size_body,
        leading=font_size_body + 3,
        textColor=colors.HexColor("#1E293B")
    )
    
    table_data = [[
        Paragraph("Version", cell_header_style),
        Paragraph("Target Date", cell_header_style),
        Paragraph("Key Highlights & Scope Comments", cell_header_style)
    ]]
    
    for _, row in df.iterrows():
        version = str(row.get('Version', ''))
        date = str(row.get('Target Date', ''))
        comments = str(row.get('Comments', ''))
        
        table_data.append([
            Paragraph(version, cell_body_bold_style),
            Paragraph(date, cell_body_style),
            Paragraph(comments, cell_body_style)
        ])
        
    # Col Widths: Total = 504pt (Portrait) or 684pt (Landscape)
    # Version: 80pt/100pt, Date: 80pt/100pt, Comments: 344pt/484pt
    if is_landscape:
        col_widths = [100, 100, 484]
    else:
        col_widths = [80, 80, 344]
        
    rel_table = Table(
        table_data,
        colWidths=col_widths
    )
    
    rel_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), padding_val),
        ('BOTTOMPADDING', (0, 0), (-1, -1), padding_val),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.8 if is_landscape else 0.5, colors.HexColor("#E2E8F0") if is_landscape else colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    
    block_elements.append(rel_table)
    block_elements.append(Spacer(1, 10))
    
    return block_elements

# Helper function to map Jira status strings to clean color-coded status bullets (PDF safe)
def format_status_with_emoji(status_str):
    if not status_str or not isinstance(status_str, str):
        return '<font color="#3B82F6">●</font>'
        
    st_clean = status_str.strip().lower()
    
    if st_clean in ['done', 'closed', 'resolved', 'complete']:
        return '<font color="#22C55E">●</font>'
    elif st_clean in ['in progress', 'development', 'testing', 'review', 'in dev', 'dev', 'qa']:
        return '<font color="#F59E0B">●</font>'
    elif st_clean in ['blocked', 'on hold', 'impediment', 'delayed', 'hold']:
        return '<font color="#EF4444">●</font>'
    elif st_clean in ['to do', 'open', 'backlog', 'selected for development', 'new']:
        return '<font color="#3B82F6">●</font>'
    else:
        return '<font color="#3B82F6">●</font>'

# Helper function to dynamically build and format an uploaded custom table (non-Jira) in both landscape and portrait PDFs
def build_custom_extra_table_pdf_block(df, primary_color, styles, is_landscape=False):
    if df is None or df.empty:
        return []
        
    block_elements = []
    
    # Dynamic styling matching the presentation grade
    font_size_header = 9 if is_landscape else 8
    font_size_body = 8.5 if is_landscape else 7.5
    padding_val = 4 if is_landscape else 3
    
    cell_header_style = ParagraphStyle(
        'ExtraHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=font_size_header,
        leading=font_size_header + 3,
        textColor=colors.white
    )
    
    cell_body_style = ParagraphStyle(
        'ExtraBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=font_size_body,
        leading=font_size_body + 3,
        textColor=colors.HexColor("#1E293B")
    )
    
    table_data = []
    
    # Column names as header
    header_row = [Paragraph(str(col), cell_header_style) for col in df.columns]
    table_data.append(header_row)
    
    # Data rows
    for _, row in df.iterrows():
        row_data = [Paragraph(str(val), cell_body_style) for val in row]
        table_data.append(row_data)
        
    # Compute columns widths dynamically to fill the page printable width
    total_width = 684 if is_landscape else 504
    num_cols = len(df.columns)
    col_widths = [total_width / num_cols] * num_cols
    
    extra_table = Table(
        table_data,
        colWidths=col_widths
    )
    
    extra_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), padding_val),
        ('BOTTOMPADDING', (0, 0), (-1, -1), padding_val),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.8 if is_landscape else 0.5, colors.HexColor("#E2E8F0") if is_landscape else colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    
    block_elements.append(extra_table)
    block_elements.append(Spacer(1, 15))
    return block_elements

# ---------------------------------------------------------
# 6. PDF Builder: Sprint Review PDF (Consolidated Single Table)
# ---------------------------------------------------------
def get_arrow_drawing(color):
    d = Drawing(10, 10)
    # L-shape: bottom-right to bottom-left to top-left pointing up, smaller size (10x10) and black
    d.add(PolyLine([(7, 2), (2, 2), (2, 8)], strokeColor=colors.black, strokeWidth=1.0))
    d.add(Line(0, 6, 2, 8, strokeColor=colors.black, strokeWidth=1.0))
    d.add(Line(4, 6, 2, 8, strokeColor=colors.black, strokeWidth=1.0))
    return d
def build_sprint_review_pdf(overview_df, outlook_df):
    pdf_buffer = io.BytesIO()
    
    # Setup document geometry for landscape presentation slide format
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=landscape(letter),
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )
    
    styles = getSampleStyleSheet()
    primary_color_hex = st.session_state.primary_color
    primary_color = hex_to_reportlab_color(primary_color_hex)
    
    # Custom styles (optimized for large, presentation-grade text size)
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=32,
        leading=36,
        textColor=primary_color,
        spaceAfter=12
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=13.5,
        leading=18,
        textColor=colors.HexColor("#475569"),
        spaceAfter=25
    )
    
    section_title_style = ParagraphStyle(
        'SecTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=primary_color,
        spaceBefore=15,
        spaceAfter=8
    )
    
    cell_header_style = ParagraphStyle(
        'CellHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.white
    )
    
    cell_body_style = ParagraphStyle(
        'CellBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.0,
        leading=10.5,
        textColor=colors.HexColor("#1E293B")
    )
    
    cell_body_bold_style = ParagraphStyle(
        'CellBodyBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.0,
        leading=10.5,
        textColor=colors.HexColor("#1E293B")
    )
    
    sub_section_title_style = ParagraphStyle(
        'SubSecTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14.5,
        leading=18.5,
        textColor=colors.HexColor("#475569"),
        spaceBefore=12,
        spaceAfter=5
    )

    cell_header_center_style = ParagraphStyle(
        'CellHeaderCenter',
        parent=cell_header_style,
        alignment=1 # Center
    )
    
    cell_body_center_style = ParagraphStyle(
        'CellBodyCenter',
        parent=cell_body_style,
        alignment=1 # Center
    )
    
    legend_style = ParagraphStyle(
        'LegendStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#64748B"),
        alignment=2, # Right
        spaceBefore=2,
        spaceAfter=10
    )

    # Cover Page Styles (optimized for landscape presentation)
    cover_project_style = ParagraphStyle(
        'CoverProject',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#64748B"),
        alignment=1, # Center
        spaceAfter=8
    )
    
    cover_title_style = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=40,
        leading=34,
        textColor=primary_color,
        alignment=1, # Center
        spaceAfter=6
    )
    
    cover_subtitle_style = ParagraphStyle(
        'CoverSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=20,
        textColor=colors.HexColor("#334155"),
        alignment=1, # Center
        spaceAfter=15
    )
    
    cover_date_style = ParagraphStyle(
        'CoverDate',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#64748B"),
        alignment=1, # Center
        spaceAfter=15
    )
    
    cover_welcome_style = ParagraphStyle(
        'CoverWelcome',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#475569"),
        alignment=1, # Center
        spaceBefore=15,
        spaceAfter=15
    )

    story = []

    # --- STARTING COVER PAGE ---
    sprint_num = "Sprint 14"
    if 'sprint_number' in st.session_state and str(st.session_state.sprint_number).strip() != "":
        sprint_num = str(st.session_state.sprint_number).strip()
    elif 'ov_sprint_num' in st.session_state and str(st.session_state.ov_sprint_num).strip() != "":
        sprint_num = f"Sprint {st.session_state.ov_sprint_num}"
        
    from datetime import datetime
    current_date = datetime.now().strftime("%d-%m-%Y")
    
    story.append(Spacer(1, 15))
    story.append(Paragraph(st.session_state.project_name.upper(), cover_project_style))
    story.append(Paragraph("Sprint Review", cover_title_style))
    story.append(Spacer(1, 15))
    story.append(Paragraph(f"Sprint: {sprint_num}", cover_subtitle_style))
    story.append(Paragraph(f"Date: {current_date}", cover_date_style))
    story.append(Spacer(1, 5))
    
    cover_image_path = st.session_state.cover_temp_path
    if cover_image_path and os.path.exists(cover_image_path):
        try:
            pil_img = PILImage.open(cover_image_path)
            orig_w, orig_h = pil_img.size
            max_w = 320  # Optimized landscape cover width
            max_h = 160  # Optimized landscape cover height
            scale = min(max_w / orig_w, max_h / orig_h)
            img = Image(cover_image_path, width=orig_w * scale, height=orig_h * scale)
            img.hAlign = 'CENTER'
            story.append(img)
            story.append(Spacer(1, 10))
        except Exception:
            pass
            
    welcome_text = st.session_state.sprint_welcome_message
    if welcome_text:
        story.append(Paragraph(welcome_text, cover_welcome_style))
        
    story.append(PageBreak())
    # --- END OF COVER PAGE ---
    
    # 2. Section 1: Overview
    topics_ov, bugs_ov = split_bugs_and_topics(overview_df)
    
    if not topics_ov.empty or not bugs_ov.empty:
        story.append(Paragraph("Overview:", section_title_style))
        story.append(Paragraph('<font color="#22C55E">●</font> Done &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <font color="#F59E0B">●</font> In Progress &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <font color="#EF4444">●</font> Blocked &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <font color="#3B82F6">●</font> To Do', legend_style))
        
        # 2a. Delivered Topics Sub-section
        if not topics_ov.empty:
            story.append(Paragraph("Delivered Topics", sub_section_title_style))
            # Col Widths: Total = 684pt (Landscape)
            table_data = [[
                Paragraph("Epic", cell_header_style),
                Paragraph("Key", cell_header_style),
                Paragraph("Summary", cell_header_style),
                Paragraph("Status", cell_header_center_style),
                Paragraph("Fix Version", cell_header_style)
            ]]
            
            sorted_topics = sort_items_by_type_and_epic(topics_ov)
            
            last_epic = None
            for _, row in sorted_topics.iterrows():
                epic_val = str(row['Epic']).strip() if pd.notna(row['Epic']) else "-"
                if epic_val in ["", "No Epic", "nan"]:
                    epic_val = "-"
                fv_val = extract_numeric_version(row['Fix Version'])
                if not fv_val:
                    fv_val = "-"
                    
                display_epic = epic_val
                if display_epic == last_epic:
                    if display_epic == "-":
                        epic_cell = Paragraph("-", cell_body_style)
                    else:
                        epic_cell = get_arrow_drawing(colors.HexColor("#64748B"))
                else:
                    last_epic = display_epic
                    epic_cell = Paragraph(display_epic, cell_body_style)
                    
                table_data.append([
                    epic_cell,
                    Paragraph(str(row['Key']), cell_body_bold_style),
                    Paragraph(str(row['Summary']), cell_body_style),
                    Paragraph(format_status_with_emoji(row['Status']), cell_body_center_style),
                    Paragraph(fv_val, cell_body_style)
                ])
                
            topics_table = Table(
                table_data,
                colWidths=[135, 95, 349, 50, 55]
            )
            topics_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), primary_color),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (3, 0), (3, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.8, colors.HexColor("#E2E8F0")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ]))
            story.append(topics_table)
            story.append(Spacer(1, 10))
            
        # 2b. Resolved Bugs Sub-section
        if not bugs_ov.empty:
            story.append(Paragraph("Resolved Bugs", sub_section_title_style))
            bug_data = [[
                Paragraph("Epic", cell_header_style),
                Paragraph("Key", cell_header_style),
                Paragraph("Summary", cell_header_style),
                Paragraph("Status", cell_header_center_style),
                Paragraph("Fix Version", cell_header_style)
            ]]
            
            sorted_bugs = bugs_ov.sort_values("Epic")
            
            last_epic = None
            for _, row in sorted_bugs.iterrows():
                epic_val = str(row['Epic']).strip() if pd.notna(row['Epic']) else "-"
                if epic_val in ["", "No Epic", "nan"]:
                    epic_val = "-"
                fv_val = extract_numeric_version(row['Fix Version'])
                if not fv_val:
                    fv_val = "-"
                    
                display_epic = epic_val
                if display_epic == last_epic:
                    if display_epic == "-":
                        epic_cell = Paragraph("-", cell_body_style)
                    else:
                        epic_cell = get_arrow_drawing(colors.HexColor("#64748B"))
                else:
                    last_epic = display_epic
                    epic_cell = Paragraph(display_epic, cell_body_style)
                    
                bug_data.append([
                    epic_cell,
                    Paragraph(str(row['Key']), cell_body_bold_style),
                    Paragraph(str(row['Summary']), cell_body_style),
                    Paragraph(format_status_with_emoji(row['Status']), cell_body_center_style),
                    Paragraph(fv_val, cell_body_style)
                ])
                
            bugs_table = Table(
                bug_data,
                colWidths=[155, 95, 329, 50, 55]
            )
            bugs_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), primary_color),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (3, 0), (3, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.8, colors.HexColor("#E2E8F0")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ]))
            story.append(bugs_table)
            story.append(Spacer(1, 10))
        
    story.append(Spacer(1, 10))
    
    # Render custom extra tables set to "Before Demo Table"
    before_tables = [t for t in st.session_state.custom_tables if t.get("position") == "Before Demo Table"]
    for t in before_tables:
        df_ext = t["df"]
        if df_ext is not None and not df_ext.empty:
            df_render = df_ext.drop(columns=["Select"]) if "Select" in df_ext.columns else df_ext
            story.append(PageBreak())
            extra_title = t["title"] if t["title"].strip() != "" else "Special Metrics Overview"
            story.append(Paragraph(extra_title, section_title_style))
            story.append(Spacer(1, 10))
            extra_blocks = build_custom_extra_table_pdf_block(df_render, primary_color, styles, is_landscape=True)
            if extra_blocks:
                story.extend(extra_blocks)

    # 2c. Product Demos Presenters (Moved before Outlook!)
    if overview_df is not None and not overview_df.empty:
        demo_blocks = build_demos_pdf_block(overview_df, primary_color, styles, sub_section_style=sub_section_title_style, is_landscape=True)
        if demo_blocks:
            story.extend(demo_blocks)
            story.append(Spacer(1, 15))

    # Render custom extra tables set to "After Demo Table"
    after_tables = [t for t in st.session_state.custom_tables if t.get("position") == "After Demo Table"]
    for t in after_tables:
        df_ext = t["df"]
        if df_ext is not None and not df_ext.empty:
            df_render = df_ext.drop(columns=["Select"]) if "Select" in df_ext.columns else df_ext
            story.append(PageBreak())
            extra_title = t["title"] if t["title"].strip() != "" else "Special Metrics Overview"
            story.append(Paragraph(extra_title, section_title_style))
            story.append(Spacer(1, 10))
            extra_blocks = build_custom_extra_table_pdf_block(df_render, primary_color, styles, is_landscape=True)
            if extra_blocks:
                story.extend(extra_blocks)
            
    # 3. Section 2: Outlook (Page Break isolation)
    topics_ot, bugs_ot = split_bugs_and_topics(outlook_df)
    next_release_df = st.session_state.next_release_df
    
    has_outlook = (not topics_ot.empty) or (not bugs_ot.empty) or (next_release_df is not None and not next_release_df.empty)
    if has_outlook:
        story.append(PageBreak())
        story.append(Paragraph("Outlook:", section_title_style))
        story.append(Paragraph('<font color="#22C55E">●</font> Done &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <font color="#F59E0B">●</font> In Progress &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <font color="#EF4444">●</font> Blocked &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <font color="#3B82F6">●</font> To Do', legend_style))
        
        # 3a. Planned Topics Sub-section
        if not topics_ot.empty:
            story.append(Paragraph("Planned Topics", sub_section_title_style))
            # Col Widths: Total = 684pt (Landscape)
            table_data_outlook = [[
                Paragraph("Epic", cell_header_style),
                Paragraph("Key", cell_header_style),
                Paragraph("Summary", cell_header_style),
                Paragraph("Status", cell_header_center_style),
                Paragraph("Fix Version", cell_header_style)
            ]]
            
            sorted_outlook = sort_items_by_type_and_epic(topics_ot)
            
            last_epic = None
            for _, row in sorted_outlook.iterrows():
                epic_val = str(row['Epic']).strip() if pd.notna(row['Epic']) else "-"
                if epic_val in ["", "No Epic", "nan"]:
                    epic_val = "-"
                fv_val = extract_numeric_version(row['Fix Version'])
                if not fv_val:
                    fv_val = "-"
                    
                display_epic = epic_val
                if display_epic == last_epic:
                    if display_epic == "-":
                        epic_cell = Paragraph("-", cell_body_style)
                    else:
                        epic_cell = get_arrow_drawing(colors.HexColor("#64748B"))
                else:
                    last_epic = display_epic
                    epic_cell = Paragraph(display_epic, cell_body_style)
                    
                table_data_outlook.append([
                    epic_cell,
                    Paragraph(str(row['Key']), cell_body_bold_style),
                    Paragraph(str(row['Summary']), cell_body_style),
                    Paragraph(format_status_with_emoji(row['Status']), cell_body_center_style),
                    Paragraph(fv_val, cell_body_style)
                ])
                
            outlook_table = Table(
                table_data_outlook,
                colWidths=[135, 95, 349, 50, 55]
            )
            outlook_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), primary_color),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (3, 0), (3, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.8, colors.HexColor("#E2E8F0")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ]))
            story.append(outlook_table)
            story.append(Spacer(1, 10))
            
        # 3b. Planned Bugs Sub-section
        if not bugs_ot.empty:
            story.append(Paragraph("Planned Bugs", sub_section_title_style))
            bug_data_outlook = [[
                Paragraph("Epic", cell_header_style),
                Paragraph("Key", cell_header_style),
                Paragraph("Summary", cell_header_style),
                Paragraph("Status", cell_header_center_style),
                Paragraph("Fix Version", cell_header_style)
            ]]
            
            sorted_outlook_bugs = bugs_ot.sort_values("Epic")
            
            last_epic = None
            for _, row in sorted_outlook_bugs.iterrows():
                epic_val = str(row['Epic']).strip() if pd.notna(row['Epic']) else "-"
                if epic_val in ["", "No Epic", "nan"]:
                    epic_val = "-"
                fv_val = extract_numeric_version(row['Fix Version'])
                if not fv_val:
                    fv_val = "-"
                    
                display_epic = epic_val
                if display_epic == last_epic:
                    if display_epic == "-":
                        epic_cell = Paragraph("-", cell_body_style)
                    else:
                        epic_cell = get_arrow_drawing(colors.HexColor("#64748B"))
                else:
                    last_epic = display_epic
                    epic_cell = Paragraph(display_epic, cell_body_style)
                    
                bug_data_outlook.append([
                    epic_cell,
                    Paragraph(str(row['Key']), cell_body_bold_style),
                    Paragraph(str(row['Summary']), cell_body_style),
                    Paragraph(format_status_with_emoji(row['Status']), cell_body_center_style),
                    Paragraph(fv_val, cell_body_style)
                ])
                
            bugs_outlook_table = Table(
                bug_data_outlook,
                colWidths=[155, 95, 329, 50, 55]
            )
            bugs_outlook_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), primary_color),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (3, 0), (3, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.8, colors.HexColor("#E2E8F0")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ]))
            story.append(bugs_outlook_table)
            story.append(Spacer(1, 10))
     
        # 3c. Target Releases Sub-section (Moved inside Outlook!)
        if next_release_df is not None and not next_release_df.empty:
            story.append(Paragraph("Target Releases", sub_section_title_style))
            rel_blocks = build_next_releases_pdf_block(next_release_df, primary_color, styles, is_landscape=True)
            if rel_blocks:
                story.extend(rel_blocks)
                story.append(Spacer(1, 10))
            
    doc.build(story, canvasmaker=NumberedCanvas, onFirstPage=draw_background_landscape, onLaterPages=draw_background_landscape)
    pdf_buffer.seek(0)
    return pdf_buffer


# ---------------------------------------------------------
# 8. Main Application Interface Rendering
# ---------------------------------------------------------
st.title("📋 Sprint Review Report Generator")
st.markdown("Automate and customize Sprint Review reports securely by connecting directly to **Jira** or importing local files.")

# Programmatic Navigation Sidebar
st.sidebar.markdown("### 🧭 Navigation Panel")
options_en = ["🔌 Ingestion", "✍️ Workbook", "🎨 Branding", "💾 Exporter"]

if 'active_tab' not in st.session_state or st.session_state.active_tab not in options_en:
    st.session_state.active_tab = "🔌 Ingestion"

selected_nav = st.sidebar.radio(
    "Select current step:",
    options=options_en,
    index=options_en.index(st.session_state.active_tab)
)

if selected_nav != st.session_state.active_tab:
    st.session_state.active_tab = selected_nav
    st.rerun()



# ---------------------------------------------------------
# STEP 1: Ingestion & Connection
# ---------------------------------------------------------
if st.session_state.active_tab == "🔌 Ingestion":
    st.subheader("🔌 Dual Jira Backlog Ingestion")
    st.write("Configure connection details below to load both **Overview** (What We Did) and **Outlook** (What We Will Do) ticket datasets.")
    
    # Credentials block

    st.markdown("**1. Secure Access Credentials (Jira Server PAT)**")
    col_serv, col_tok = st.columns([1, 1])
    with col_serv:
        server_input = st.text_input(
            "Jira Server URL:",
            value=st.session_state.jira_server,
            placeholder="https://company.atlassian.net",
            help="Your corporate Jira Server local address (e.g., https://devstack.vwgroup.com/jira)"
        )
    with col_tok:
        token_input = st.text_input(
            "Jira Personal Access Token (PAT):",
            value=st.session_state.jira_token,
            type="password",
            placeholder="Paste your secure PAT...",
            help="Your secure Jira Server Personal Access Token (PAT)"
        )
        
    if server_input != st.session_state.jira_server:
        st.session_state.jira_server = server_input
    if token_input != st.session_state.jira_token:
        st.session_state.jira_token = token_input
        
    st.info("💡 **Security:** Credentials are loaded locally using secure dotenv files and are never saved publicly on git repositories.")

    st.divider()

    # Issue Type Selection Checkboxes
    st.markdown("**2. Filter Ingested Issue Types**")
    st.write("Select which issue types should be loaded into the workspace:")
    col_cb1, col_cb2, col_cb3, col_cb4, col_cb5, col_cb6 = st.columns(6)
    with col_cb1:
        inc_all = st.checkbox("All / Everything", value=False, key="inc_all")
    with col_cb2:
        inc_story = st.checkbox("User Story", value=("User Story" in DEFAULT_INCLUDED_TYPES), key="inc_story", disabled=inc_all)
    with col_cb3:
        inc_task = st.checkbox("Task", value=("Task" in DEFAULT_INCLUDED_TYPES), key="inc_task", disabled=inc_all)
    with col_cb4:
        inc_tech = st.checkbox("Technical Task", value=("Technical Task" in DEFAULT_INCLUDED_TYPES), key="inc_tech", disabled=inc_all)
    with col_cb5:
        inc_subtask = st.checkbox("Technical Sub-task", value=("Technical Sub-task" in DEFAULT_INCLUDED_TYPES), key="inc_subtask", disabled=inc_all)
    with col_cb6:
        inc_bug = st.checkbox("Bug", value=("Bug" in DEFAULT_INCLUDED_TYPES), key="inc_bug", disabled=inc_all)

    selected_types = []
    if not inc_all:
        if inc_story: selected_types.append("User Story")
        if inc_task: selected_types.append("Task")
        if inc_tech: selected_types.append("Technical Task")
        if inc_subtask: selected_types.append("Technical Sub-task")
        if inc_bug: selected_types.append("Bug")

    st.divider()
    
    # Dual Query extraction panels
    st.markdown("**3. Ingestion Query Configurations**")
    col_ov_query, col_ot_query = st.columns([1, 1])
    
    with col_ov_query:
        with st.container(border=True):
            st.markdown("#### 🚀 Overview (Delivered Items)")
            st.write("Load tickets representing completed work from the current cycle.")
            
            ov_query_type = st.radio(
                "Overview Query Type:",
                options=["Overview Sprint Number", "Overview JQL Query"],
                horizontal=True,
                key="ov_query_type"
            )
            
            if ov_query_type == "Overview Sprint Number":
                ov_val = st.text_input("Sprint Number / Name:", value="1", key="ov_sprint_num")
                ov_is_sprint = True
            else:
                ov_val = st.text_area("JQL Query:", value="project = 'PROJ' AND status = 'Done' AND sprint = 12", key="ov_jql_text")
                ov_is_sprint = False
                
            if st.button("🔌 Fetch Overview", use_container_width=True):
                with st.spinner("Downloading delivered tickets from Jira..."):
                    res_df = fetch_jira_tickets_dataset(
                        st.session_state.jira_server,
                        st.session_state.jira_token,
                        ov_val,
                        is_sprint=ov_is_sprint,
                        auth_type=st.session_state.jira_auth_method,
                        email=st.session_state.jira_email
                    )
                    if res_df is not None:
                        if not res_df.empty and not inc_all:
                            res_df = res_df[res_df["Type"].isin(selected_types)].reset_index(drop=True)
                        st.session_state.overview_df = res_df
                        st.success(f"Success! Loaded {len(res_df)} Overview tickets.")
                        st.rerun()
        
    with col_ot_query:
        with st.container(border=True):
            st.markdown("#### 🔮 Outlook (Upcoming Backlog)")
            st.write("Load planned roadmap tickets representing future sprint cycles.")
            
            ot_query_type = st.radio(
                "Outlook Query Type:",
                options=["Outlook Sprint Number", "Outlook JQL Query"],
                horizontal=True,
                key="ot_query_type"
            )
            
            if ot_query_type == "Outlook Sprint Number":
                ot_val = st.text_input("Sprint Number / Name:", value="2", key="ot_sprint_num")
                ot_is_sprint = True
            else:
                ot_val = st.text_area("JQL Query:", value="project = 'PROJ' AND status = 'To Do' AND sprint = 13", key="ot_jql_text")
                ot_is_sprint = False
                
            if st.button("🔌 Fetch Outlook", use_container_width=True):
                with st.spinner("Downloading planned tickets from Jira..."):
                    res_df = fetch_jira_tickets_dataset(
                        st.session_state.jira_server,
                        st.session_state.jira_token,
                        ot_val,
                        is_sprint=ot_is_sprint,
                        auth_type=st.session_state.jira_auth_method,
                        email=st.session_state.jira_email
                    )
                    if res_df is not None:
                        if not res_df.empty and not inc_all:
                            res_df = res_df[res_df["Type"].isin(selected_types)].reset_index(drop=True)
                        st.session_state.outlook_df = res_df
                        st.success(f"Success! Loaded {len(res_df)} Outlook tickets.")
                        st.rerun()
    
    # Ingestion of Additional Custom Report Tables (Jira or CSV)
    st.subheader("📊 Ingestion of Additional Custom Table (Optional)")
    st.write("Retrieve custom data from Jira or upload a CSV file to render a custom table in a dedicated section of the document.")
    
    col_add_title, col_add_pos, col_add_source = st.columns([2, 1, 1])
    with col_add_title:
        extra_table_title = st.text_input("Additional Table Title:", value="Special Project Metrics", key="extra_table_title_input")
    with col_add_pos:
        extra_table_position = st.selectbox("Position in Report:", options=["Before Demo Table", "After Demo Table"], key="extra_table_pos_input")
    with col_add_source:
        extra_source_type = st.radio(
            "Custom Table Data Source:",
            options=["CSV Upload", "Jira JQL Query"],
            horizontal=True,
            key="extra_source_type"
        )
        
    if extra_source_type == "CSV Upload":
        up_extra = st.file_uploader("Upload Additional Table CSV File:", type=["csv"], key=f"uploader_extra_{len(st.session_state.custom_tables)}")
        if up_extra:
            if st.button("➕ Import Custom Table", use_container_width=True):
                try:
                    extra_df = pd.read_csv(up_extra)
                    if 'Select' not in extra_df.columns:
                        extra_df.insert(0, 'Select', False)
                    if 'Labels' not in extra_df.columns:
                        extra_df['Labels'] = ""
                    new_table = {
                        "title": extra_table_title if extra_table_title.strip() != "" else "Special Project Metrics",
                        "df": extra_df,
                        "position": extra_table_position
                    }
                    st.session_state.custom_tables.append(new_table)
                    st.toast(f"Custom table '{new_table['title']}' uploaded successfully!", icon="📊")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error parsing Additional CSV: {str(e)}")
    else:
        # Jira JQL Query
        custom_jql = st.text_area("JQL Query for Custom Table:", value="project = 'PROJ' AND status = 'In Progress'", key="extra_jql_text")
        if st.button("🔌 Fetch Custom Table", use_container_width=True):
            with st.spinner("Downloading custom tickets from Jira..."):
                res_df = fetch_jira_tickets_dataset(
                    st.session_state.jira_server,
                    st.session_state.jira_token,
                    custom_jql,
                    is_sprint=False,
                    auth_type=st.session_state.jira_auth_method,
                    email=st.session_state.jira_email
                )
                if res_df is not None:
                    # Filter to standard presentation columns so it renders beautifully in ReportLab
                    cols_to_keep = ["Key", "Summary", "Epic", "Status", "Fix Version", "Assignee", "Labels"]
                    cols_to_keep = [c for c in cols_to_keep if c in res_df.columns]
                    extra_df = res_df[cols_to_keep]
                    if 'Select' not in extra_df.columns:
                        extra_df.insert(0, 'Select', False)
                    if 'Labels' not in extra_df.columns:
                        extra_df['Labels'] = ""
                    new_table = {
                        "title": extra_table_title if extra_table_title.strip() != "" else "Special Project Metrics",
                        "df": extra_df,
                        "position": extra_table_position
                    }
                    st.session_state.custom_tables.append(new_table)
                    st.toast(f"Success! Loaded {len(res_df)} tickets for custom table '{new_table['title']}'.", icon="📊")
                    st.rerun()

    st.divider()
    
    # Offline Sandbox / local imports
    st.subheader("💡 Sandbox & Mock Playground")
    st.write("Don't have a live connection? Use these sandbox tools to instantly populate both Overview and Outlook datasets:")
    
    col_sand1, col_sand2 = st.columns([1, 1])
    
    with col_sand1:
        st.button("🚀 Load Mock Sprint Datasets", use_container_width=True, on_click=load_mock_sprint_data)
 
    with col_sand2:
        st.write("Or import raw local CSV files:")
        up_ov = st.file_uploader("Upload Overview CSV File:", type=["csv"], key="uploader_ov")
        up_ot = st.file_uploader("Upload Outlook CSV File:", type=["csv"], key="uploader_ot")
        
        # Ingest Overview CSV
        if up_ov:
            try:
                csv_df = pd.read_csv(up_ov)
                # Normalization
                rename_map = {
                    'key': 'Key',
                    'issue key': 'Key',
                    'summary': 'Summary',
                    'status': 'Status',
                    'fix version': 'Fix Version',
                    'fix version/s': 'Fix Version',
                    'fix versions': 'Fix Version',
                    'assignee': 'Assignee',
                    'type': 'Type',
                    'issue type': 'Type',
                    'issuetype': 'Type',
                    'labels': 'Labels'
                }
                norm_cols = {}
                epic_col_detected = None
                for c in csv_df.columns:
                    c_lower = c.strip().lower()
                    if c_lower == 'epic':
                        epic_col_detected = c
                        break
                    elif c_lower == 'custom field (epic link)' or c_lower == 'epic link':
                        epic_col_detected = c
                    elif c_lower == 'custom field (epic name)' or c_lower == 'epic name':
                        if not epic_col_detected:
                            epic_col_detected = c
                for c in csv_df.columns:
                    for k_map, v_map in rename_map.items():
                        if c.strip().lower() == k_map:
                            norm_cols[c] = v_map
                if epic_col_detected:
                    norm_cols[epic_col_detected] = 'Epic'
                if norm_cols:
                    csv_df.rename(columns=norm_cols, inplace=True)
                for req in ['Key', 'Summary', 'Epic', 'Status', 'Fix Version']:
                    if req not in csv_df.columns:
                        csv_df[req] = "N/A"
                if 'Assignee' not in csv_df.columns:
                    csv_df['Assignee'] = "Unassigned"
                if 'Type' not in csv_df.columns:
                    csv_df['Type'] = "User Story"
                if 'Labels' not in csv_df.columns:
                    csv_df['Labels'] = ""
                csv_df['Outlook'] = ""
                csv_df['Sprint Review'] = True
                csv_df['Release Notes'] = True
                csv_df['Demo'] = False
                if 'Fix Version' in csv_df.columns:
                    csv_df['Fix Version'] = csv_df['Fix Version'].apply(extract_numeric_version)
                if 'Epic' in csv_df.columns:
                    csv_df['Epic'] = csv_df['Epic'].apply(lambda x: "-" if pd.isna(x) or str(x).strip() in ["", "No Epic", "nan"] else str(x).strip())
                    if st.session_state.get("jira_server") and st.session_state.get("jira_token"):
                        try:
                            epic_keys = set(csv_df['Epic'].dropna().unique()) - {"-"}
                            epic_keys = {k for k in epic_keys if " - " not in k}
                            if epic_keys:
                                keys_str = ",".join([f"'{k}'" for k in epic_keys])
                                url = f"{st.session_state.jira_server.rstrip('/')}/rest/api/2/search"
                                headers = {"Accept": "application/json", "Content-Type": "application/json"}
                                if st.session_state.get("jira_auth_method") == "Corporate Login (Username + Password)" or st.session_state.get("jira_auth_method") == "Jira Cloud/Server Basic (Email/User + Token)":
                                    auth = (st.session_state.get("jira_email", "").strip(), st.session_state.get("jira_token", "").strip())
                                else:
                                    headers["Authorization"] = f"Bearer {st.session_state.jira_token.strip()}"
                                    auth = None
                                
                                params = {"jql": f"key in ({keys_str})", "fields": "key,summary", "maxResults": 100}
                                if auth:
                                    resp = requests.get(url, headers=headers, params=params, auth=auth, timeout=10)
                                else:
                                    resp = requests.get(url, headers=headers, params=params, timeout=10)
                                    
                                if resp.status_code == 200:
                                    epic_map = {}
                                    for issue in resp.json().get("issues", []):
                                        ek = issue.get("key")
                                        es = (issue.get("fields") or {}).get("summary")
                                        if ek and es:
                                            epic_map[ek] = f"{ek} - {es}"
                                    csv_df['Epic'] = csv_df['Epic'].apply(lambda x: epic_map.get(x, x))
                        except Exception:
                            pass
                
                # Filter by selected issue types
                if not inc_all:
                    csv_df = csv_df[csv_df["Type"].isin(selected_types)].reset_index(drop=True)
                
                st.session_state.overview_df = csv_df[['Key', 'Summary', 'Epic', 'Status', 'Fix Version', 'Labels', 'Outlook', 'Sprint Review', 'Release Notes', 'Assignee', 'Demo', 'Type']]
                st.success("Overview CSV loaded.")
                st.rerun()
            except Exception as e:
                st.error(f"Error parsing Overview CSV: {str(e)}")
                
        # Ingest Outlook CSV
        if up_ot:
            try:
                csv_df = pd.read_csv(up_ot)
                # Normalization
                rename_map = {
                    'key': 'Key',
                    'issue key': 'Key',
                    'summary': 'Summary',
                    'status': 'Status',
                    'fix version': 'Fix Version',
                    'fix version/s': 'Fix Version',
                    'fix versions': 'Fix Version',
                    'assignee': 'Assignee',
                    'type': 'Type',
                    'issue type': 'Type',
                    'issuetype': 'Type',
                    'labels': 'Labels'
                }
                norm_cols = {}
                epic_col_detected = None
                for c in csv_df.columns:
                    c_lower = c.strip().lower()
                    if c_lower == 'epic':
                        epic_col_detected = c
                        break
                    elif c_lower == 'custom field (epic link)' or c_lower == 'epic link':
                        epic_col_detected = c
                    elif c_lower == 'custom field (epic name)' or c_lower == 'epic name':
                        if not epic_col_detected:
                            epic_col_detected = c
                for c in csv_df.columns:
                    for k_map, v_map in rename_map.items():
                        if c.strip().lower() == k_map:
                            norm_cols[c] = v_map
                if epic_col_detected:
                    norm_cols[epic_col_detected] = 'Epic'
                if norm_cols:
                    csv_df.rename(columns=norm_cols, inplace=True)
                for req in ['Key', 'Summary', 'Epic', 'Status', 'Fix Version']:
                    if req not in csv_df.columns:
                        csv_df[req] = "N/A"
                if 'Assignee' not in csv_df.columns:
                    csv_df['Assignee'] = "Unassigned"
                if 'Type' not in csv_df.columns:
                    csv_df['Type'] = "User Story"
                if 'Labels' not in csv_df.columns:
                    csv_df['Labels'] = ""
                if 'Fix Version' in csv_df.columns:
                    csv_df['Fix Version'] = csv_df['Fix Version'].apply(extract_numeric_version)
                if 'Epic' in csv_df.columns:
                    csv_df['Epic'] = csv_df['Epic'].apply(lambda x: "-" if pd.isna(x) or str(x).strip() in ["", "No Epic", "nan"] else str(x).strip())
                    if st.session_state.get("jira_server") and st.session_state.get("jira_token"):
                        try:
                            epic_keys = set(csv_df['Epic'].dropna().unique()) - {"-"}
                            epic_keys = {k for k in epic_keys if " - " not in k}
                            if epic_keys:
                                keys_str = ",".join([f"'{k}'" for k in epic_keys])
                                url = f"{st.session_state.jira_server.rstrip('/')}/rest/api/2/search"
                                headers = {"Accept": "application/json", "Content-Type": "application/json"}
                                if st.session_state.get("jira_auth_method") == "Corporate Login (Username + Password)" or st.session_state.get("jira_auth_method") == "Jira Cloud/Server Basic (Email/User + Token)":
                                    auth = (st.session_state.get("jira_email", "").strip(), st.session_state.get("jira_token", "").strip())
                                else:
                                    headers["Authorization"] = f"Bearer {st.session_state.jira_token.strip()}"
                                    auth = None
                                
                                params = {"jql": f"key in ({keys_str})", "fields": "key,summary", "maxResults": 100}
                                if auth:
                                    resp = requests.get(url, headers=headers, params=params, auth=auth, timeout=10)
                                else:
                                    resp = requests.get(url, headers=headers, params=params, timeout=10)
                                    
                                if resp.status_code == 200:
                                    epic_map = {}
                                    for issue in resp.json().get("issues", []):
                                        ek = issue.get("key")
                                        es = (issue.get("fields") or {}).get("summary")
                                        if ek and es:
                                            epic_map[ek] = f"{ek} - {es}"
                                    csv_df['Epic'] = csv_df['Epic'].apply(lambda x: epic_map.get(x, x))
                        except Exception:
                            pass
                csv_df['Sprint Review'] = True
                csv_df['Release Notes'] = True
                
                # Filter by selected issue types
                if not inc_all:
                    csv_df = csv_df[csv_df["Type"].isin(selected_types)].reset_index(drop=True)
                
                st.session_state.outlook_df = csv_df[['Key', 'Summary', 'Epic', 'Status', 'Fix Version', 'Labels', 'Sprint Review', 'Release Notes', 'Assignee', 'Type']]
                st.success("Outlook CSV loaded.")
                st.rerun()
            except Exception as e:
                st.error(f"Error parsing Outlook CSV: {str(e)}")

# ---------------------------------------------------------
# STEP 2: Worktable Workspace (Tabbed Data Editor)
# ---------------------------------------------------------
elif st.session_state.active_tab == "✍️ Workbook":
    st.subheader("✍️ Workspace Workbooks: Commercial Fine-Tuning")
    st.write("Convert technical Jira summaries into elegant commercial feature descriptions, assign demo presenters, and toggle report targets.")
    if st.session_state.overview_df is None and st.session_state.outlook_df is None and not st.session_state.custom_tables:
        st.info("⚠️ Workspace empty. Please complete step **🔌 1. Ingestion & Connection** by fetching Jira data or clicking 'Load Mock Sprint Datasets'.")
    else:
        # Sorting callback functions
        def trigger_sort_ov():
            col = st.session_state.sort_ov_col
            direction = st.session_state.sort_ov_dir
            if col != "🔍 Sort by..." and st.session_state.overview_df is not None:
                ascending = (direction == "Ascending")
                st.session_state.overview_df = st.session_state.overview_df.sort_values(
                    by=col, ascending=ascending
                ).reset_index(drop=True)
                st.session_state.overview_df["Select"] = False

        def trigger_sort_ot():
            col = st.session_state.sort_ot_col
            direction = st.session_state.sort_ot_dir
            if col != "🔍 Sort by..." and st.session_state.outlook_df is not None:
                ascending = (direction == "Ascending")
                st.session_state.outlook_df = st.session_state.outlook_df.sort_values(
                    by=col, ascending=ascending
                ).reset_index(drop=True)
                st.session_state.outlook_df["Select"] = False

        def trigger_sort_ext(table_idx):
            col = st.session_state.get(f"sort_ext_{table_idx}_col", "🔍 Sort by...")
            direction = st.session_state.get(f"sort_ext_{table_idx}_dir", "Ascending")
            if col != "🔍 Sort by..." and len(st.session_state.custom_tables) > table_idx:
                ascending = (direction == "Ascending")
                df = st.session_state.custom_tables[table_idx]["df"]
                st.session_state.custom_tables[table_idx]["df"] = df.sort_values(
                    by=col, ascending=ascending
                ).reset_index(drop=True)
                st.session_state.custom_tables[table_idx]["df"]["Select"] = False

        # Subtabs for separating Overview, Outlook, and optional Custom Table editing
        tabs_list = [
            "🚀 Overview Dataset (What We Have Done)",
            "🔮 Outlook Dataset (What We Will Do next)"
        ]
        for idx, table in enumerate(st.session_state.custom_tables):
            tabs_list.append(f"📊 Custom: {table['title']}")
            
        tabs = st.tabs(tabs_list)
        work_subtab_ov = tabs[0]
        work_subtab_ot = tabs[1]
        work_subtabs_ext = tabs[2:]
        
        # Ensure 'Select' and 'Labels' columns are initialized
        if st.session_state.overview_df is not None:
            if 'Select' not in st.session_state.overview_df.columns:
                st.session_state.overview_df.insert(0, 'Select', False)
            if 'Labels' not in st.session_state.overview_df.columns:
                st.session_state.overview_df['Labels'] = ""
        if st.session_state.outlook_df is not None:
            if 'Select' not in st.session_state.outlook_df.columns:
                st.session_state.outlook_df.insert(0, 'Select', False)
            if 'Labels' not in st.session_state.outlook_df.columns:
                st.session_state.outlook_df['Labels'] = ""
        
        # Overview Dataset Workspace
        with work_subtab_ov:
            st.markdown("#### 🚀 Delivered Sprint Deliverables (Overview)")
            st.write("Edit completed features. Check the **Demo** box to assign a presentation scheduled for the final PDF demos block.")
            
            if st.session_state.overview_df is None:
                st.warning("Overview dataset is empty. Load it from Step 1.")
            else:
                ov_statuses = sorted(list(set(st.session_state.overview_df["Status"].dropna().unique()).union({"To Do", "In Progress", "Done", "Blocked", "Open", "Closed"})))
                col_cfg_ov = {
                    "Select": st.column_config.CheckboxColumn("Select 🗑️", default=False, width="small"),
                    "Key": st.column_config.TextColumn("Key 🔑", disabled=False),
                    "Type": st.column_config.SelectboxColumn("Type 🏷️", options=["User Story", "Task", "Technical Task", "Technical Sub-task", "Bug", "Epic", "Improvement", "Sub-task", "Other"], width="medium", default="User Story"),
                    "Summary": st.column_config.TextColumn("Summary ✍️", width="large"),
                    "Epic": st.column_config.TextColumn("Epic 🎯", width="medium"),
                    "Status": st.column_config.SelectboxColumn("Status 🚥", options=ov_statuses, width="small"),
                    "Fix Version": st.column_config.TextColumn("Fix Version 📦", width="small"),
                    "Labels": st.column_config.TextColumn("Labels 🏷️", width="medium"),
                    "Assignee": st.column_config.TextColumn("Responsible 👤", width="medium"),
                    "Demo": st.column_config.CheckboxColumn("Demo 📌", default=False, width="small"),
                    "Outlook": st.column_config.TextColumn("Item Outlook / Comments 🔮", width="large"),
                    "Sprint Review": st.column_config.CheckboxColumn("Sprint Review 📋", default=True, width="small"),
                    "Release Notes": st.column_config.CheckboxColumn("Release Notes 📣", default=True, width="small")
                }
                
                # Check selection state dynamically
                has_selected_ov = bool(st.session_state.overview_df["Select"].any())
                
                # Sorting & Filtering controls
                sc_col1, sc_col2, sc_col3 = st.columns([4.0, 4.0, 4.0])
                with sc_col1:
                    sort_col = st.selectbox("Sort by:", ["🔍 Sort by...", "Key", "Epic", "Status", "Type", "Fix Version", "Labels"], key="sort_ov_col", label_visibility="collapsed", on_change=trigger_sort_ov)
                with sc_col2:
                    sort_dir = st.selectbox("Order:", ["Ascending", "Descending"], key="sort_ov_dir", label_visibility="collapsed", on_change=trigger_sort_ov)
                with sc_col3:
                    filter_label = st.text_input("Filter by Label:", key="filter_ov_label", placeholder="🔍 Filter by label...", label_visibility="collapsed")
 
                # Apply filter to display
                display_df = st.session_state.overview_df
                if "Labels" in display_df.columns and filter_label.strip() != "":
                    display_df = display_df[display_df["Labels"].str.contains(filter_label.strip(), case=False, na=False)]

                edited_ov = st.data_editor(
                    display_df,
                    num_rows="dynamic",
                    use_container_width=True,
                    column_config=col_cfg_ov,
                    key="editor_ov_refined"
                )
                
                # Bottom action controls
                has_selected_ov_visible = bool(display_df["Select"].any()) if "Select" in display_df.columns else False
                toggle_icon_ov = "☑️" if has_selected_ov_visible else "⬜"
                
                bot_col_sel, bot_col1, bot_col2, bot_col3 = st.columns([1.0, 2.5, 2.5, 6.0])
                with bot_col_sel:
                    if st.button(toggle_icon_ov, key="btn_toggle_sel_ov", use_container_width=True, help="Select/Deselect All"):
                        if has_selected_ov_visible:
                            st.session_state.overview_df.loc[display_df.index, "Select"] = False
                        else:
                            st.session_state.overview_df.loc[display_df.index, "Select"] = True
                        st.rerun()
                    
                with bot_col1:
                    if st.button("Delete", key="btn_del_ov", use_container_width=True, disabled=not has_selected_ov):
                        # Filter out selected keys from master dataframe
                        selected_keys = st.session_state.overview_df[st.session_state.overview_df["Select"] == True]["Key"].tolist()
                        st.session_state.overview_df = st.session_state.overview_df[
                            ~st.session_state.overview_df["Key"].isin(selected_keys)
                        ].reset_index(drop=True)
                        st.toast("Deleted selected rows!", icon="🗑️")
                        st.rerun()
                with bot_col2:
                    if st.button("Clear", key="btn_clear_ov", use_container_width=True):
                        st.session_state.overview_df = None
                        st.rerun()

                # Duplicate in: dropdown menu
                dest_options = ["Select destination...", "Outlook"]
                if st.session_state.custom_tables:
                    dest_options.extend([f"Custom Table: {t['title']}" for t in st.session_state.custom_tables])
                
                dup_dest = st.selectbox(
                    "Duplicate in:",
                    options=dest_options,
                    key="dup_dest_ov",
                    disabled=not has_selected_ov
                )
                
                if dup_dest != "Select destination...":
                    selected_rows = st.session_state.overview_df[st.session_state.overview_df["Select"] == True].copy()
                    if dup_dest == "Outlook":
                        cols_to_keep = ["Key", "Summary", "Epic", "Status", "Fix Version", "Labels", "Sprint Review", "Release Notes", "Assignee", "Type"]
                        cols_to_keep = [c for c in cols_to_keep if c in selected_rows.columns]
                        selected_rows = selected_rows[cols_to_keep]
                        selected_rows.insert(0, "Select", False)
                        
                        if st.session_state.outlook_df is None:
                            st.session_state.outlook_df = selected_rows
                        else:
                            st.session_state.outlook_df = pd.concat([st.session_state.outlook_df, selected_rows], ignore_index=True)
                            
                        st.session_state.overview_df["Select"] = False
                        st.toast("Duplicated selected rows to Outlook!", icon="🔮")
                        st.rerun()
                    elif dup_dest.startswith("Custom Table: "):
                        target_title = dup_dest.replace("Custom Table: ", "")
                        target_idx = None
                        for idx, t in enumerate(st.session_state.custom_tables):
                            if t["title"] == target_title:
                                target_idx = idx
                                break
                        if target_idx is not None:
                            target_df = st.session_state.custom_tables[target_idx]["df"]
                            cols_to_keep = [col for col in target_df.columns if col != "Select"]
                            for col in cols_to_keep:
                                if col not in selected_rows.columns:
                                    selected_rows[col] = "-"
                            selected_rows = selected_rows[cols_to_keep]
                            selected_rows.insert(0, "Select", False)
                            
                            st.session_state.custom_tables[target_idx]["df"] = pd.concat([target_df, selected_rows], ignore_index=True)
                            st.session_state.overview_df["Select"] = False
                            st.toast(f"Duplicated selected rows to Custom Table '{target_title}'!", icon="📊")
                            st.rerun()
                
                if not edited_ov.equals(display_df):
                    # Handle deleted rows in filtered view
                    deleted_keys = set(display_df["Key"]) - set(edited_ov["Key"])
                    if deleted_keys:
                        st.session_state.overview_df = st.session_state.overview_df[
                            ~st.session_state.overview_df["Key"].isin(deleted_keys)
                        ].reset_index(drop=True)
                    # Handle updated or added rows
                    for _, row in edited_ov.iterrows():
                        key_val = row["Key"]
                        if key_val in st.session_state.overview_df["Key"].values:
                            match_idx = st.session_state.overview_df[st.session_state.overview_df["Key"] == key_val].index
                            if not match_idx.empty:
                                st.session_state.overview_df.loc[match_idx[0], row.index] = row.values
                        else:
                            st.session_state.overview_df = pd.concat([st.session_state.overview_df, pd.DataFrame([row])], ignore_index=True)
                    st.success("Overview workbook saved successfully!")
                    st.rerun()
                    
        # Outlook Dataset Workspace
        with work_subtab_ot:
            st.markdown("#### 🔮 Future Sprint Backlog Roadmap (Outlook)")
            st.write("Edit planned target initiatives. (Presenter names and Demo checkboxes are ignored here since Outlook represents future planning).")
            if st.session_state.outlook_df is None:
                st.warning("Outlook dataset is empty. Load it from Step 1.")
            else:
                ot_statuses = sorted(list(set(st.session_state.outlook_df["Status"].dropna().unique()).union({"To Do", "In Progress", "Done", "Blocked", "Open", "Closed"})))
                col_cfg_ot = {
                    "Select": st.column_config.CheckboxColumn("Select 🗑️", default=False, width="small"),
                    "Key": st.column_config.TextColumn("Key 🔑", disabled=False),
                    "Type": st.column_config.SelectboxColumn("Type 🏷️", options=["User Story", "Task", "Technical Task", "Technical Sub-task", "Bug", "Epic", "Improvement", "Sub-task", "Other"], width="medium", default="User Story"),
                    "Summary": st.column_config.TextColumn("Summary ✍️", width="large"),
                    "Epic": st.column_config.TextColumn("Epic 🎯", width="medium"),
                    "Status": st.column_config.SelectboxColumn("Status 🚥", options=ot_statuses, width="small"),
                    "Fix Version": st.column_config.TextColumn("Fix Version 📦", width="small"),
                    "Labels": st.column_config.TextColumn("Labels 🏷️", width="medium"),
                    "Assignee": st.column_config.TextColumn("Responsible 👤", width="medium"),
                    "Sprint Review": st.column_config.CheckboxColumn("Sprint Review 📋", default=True, width="small"),
                    "Release Notes": st.column_config.CheckboxColumn("Release Notes 📣", default=True, width="small")
                }
                
                # Check selection state dynamically
                has_selected_ot = bool(st.session_state.outlook_df["Select"].any())
                
                # Sorting & Filtering controls
                sc_col1, sc_col2, sc_col3 = st.columns([4.0, 4.0, 4.0])
                with sc_col1:
                    sort_col = st.selectbox("Sort by:", ["🔍 Sort by...", "Key", "Epic", "Status", "Type", "Fix Version", "Labels"], key="sort_ot_col", label_visibility="collapsed", on_change=trigger_sort_ot)
                with sc_col2:
                    sort_dir = st.selectbox("Order:", ["Ascending", "Descending"], key="sort_ot_dir", label_visibility="collapsed", on_change=trigger_sort_ot)
                with sc_col3:
                    filter_label_ot = st.text_input("Filter by Label:", key="filter_ot_label", placeholder="🔍 Filter by label...", label_visibility="collapsed")
  
                # Apply filter to display
                display_df_ot = st.session_state.outlook_df
                if "Labels" in display_df_ot.columns and filter_label_ot.strip() != "":
                    display_df_ot = display_df_ot[display_df_ot["Labels"].str.contains(filter_label_ot.strip(), case=False, na=False)]

                edited_ot = st.data_editor(
                    display_df_ot,
                    num_rows="dynamic",
                    use_container_width=True,
                    column_config=col_cfg_ot,
                    key="editor_ot_refined"
                )

                # Bottom action controls
                has_selected_ot_visible = bool(display_df_ot["Select"].any()) if "Select" in display_df_ot.columns else False
                toggle_icon_ot = "☑️" if has_selected_ot_visible else "⬜"
                
                bot_col_sel, bot_col1, bot_col2, bot_col3 = st.columns([1.0, 2.5, 2.5, 6.0])
                with bot_col_sel:
                    if st.button(toggle_icon_ot, key="btn_toggle_sel_ot", use_container_width=True, help="Select/Deselect All"):
                        if has_selected_ot_visible:
                            st.session_state.outlook_df.loc[display_df_ot.index, "Select"] = False
                        else:
                            st.session_state.outlook_df.loc[display_df_ot.index, "Select"] = True
                        st.rerun()
                with bot_col1:
                    if st.button("Delete", key="btn_del_ot", use_container_width=True, disabled=not has_selected_ot):
                        # Filter out selected keys from master dataframe
                        selected_keys = st.session_state.outlook_df[st.session_state.outlook_df["Select"] == True]["Key"].tolist()
                        st.session_state.outlook_df = st.session_state.outlook_df[
                            ~st.session_state.outlook_df["Key"].isin(selected_keys)
                        ].reset_index(drop=True)
                        st.toast("Deleted selected rows!", icon="🗑️")
                        st.rerun()
                with bot_col2:
                    if st.button("Clear", key="btn_clear_ot", use_container_width=True):
                        st.session_state.outlook_df = None
                        st.rerun()

                # Duplicate in: dropdown menu
                dup_dest_ot = st.selectbox(
                    "Duplicate in:",
                    options=["Select destination...", "Overview"],
                    key="dup_dest_ot",
                    disabled=not has_selected_ot
                )
                if dup_dest_ot == "Overview":
                    selected_rows = st.session_state.outlook_df[st.session_state.outlook_df["Select"] == True].copy()
                    selected_rows["Outlook"] = ""
                    selected_rows["Demo"] = False
                    cols_order = ["Select", "Key", "Summary", "Epic", "Status", "Fix Version", "Labels", "Outlook", "Sprint Review", "Release Notes", "Assignee", "Demo", "Type"]
                    cols_order = [c for c in cols_order if c in selected_rows.columns]
                    selected_rows = selected_rows[cols_order]
                    selected_rows["Select"] = False
                    
                    if st.session_state.overview_df is None:
                        st.session_state.overview_df = selected_rows
                    else:
                        st.session_state.overview_df = pd.concat([st.session_state.overview_df, selected_rows], ignore_index=True)
                        
                    st.session_state.outlook_df["Select"] = False
                    st.toast("Duplicated selected rows to Overview!", icon="🚀")
                    st.rerun()
                
                if not edited_ot.equals(display_df_ot):
                    # Handle deleted rows in filtered view
                    deleted_keys = set(display_df_ot["Key"]) - set(edited_ot["Key"])
                    if deleted_keys:
                        st.session_state.outlook_df = st.session_state.outlook_df[
                            ~st.session_state.outlook_df["Key"].isin(deleted_keys)
                        ].reset_index(drop=True)
                    # Handle updated or added rows
                    for _, row in edited_ot.iterrows():
                        key_val = row["Key"]
                        if key_val in st.session_state.outlook_df["Key"].values:
                            match_idx = st.session_state.outlook_df[st.session_state.outlook_df["Key"] == key_val].index
                            if not match_idx.empty:
                                st.session_state.outlook_df.loc[match_idx[0], row.index] = row.values
                        else:
                            st.session_state.outlook_df = pd.concat([st.session_state.outlook_df, pd.DataFrame([row])], ignore_index=True)
                    st.success("Outlook workbook saved successfully!")
                    st.rerun()
                 # Custom Table Dataset Workspace
        for ext_idx, ext_tab in enumerate(work_subtabs_ext):
            with ext_tab:
                table_data = st.session_state.custom_tables[ext_idx]
                title_val = table_data["title"]
                display_title = title_val if title_val.strip() != "" else f"Custom Table {ext_idx + 1}"
                
                st.markdown(f"#### 📊 Custom Table: {display_title}")
                
                # Title, Position inputs
                edit_col_title, edit_col_pos = st.columns([3, 2])
                with edit_col_title:
                    new_title = st.text_input("Rename Table Title:", value=title_val, key=f"rename_ext_{ext_idx}")
                    if new_title != title_val:
                        st.session_state.custom_tables[ext_idx]["title"] = new_title
                        st.rerun()
                with edit_col_pos:
                    new_pos = st.selectbox("Position in Report:", options=["Before Demo Table", "After Demo Table"], index=0 if table_data["position"] == "Before Demo Table" else 1, key=f"pos_ext_{ext_idx}")
                    if new_pos != table_data["position"]:
                        st.session_state.custom_tables[ext_idx]["position"] = new_pos
                        st.rerun()
                
                df_ext = table_data["df"]
                if 'Select' not in df_ext.columns:
                    df_ext.insert(0, 'Select', False)
                    
                has_selected_ext = bool(df_ext["Select"].any())
                
                col_cfg_ext = {
                    "Select": st.column_config.CheckboxColumn("Select 🗑️", default=False, width="small"),
                }
                if "Status" in df_ext.columns:
                    ext_statuses = sorted(list(set(df_ext["Status"].dropna().unique()).union({"To Do", "In Progress", "Done", "Blocked", "Open", "Closed"})))
                    col_cfg_ext["Status"] = st.column_config.SelectboxColumn("Status 🚥", options=ext_statuses, width="small")
                
                # Sorting & Filtering controls
                sc_col1, sc_col2, sc_col3 = st.columns([4.0, 4.0, 4.0])
                with sc_col1:
                    ext_cols = ["🔍 Sort by..."] + [col for col in df_ext.columns if col != "Select"]
                    sort_col = st.selectbox("Sort by:", ext_cols, key=f"sort_ext_{ext_idx}_col", label_visibility="collapsed", on_change=trigger_sort_ext, args=(ext_idx,))
                with sc_col2:
                    sort_dir = st.selectbox("Order:", ["Ascending", "Descending"], key=f"sort_ext_{ext_idx}_dir", label_visibility="collapsed", on_change=trigger_sort_ext, args=(ext_idx,))
                with sc_col3:
                    filter_label_ext = st.text_input("Filter by Label:", key=f"filter_ext_{ext_idx}_label", placeholder="🔍 Filter by label...", label_visibility="collapsed")
 
                # Apply filter to display
                display_df_ext = df_ext
                if filter_label_ext.strip() != "" and "Labels" in display_df_ext.columns:
                    display_df_ext = display_df_ext[display_df_ext["Labels"].str.contains(filter_label_ext.strip(), case=False, na=False)]

                edited_ext = st.data_editor(
                    display_df_ext,
                    num_rows="dynamic",
                    use_container_width=True,
                    column_config=col_cfg_ext,
                    key=f"editor_ext_{ext_idx}_refined"
                )
                
                # Bottom action controls
                has_selected_ext_visible = bool(display_df_ext["Select"].any()) if "Select" in display_df_ext.columns else False
                toggle_icon_ext = "☑️" if has_selected_ext_visible else "⬜"
                
                bot_col_sel, bot_col1, bot_col2, bot_col3, bot_col4 = st.columns([1.0, 2.5, 2.5, 2.5, 3.5])
                with bot_col_sel:
                    if st.button(toggle_icon_ext, key=f"btn_toggle_sel_ext_{ext_idx}", use_container_width=True, help="Select/Deselect All"):
                        if has_selected_ext_visible:
                            st.session_state.custom_tables[ext_idx]["df"].loc[display_df_ext.index, "Select"] = False
                        else:
                            st.session_state.custom_tables[ext_idx]["df"].loc[display_df_ext.index, "Select"] = True
                        st.rerun()
                with bot_col1:
                    if st.button("Delete", key=f"btn_del_ext_{ext_idx}", use_container_width=True, disabled=not has_selected_ext):
                        if "Key" in df_ext.columns:
                            selected_keys = df_ext[df_ext["Select"] == True]["Key"].tolist()
                            st.session_state.custom_tables[ext_idx]["df"] = df_ext[
                                ~df_ext["Key"].isin(selected_keys)
                            ].reset_index(drop=True)
                        else:
                            st.session_state.custom_tables[ext_idx]["df"] = df_ext[
                                df_ext["Select"] == False
                            ].reset_index(drop=True)
                        st.toast("Deleted selected rows!", icon="🗑️")
                        st.rerun()
                with bot_col2:
                    if st.button("Add Outlook", key=f"btn_dup_ext_{ext_idx}_to_ot", use_container_width=True, disabled=not has_selected_ext):
                        selected_rows = df_ext[df_ext["Select"] == True].copy()
                        cols_to_keep = ["Key", "Summary", "Epic", "Status", "Fix Version", "Labels", "Sprint Review", "Release Notes", "Assignee", "Type"]
                        for col in cols_to_keep:
                            if col not in selected_rows.columns:
                                if col in ["Sprint Review", "Release Notes"]:
                                    selected_rows[col] = True
                                elif col == "Type":
                                    selected_rows[col] = "User Story"
                                else:
                                    selected_rows[col] = "-"
                        selected_rows = selected_rows[cols_to_keep]
                        selected_rows.insert(0, "Select", False)
                        
                        if st.session_state.outlook_df is None:
                            st.session_state.outlook_df = selected_rows
                        else:
                            st.session_state.outlook_df = pd.concat([st.session_state.outlook_df, selected_rows], ignore_index=True)
                            
                        st.session_state.custom_tables[ext_idx]["df"]["Select"] = False
                        st.toast("Duplicated selected rows to Outlook!", icon="🔮")
                        st.rerun()
                with bot_col3:
                    if st.button("Clear Data", key=f"btn_clear_ext_{ext_idx}", use_container_width=True):
                        st.session_state.custom_tables[ext_idx]["df"] = pd.DataFrame(columns=df_ext.columns)
                        st.toast("Custom table dataset cleared!", icon="🧹")
                        st.rerun()
                with bot_col4:
                    if st.button("Delete Table", key=f"del_ext_tab_{ext_idx}", use_container_width=True):
                        st.session_state.custom_tables.pop(ext_idx)
                        st.toast(f"Custom table '{display_title}' deleted!", icon="🗑️")
                        st.rerun()
                        
                if not edited_ext.equals(display_df_ext):
                    master_df = st.session_state.custom_tables[ext_idx]["df"]
                    if "Key" in display_df_ext.columns and "Key" in master_df.columns:
                        # Handle deleted rows
                        deleted_keys = set(display_df_ext["Key"]) - set(edited_ext["Key"])
                        if deleted_keys:
                            master_df = master_df[
                                ~master_df["Key"].isin(deleted_keys)
                            ].reset_index(drop=True)
                        # Handle updated/added rows
                        for _, row in edited_ext.iterrows():
                            key_val = row["Key"]
                            if key_val in master_df["Key"].values:
                                match_idx = master_df[master_df["Key"] == key_val].index
                                if not match_idx.empty:
                                    master_df.loc[match_idx[0], row.index] = row.values
                            else:
                                master_df = pd.concat([master_df, pd.DataFrame([row])], ignore_index=True)
                        st.session_state.custom_tables[ext_idx]["df"] = master_df
                    else:
                        for idx, row in edited_ext.iterrows():
                            st.session_state.custom_tables[ext_idx]["df"].loc[idx] = row
                    st.success("Custom table workbook saved successfully!")
                    st.rerun()

# ---------------------------------------------------------
# STEP 3: Branding & Intro
# ---------------------------------------------------------
elif st.session_state.active_tab == "🎨 Branding":
    st.subheader("🎨 Visual Customization & Documentation Branding")
    st.write("Configure document metadata, Next Target Release targets, custom logos, and rich welcomes.")
    
    col_br_left, col_br_right = st.columns([1, 1])
    
    with col_br_left:
        st.markdown("**1. Document Metadata & Visuals**")
        
        # Project Name input
        p_name = st.text_input(
            "Project / Company Name:",
            value=st.session_state.project_name,
            placeholder="e.g. PO Tools Enterprise"
        )
        if p_name != st.session_state.project_name:
            st.session_state.project_name = p_name
            
        s_name = st.text_input(
            "Sprint Name / Number:",
            value=st.session_state.sprint_number,
            placeholder="e.g. Sprint 14",
            help="This name will appear styled on the front Cover Page of both generated reports."
        )

        if s_name != st.session_state.sprint_number:
            st.session_state.sprint_number = s_name

            
        # Target Next Releases Data Editor (NEW requested table!)
        st.markdown("**Target Next Releases**")
        st.write("Add and plan upcoming product target versions below:")
        edited_rel_df = st.data_editor(
            st.session_state.next_release_df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Version": st.column_config.TextColumn("Fix Version 📦", width="small", default="v1.3.0"),
                "Target Date": st.column_config.TextColumn("Target Date 📅", width="small", default="2026-06-30"),
                "Comments": st.column_config.TextColumn("Highlights / Comments 💬", width="large")
            },
            key="next_release_editor"
        )
        if not edited_rel_df.equals(st.session_state.next_release_df):
            st.session_state.next_release_df = edited_rel_df
            st.rerun()
            
        # 10 Predefined Premium Corporate Colors Presets
        COLOR_PRESETS_MAP = {
            "Tech Blue": "#3B82F6",
            "Indigo Purple": "#6366F1",
            "Deep Emerald": "#059669",
            "Teal Breeze": "#0D9488",
            "Sunset Gold": "#D97706",
            "Royal Violet": "#7C3AED",
            "Warm Orange": "#EA580C",
            "Crimson Red": "#DC2626",
            "Sleek Charcoal": "#475569",
            "Mint Green": "#10B981"
        }
        
        # Build dropdown options: "Name — #HEX"
        preset_options = [f"{name} — {hex_val}" for name, hex_val in COLOR_PRESETS_MAP.items()]
        preset_options.insert(0, "Custom (use color picker below)")
        
        # Find which preset matches the current color, if any
        current_color = st.session_state.primary_color.upper()
        default_idx = 0  # "Custom" by default
        for i, (name, hex_val) in enumerate(COLOR_PRESETS_MAP.items()):
            if hex_val.upper() == current_color:
                default_idx = i + 1  # +1 because "Custom" is at index 0
                break
        
        st.markdown("**Primary Color Theme**")
        selected_preset = st.selectbox(
            "Select a Color Preset:",
            options=preset_options,
            index=default_idx,
            key="color_preset_selector",
            help="Choose a predefined corporate color or select 'Custom' to pick your own."
        )
        
        # Apply the selected preset
        if selected_preset != "Custom (use color picker below)":
            # Extract hex from "Name — #HEX"
            chosen_hex = selected_preset.split(" — ")[1]
            if chosen_hex.upper() != st.session_state.primary_color.upper():
                st.session_state.primary_color = chosen_hex
                st.rerun()
        
        # Show active color swatch + fine-tune picker
        st.markdown(
            f"<div style='background-color:{st.session_state.primary_color}; width:15px; height:15px; border-radius:3px; border:1px solid #CBD5E1; display:inline-block; vertical-align:middle; margin-right:6px;'></div><span style='font-size:12px; font-weight:bold; color:#FFFFFF; vertical-align:middle;'>Active: {st.session_state.primary_color}</span>",
            unsafe_allow_html=True
        )
        
        c_picker = st.color_picker(
            "Fine-tune Accent Color (HEX):",
            value=st.session_state.primary_color
        )
        if c_picker != st.session_state.primary_color:
            st.session_state.primary_color = c_picker
            st.rerun()

            
        # Scan logos folder for presets
        logo_dir = "assets/logos"
        default_logos = []
        if os.path.exists(logo_dir):
            default_logos = [f for f in os.listdir(logo_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg'))]
            
        selected_default_logo = None
        if default_logos:
            st.markdown("**Logo Preset Options**")
            logo_options = ["None (Upload only or blank)"] + default_logos
            selected_logo_opt = st.selectbox(
                "Select a default Logo Preset from 'assets/logos/':",
                options=logo_options,
                help="Add image files inside the 'assets/logos/' directory to populate this list dynamically"
            )
            if selected_logo_opt != "None (Upload only or blank)":
                selected_default_logo = os.path.join(logo_dir, selected_logo_opt)
                
        # Brand Logo Image uploader
        logo_file = st.file_uploader(
            "Or upload a new Custom Project Brand Logo (PNG, JPEG):",
            type=["png", "jpg", "jpeg"]
        )
        
        if logo_file:
            try:
                logo_image = PILImage.open(logo_file)
                logo_temp = "tools_temp_logo.png"
                logo_image.save(logo_temp)
                st.session_state.logo_temp_path = logo_temp
                st.image(logo_image, caption="Preview of uploaded brand logo", width=150)
            except Exception as e:
                st.error(f"Error processing upload image logo: {str(e)}")
        else:
            if selected_default_logo:
                st.session_state.logo_temp_path = selected_default_logo
                try:
                    default_img = PILImage.open(selected_default_logo)
                    st.image(default_img, caption=f"Preview of logo preset: {os.path.basename(selected_default_logo)}", width=150)
                except Exception as e:
                    st.error(f"Error loading logo preset: {str(e)}")
            else:
                if st.session_state.logo_temp_path == "tools_temp_logo.png":
                    if os.path.exists("tools_temp_logo.png"):
                        try:
                            os.remove("tools_temp_logo.png")
                        except:
                            pass
                st.session_state.logo_temp_path = None
                
        # Scan covers folder for presets
        cover_dir = "assets/covers"
        default_covers = []
        if os.path.exists(cover_dir):
            default_covers = [f for f in os.listdir(cover_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg'))]
            
        selected_default_cover = None
        if default_covers:
            st.markdown("**Cover Image Preset Options**")
            cover_options = ["None (Upload only or blank)"] + default_covers
            selected_cover_opt = st.selectbox(
                "Select a default Cover Preset from 'assets/covers/':",
                options=cover_options,
                help="Add image files inside the 'assets/covers/' directory to populate this list dynamically"
            )
            if selected_cover_opt != "None (Upload only or blank)":
                selected_default_cover = os.path.join(cover_dir, selected_cover_opt)
                
        # Cover Page Hero Image uploader (NEW cover image requested uploader)
        st.markdown("**Starting Page Hero / Cover Image**")
        cover_file = st.file_uploader(
            "Or upload a new Custom Starting Page Cover Image (PNG, JPEG):",
            type=["png", "jpg", "jpeg"],
            key="cover_image_uploader"
        )
        
        if cover_file:
            try:
                cover_image = PILImage.open(cover_file)
                cover_temp = "tools_temp_cover.png"
                cover_image.save(cover_temp)
                st.session_state.cover_temp_path = cover_temp
                st.image(cover_image, caption="Preview of uploaded cover image", width=180)
            except Exception as e:
                st.error(f"Error processing cover image: {str(e)}")
        else:
            if selected_default_cover:
                st.session_state.cover_temp_path = selected_default_cover
                try:
                    default_cimg = PILImage.open(selected_default_cover)
                    st.image(default_cimg, caption=f"Preview of cover preset: {os.path.basename(selected_default_cover)}", width=180)
                except Exception as e:
                    st.error(f"Error loading cover preset: {str(e)}")
            else:
                if st.session_state.cover_temp_path == "tools_temp_cover.png":
                    if os.path.exists("tools_temp_cover.png"):
                        try:
                            os.remove("tools_temp_cover.png")
                        except:
                            pass
                st.session_state.cover_temp_path = None

        # Document Export File Names Configuration
        st.markdown("**📄 Document Export File Names Base**")
        st.write("Customize default download file name (spaces will automatically be replaced by underscores):")
        fn_sr = st.text_input(
            "Sprint Review Filename Base:",
            value=st.session_state.filename_sr,
            placeholder="Sprint_Review_Report"
        )
        if fn_sr != st.session_state.filename_sr:
            st.session_state.filename_sr = fn_sr

        with col_br_right:
            st.markdown("**2. Sprint Review Welcome Message**")
            st.write("Write the greeting message printed on the starting cover page of the Sprint Review PDF.")
            
            sprint_welcome_input = st.text_area(
                "Welcome Message Content:",
                value=st.session_state.sprint_welcome_message,
                height=180,
                key="sprint_welcome_editor"
            )
            if sprint_welcome_input != st.session_state.sprint_welcome_message:
                st.session_state.sprint_welcome_message = sprint_welcome_input

# ---------------------------------------------------------
# STEP 4: PDF Exporter
# ---------------------------------------------------------
elif st.session_state.active_tab == "💾 Exporter":
    st.subheader("💾 Branded PDF Exporters & Live Interactive Previews")
    st.write("Inspect base64 rendered previews of both documents before downloading them directly to your system.")
    
    if st.session_state.overview_df is None and st.session_state.outlook_df is None:
        st.info("⚠️ No data loaded inside workbook. Complete Step 1: Ingestion & Connection first.")
    else:
        col_export_actions, col_preview_area = st.columns([2, 3])
        
        # Prepare filtered data
        sr_ov_df = st.session_state.overview_df[st.session_state.overview_df["Sprint Review"] == True] if st.session_state.overview_df is not None else pd.DataFrame()
        sr_ot_df = st.session_state.outlook_df[st.session_state.outlook_df["Sprint Review"] == True] if st.session_state.outlook_df is not None else pd.DataFrame()
        
        rn_ov_df = st.session_state.overview_df[st.session_state.overview_df["Release Notes"] == True] if st.session_state.overview_df is not None else pd.DataFrame()
        rn_ot_df = st.session_state.outlook_df[st.session_state.outlook_df["Release Notes"] == True] if st.session_state.outlook_df is not None else pd.DataFrame()
        
        # Prepare primary release version for metadata summaries
        primary_rel = "Next Releases"
        if 'next_release_df' in st.session_state and not st.session_state.next_release_df.empty:
            primary_rel = str(st.session_state.next_release_df.iloc[0]['Version'])

        with col_export_actions:
            st.markdown("### 📥 Document Downloads")
            
            # 1. Sprint Review Card
            st.markdown(f"""
            <div class="export-card">
                <h4 style='margin-bottom:6px; color:#FFFFFF;'>📋 Sprint Review Report</h4>
                <p style='font-size:11.5px; line-height:14px;'>Unified internal report showing:
                <ul style='margin-top:2px; margin-bottom:2px; padding-left:15px; font-size:11px;'>
                    <li><b>Overview:</b> Single unified table showing what was done (no assignee).</li>
                    <li><b>Outlook:</b> Single unified table showing what will be done (Target: {primary_rel}).</li>
                    <li><b>Demos:</b> Appended demo presentations schedule with present owners.</li>
                </ul>
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            try:
                sr_pdf = build_sprint_review_pdf(sr_ov_df, sr_ot_df)
                clean_project_name = st.session_state.project_name.replace(' ', '_')
                sr_filename = f"{st.session_state.filename_sr.strip().replace(' ', '_')}_{clean_project_name}.pdf" if st.session_state.filename_sr.strip() != "" else f"Sprint_Review_Report_{clean_project_name}.pdf"
                st.download_button(
                    label="⬇️ Download PDF Sprint Review",
                    data=sr_pdf,
                    file_name=sr_filename,
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error compiling Sprint Review PDF: {str(e)}")
                
            st.markdown("<br/>", unsafe_allow_html=True)
            
            st.markdown("### 🔌 Confluence Publisher")
            st.markdown("""
            <div class="export-card" style="border-left: 4px solid #3B82F6;">
                <h4 style="margin-bottom:6px; color:#FFFFFF;">🌐 Atlassian Confluence Integration</h4>
                <p style="font-size:11.5px; line-height:14px; margin-bottom: 2px;">
                    Upload the generated Sprint Review PDF directly as an attachment to a targeted page in Confluence.
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            conf_server_input = st.text_input(
                "Confluence Server URL:",
                value=st.session_state.conf_server if st.session_state.conf_server else "https://devstack.vwgroup.com/confluence",
                placeholder="https://devstack.vwgroup.com/confluence",
                key="conf_server_url_input"
            )
            
            conf_token_input = st.text_input(
                "Confluence PAT Token:",
                value=st.session_state.conf_token,
                type="password",
                placeholder="Enter Confluence Personal Access Token (PAT)...",
                key="conf_api_token_input"
            )
            
            col_space, col_page = st.columns([1, 2])
            with col_space:
                conf_space_input = st.text_input(
                    "Space Key:",
                    value=st.session_state.conf_space_key,
                    placeholder="e.g. DS",
                    key="conf_space_key_input"
                )
            with col_page:
                conf_page_title_input = st.text_input(
                    "Page Title:",
                    value=st.session_state.conf_page_name,
                    placeholder="e.g. Sprint Review",
                    key="conf_page_name_input"
                )
                
            # Sync back to session state safely
            if conf_server_input != st.session_state.conf_server:
                st.session_state.conf_server = conf_server_input
            if conf_token_input != st.session_state.conf_token:
                st.session_state.conf_token = conf_token_input
            if conf_space_input != st.session_state.conf_space_key:
                st.session_state.conf_space_key = conf_space_input
            if conf_page_title_input != st.session_state.conf_page_name:
                st.session_state.conf_page_name = conf_page_title_input
                
            if st.button("🚀 Upload PDF to Confluence", use_container_width=True):
                with st.spinner("Connecting and uploading to Confluence..."):
                    try:
                        pdf_data = build_sprint_review_pdf(sr_ov_df, sr_ot_df)
                        clean_project_name = st.session_state.project_name.replace(' ', '_')
                        filename = f"{st.session_state.filename_sr.strip().replace(' ', '_')}_{clean_project_name}.pdf" if st.session_state.filename_sr.strip() != "" else f"Sprint_Review_Report_{clean_project_name}.pdf"
                            
                        # Call helper
                        pdf_bytes = pdf_data.getvalue()
                        page_url = upload_pdf_to_confluence(
                            server_url=st.session_state.conf_server,
                            auth_type="Personal Access Token (Bearer PAT)",
                            token=st.session_state.conf_token,
                            email="",
                            space_key=st.session_state.conf_space_key,
                            page_title=st.session_state.conf_page_name,
                            pdf_bytes=pdf_bytes,
                            filename=filename
                        )

                        st.success(f"🎉 **PDF successfully uploaded to Confluence!**")
                        st.markdown(f"[👉 Click here to view Confluence Page]({page_url})")
                    except Exception as ex:
                        st.error(f"Failed to publish to Confluence: {str(ex)}")
                        
        with col_preview_area:
            st.markdown("### 👁️ Live Document Previewer")
            st.write("Sprint Review Report PDF live preview:")
            
            active_pdf_data = None
            try:
                active_pdf_data = build_sprint_review_pdf(sr_ov_df, sr_ot_df)
            except:
                pass
                    
            if active_pdf_data is not None:
                try:
                    base64_pdf = base64.b64encode(active_pdf_data.getvalue()).decode('utf-8')
                    preview_iframe = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="520" type="application/pdf" style="border: 1px solid #3E3E4A; border-radius: 12px; background-color: #ffffff;"></iframe>'
                    st.markdown(preview_iframe, unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"Failed to render interactive base64 PDF: {str(e)}")
            else:
                st.info("Ingest data first to view live generated previews.")
