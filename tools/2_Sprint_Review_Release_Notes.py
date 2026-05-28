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
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

# ---------------------------------------------------------
# 1. Environment Loading & Session Setup
# ---------------------------------------------------------
load_dotenv()

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
if 'next_release_df' not in st.session_state:
    st.session_state.next_release_df = pd.DataFrame([
        {
            "Version": "v1.3.0",
            "Target Date": "2026-06-15",
            "Comments": "Major central dashboard UI redesign, EKS migration, and compliance preparations."
        }
    ])
if 'primary_color' not in st.session_state:
    st.session_state.primary_color = default_primary_color
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
            padding: 0.5rem 1.5rem; 
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
            "Type": "User Story"
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
            "Type": "User Story"
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
            "Type": "Task"
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
            "Type": "Technical Task"
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
            "Type": "Bug"
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
            "Type": "User Story"
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
            "Type": "Technical Task"
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
            "Type": "Task"
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
            "Type": "Bug"
        }
    ])

# Callback to load mock sprint datasets securely before widget instantiation
def load_mock_sprint_data():
    st.session_state.overview_df = generate_mock_overview_data()
    st.session_state.outlook_df = generate_mock_outlook_data()
    st.session_state.ov_sprint_num = "12"
    st.session_state.ot_sprint_num = "13"
    st.session_state.active_tab = "✍️ Workbook"
    st.session_state.nav_step_selection = "✍️ Workbook"
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
        "fields": "key,summary,status,fixVersions,parent,customfield_10008,customfield_10009,assignee,issuetype"
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
            fix_version = ", ".join([v.get("name", "") for v in fix_versions]) if fix_versions else ""
            
            # Assignee
            assignee_obj = fields.get("assignee")
            assignee = assignee_obj.get("displayName", "Unassigned") if assignee_obj else "Unassigned"
            
            # Epic detection
            epic = "No Epic"
            parent = fields.get("parent")
            if parent:
                parent_fields = parent.get("fields") or {}
                epic = parent_fields.get("summary") or parent.get("key", "No Epic")
            else:
                for custom_field in ["customfield_10008", "customfield_10009"]:
                    cf_val = fields.get(custom_field)
                    if cf_val:
                        if isinstance(cf_val, dict):
                            epic = cf_val.get("name") or cf_val.get("summary") or cf_val.get("key") or str(cf_val)
                        elif isinstance(cf_val, str):
                            epic = cf_val
                        break
                        
            # Issue Type detection & mapping
            issue_type_obj = fields.get("issuetype") or {}
            issue_type_raw = issue_type_obj.get("name", "Task")
            
            issue_type = "Task"
            raw_lower = issue_type_raw.lower()
            if "story" in raw_lower:
                issue_type = "User Story"
            elif "bug" in raw_lower:
                issue_type = "Bug"
            elif "technical" in raw_lower or "tech" in raw_lower or "performance" in raw_lower or "scaling" in raw_lower or "infrastructure" in raw_lower:
                issue_type = "Technical Task"
            elif "task" in raw_lower or "sub-task" in raw_lower:
                issue_type = "Task"
            else:
                issue_type = "Technical Task" # Default others to Technical Task
                
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
                "Type": issue_type
            })
            
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
    df_copy.sort_values(by=['_type_sort_order', 'Epic', 'Key'], inplace=True)
    df_copy.drop(columns=['_type_sort_order'], inplace=True)
    return df_copy

# ---------------------------------------------------------
# 5. PDF Generation Custom Canvas (Header, Footer, Branding)
# ---------------------------------------------------------
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
        if self._pageNumber == 1:
            # Page 1 is the starting cover page. Skip standard headers/footers drawing!
            return
            
        primary_color_hex = st.session_state.primary_color
        primary_color = hex_to_reportlab_color(primary_color_hex)
        project_name = st.session_state.project_name
        logo_path = st.session_state.logo_temp_path
        
        self.saveState()
        
        # 1. Header (Common to all pages)
        self.setFont("Helvetica-Bold", 10)
        self.setFillColor(primary_color)
        self.drawString(54, 755, project_name.upper())
        
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Date on the right
        from datetime import datetime
        current_date = datetime.now().strftime("%d-%m-%Y")
        self.drawRightString(558, 755, f"Date: {current_date}")
        
        # Horizontal branding separator line
        self.setStrokeColor(primary_color)
        self.setLineWidth(1)
        self.line(54, 745, 558, 745)
        
        # Draw logo image in header if loaded
        if logo_path and os.path.exists(logo_path):
            try:
                self.drawImage(logo_path, 490, 762, width=68, height=22, mask='auto', preserveAspectRatio=True)
            except Exception:
                pass
                
        # 2. Footer (Common to all pages)
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(54, 50, 558, 50)
        
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#94A3B8"))
        self.drawRightString(558, 38, f"Page {self._pageNumber} of {page_count}")
        
        self.restoreState()

# Helper to build "Apartado de Demos" block (common to both PDFs if items are selected)
def build_demos_pdf_block(df, primary_color, styles, sub_section_style=None):
    demo_items = df[df["Demo"] == True] if "Demo" in df.columns else pd.DataFrame()
    if demo_items.empty:
        return []
        
    block_elements = []
    
    # Custom styling
    section_title_style = ParagraphStyle(
        'DemoSecTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=primary_color,
        spaceBefore=18,
        spaceAfter=6
    )
    
    intro_style = ParagraphStyle(
        'DemoIntro',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#475569"),
        spaceAfter=10
    )
    
    cell_header_style = ParagraphStyle(
        'DemoCellHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.white
    )
    
    cell_body_style = ParagraphStyle(
        'DemoCellBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1E293B")
    )
    
    cell_body_bold_style = ParagraphStyle(
        'DemoCellBodyBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11.5,
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
        Paragraph("Reference", cell_header_style),
        Paragraph("Feature / Deliverable to Demo", cell_header_style),
        Paragraph("Associated Initiative (Epic)", cell_header_style),
        Paragraph("Demo Owner (Presenter) 👤", cell_header_style)
    ]]
    
    for _, row in demo_items.iterrows():
        presenter = str(row['Assignee']) if pd.notna(row['Assignee']) and str(row['Assignee']).strip() != "" else "Unassigned"
        table_data.append([
            Paragraph(str(row['Key']), cell_body_bold_style),
            Paragraph(str(row['Summary']), cell_body_style),
            Paragraph(str(row['Epic']), cell_body_style),
            Paragraph(presenter, cell_body_bold_style)
        ])
        
    # Col Widths: Total = 504pt
    # Ref: 64pt, Funcionalidad: 200pt, Epic: 120pt, Presentador: 120pt
    demo_table = Table(
        table_data,
        colWidths=[64, 200, 120, 120]
    )
    
    demo_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
    ]))
    
    block_elements.append(demo_table)
    block_elements.append(Spacer(1, 15))
    
    return [KeepTogether(block_elements)]

# Helper to build Target Release versions table block in PDFs (NEW requested table)
def build_next_releases_pdf_block(df, primary_color, styles):
    if df is None or df.empty:
        return []
        
    block_elements = []
    
    cell_header_style = ParagraphStyle(
        'RelCellHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.white
    )
    
    cell_body_style = ParagraphStyle(
        'RelCellBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1E293B")
    )
    
    cell_body_bold_style = ParagraphStyle(
        'RelCellBodyBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.0,
        leading=11,
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
        
    # Col Widths: Total = 504pt
    # Version: 80pt, Date: 80pt, Comments: 344pt
    rel_table = Table(
        table_data,
        colWidths=[80, 80, 344]
    )
    
    rel_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    
    block_elements.append(rel_table)
    block_elements.append(Spacer(1, 10))
    
    return block_elements

# ---------------------------------------------------------
# 6. PDF Builder: Sprint Review PDF (Consolidated Single Table)
# ---------------------------------------------------------
def build_sprint_review_pdf(overview_df, outlook_df):
    pdf_buffer = io.BytesIO()
    
    # Setup document geometry (standard letter size, 0.75" margins)
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=72,
        bottomMargin=72
    )
    
    styles = getSampleStyleSheet()
    primary_color_hex = st.session_state.primary_color
    primary_color = hex_to_reportlab_color(primary_color_hex)
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=primary_color,
        spaceAfter=12
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#475569"),
        spaceAfter=25
    )
    
    section_title_style = ParagraphStyle(
        'SecTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
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
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor("#1E293B")
    )
    
    cell_body_bold_style = ParagraphStyle(
        'CellBodyBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor("#1E293B")
    )
    
    sub_section_title_style = ParagraphStyle(
        'SubSecTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#475569"),
        spaceBefore=12,
        spaceAfter=5
    )

    # Cover Page Styles
    cover_project_style = ParagraphStyle(
        'CoverProject',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#64748B"),
        alignment=1, # Center
        spaceAfter=15
    )
    
    cover_title_style = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=32,
        leading=38,
        textColor=primary_color,
        alignment=1, # Center
        spaceAfter=10
    )
    
    cover_subtitle_style = ParagraphStyle(
        'CoverSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#334155"),
        alignment=1, # Center
        spaceAfter=25
    )
    
    cover_date_style = ParagraphStyle(
        'CoverDate',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748B"),
        alignment=1, # Center
        spaceAfter=30
    )
    
    cover_welcome_style = ParagraphStyle(
        'CoverWelcome',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=17,
        textColor=colors.HexColor("#475569"),
        alignment=1, # Center
        spaceBefore=25,
        spaceAfter=25
    )

    story = []

    # --- STARTING COVER PAGE ---
    sprint_num = "12"
    if 'ov_sprint_num' in st.session_state and str(st.session_state.ov_sprint_num).strip() != "":
        sprint_num = str(st.session_state.ov_sprint_num).strip()
        
    from datetime import datetime
    current_date = datetime.now().strftime("%d-%m-%Y")
    
    story.append(Spacer(1, 40))
    story.append(Paragraph(st.session_state.project_name.upper(), cover_project_style))
    story.append(Paragraph("Sprint Review", cover_title_style))
    story.append(Paragraph(f"Sprint: {sprint_num}", cover_subtitle_style))
    story.append(Paragraph(f"Date: {current_date}", cover_date_style))
    story.append(Spacer(1, 15))
    
    cover_image_path = st.session_state.cover_temp_path
    if cover_image_path and os.path.exists(cover_image_path):
        try:
            pil_img = PILImage.open(cover_image_path)
            orig_w, orig_h = pil_img.size
            max_w = 400  # max width in points
            max_h = 300  # max height in points
            scale = min(max_w / orig_w, max_h / orig_h)
            img = Image(cover_image_path, width=orig_w * scale, height=orig_h * scale)
            img.hAlign = 'CENTER'
            story.append(img)
            story.append(Spacer(1, 15))
        except Exception:
            pass
            
    welcome_text = st.session_state.sprint_welcome_message
    if welcome_text:
        story.append(Paragraph(welcome_text, cover_welcome_style))
        
    story.append(PageBreak())
    # --- END OF COVER PAGE ---
    
    # 1. Document Title
    story.append(Paragraph("Sprint Review", title_style))
    story.append(Paragraph("Delivered features and upcoming roadmap.", subtitle_style))
    story.append(Spacer(1, 5))
    
    # 2. Section 1: Overview
    story.append(Paragraph("Overview:", section_title_style))
    
    # 2a. Delivered Topics Sub-section
    story.append(Paragraph("Delivered Topics", sub_section_title_style))
    
    topics_ov, bugs_ov = split_bugs_and_topics(overview_df)
    
    if not topics_ov.empty:
        # Col Widths: Total = 504pt
        # Ref Key: 50pt, Epic: 90pt, Type: 75pt, Summary: 154pt, Status: 65pt, Fix Version: 70pt
        table_data = [[
            Paragraph("Ref Key", cell_header_style),
            Paragraph("Epic Initiative", cell_header_style),
            Paragraph("Type", cell_header_style),
            Paragraph("Delivered Topic (Commercial Description)", cell_header_style),
            Paragraph("Status", cell_header_style),
            Paragraph("Fix Version", cell_header_style)
        ]]
        
        sorted_topics = sort_items_by_type_and_epic(topics_ov)
        
        for _, row in sorted_topics.iterrows():
            table_data.append([
                Paragraph(str(row['Key']), cell_body_bold_style),
                Paragraph(str(row['Epic']), cell_body_style),
                Paragraph(str(row.get('Type', 'User Story')), cell_body_bold_style),
                Paragraph(str(row['Summary']), cell_body_style),
                Paragraph(str(row['Status']), cell_body_style),
                Paragraph(str(row['Fix Version']) if pd.notna(row['Fix Version']) and str(row['Fix Version']).strip() != "" else "-", cell_body_style)
            ])
            
        topics_table = Table(
            table_data,
            colWidths=[50, 90, 75, 154, 65, 70]
        )
        topics_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), primary_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ]))
        story.append(topics_table)
    else:
        story.append(Paragraph("No delivered topics in this iteration.", cell_body_style))
        
    story.append(Spacer(1, 10))
    
    # 2b. Resolved Bugs Sub-section
    story.append(Paragraph("Resolved Bugs", sub_section_title_style))
    if not bugs_ov.empty:
        bug_data = [[
            Paragraph("Ref Key", cell_header_style),
            Paragraph("Epic Initiative", cell_header_style),
            Paragraph("Resolved Bug (Commercial Description)", cell_header_style),
            Paragraph("Status", cell_header_style),
            Paragraph("Fix Version", cell_header_style)
        ]]
        
        sorted_bugs = bugs_ov.sort_values("Epic")
        
        for _, row in sorted_bugs.iterrows():
            bug_data.append([
                Paragraph(str(row['Key']), cell_body_bold_style),
                Paragraph(str(row['Epic']), cell_body_style),
                Paragraph(str(row['Summary']), cell_body_style),
                Paragraph(str(row['Status']), cell_body_style),
                Paragraph(str(row['Fix Version']) if pd.notna(row['Fix Version']) and str(row['Fix Version']).strip() != "" else "-", cell_body_style)
            ])
            
        bugs_table = Table(
            bug_data,
            colWidths=[55, 110, 194, 75, 70]
        )
        bugs_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), primary_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ]))
        story.append(bugs_table)
    else:
        story.append(Paragraph("No resolved bugs in this iteration.", cell_body_style))
        
    story.append(Spacer(1, 10))
    
    # 2c. Product Demos Presenters (Moved before Outlook!)
    if overview_df is not None and not overview_df.empty:
        demo_blocks = build_demos_pdf_block(overview_df, primary_color, styles, sub_section_style=sub_section_title_style)
        if demo_blocks:
            story.extend(demo_blocks)
            story.append(Spacer(1, 15))
    
    # 3. Section 2: Outlook (Page Break isolation)
    story.append(PageBreak())
    story.append(Paragraph("Outlook:", section_title_style))
    
    # 3a. Planned Topics Sub-section
    story.append(Paragraph("Planned Topics", sub_section_title_style))
    
    topics_ot, bugs_ot = split_bugs_and_topics(outlook_df)
    
    if not topics_ot.empty:
        table_data_outlook = [[
            Paragraph("Ref Key", cell_header_style),
            Paragraph("Epic Initiative", cell_header_style),
            Paragraph("Type", cell_header_style),
            Paragraph("Planned Feature Description", cell_header_style),
            Paragraph("Target Status", cell_header_style),
            Paragraph("Fix Version", cell_header_style)
        ]]
        
        sorted_outlook = sort_items_by_type_and_epic(topics_ot)
        
        for _, row in sorted_outlook.iterrows():
            table_data_outlook.append([
                Paragraph(str(row['Key']), cell_body_bold_style),
                Paragraph(str(row['Epic']), cell_body_style),
                Paragraph(str(row.get('Type', 'User Story')), cell_body_bold_style),
                Paragraph(str(row['Summary']), cell_body_style),
                Paragraph(str(row['Status']), cell_body_style),
                Paragraph(str(row['Fix Version']) if pd.notna(row['Fix Version']) and str(row['Fix Version']).strip() != "" else "-", cell_body_style)
            ])
            
        outlook_table = Table(
            table_data_outlook,
            colWidths=[50, 90, 75, 154, 65, 70]
        )
        outlook_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), primary_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ]))
        story.append(outlook_table)
    else:
        story.append(Paragraph("No upcoming topics planned.", cell_body_style))
        
    story.append(Spacer(1, 10))
    
    # 3b. Planned Bugs Sub-section
    story.append(Paragraph("Planned Bugs", sub_section_title_style))
    if not bugs_ot.empty:
        bug_data_outlook = [[
            Paragraph("Ref Key", cell_header_style),
            Paragraph("Epic Initiative", cell_header_style),
            Paragraph("Planned Bug Fix Description", cell_header_style),
            Paragraph("Target Status", cell_header_style),
            Paragraph("Fix Version", cell_header_style)
        ]]
        
        sorted_outlook_bugs = bugs_ot.sort_values("Epic")
        
        for _, row in sorted_outlook_bugs.iterrows():
            bug_data_outlook.append([
                Paragraph(str(row['Key']), cell_body_bold_style),
                Paragraph(str(row['Epic']), cell_body_style),
                Paragraph(str(row['Summary']), cell_body_style),
                Paragraph(str(row['Status']), cell_body_style),
                Paragraph(str(row['Fix Version']) if pd.notna(row['Fix Version']) and str(row['Fix Version']).strip() != "" else "-", cell_body_style)
            ])
            
        bugs_outlook_table = Table(
            bug_data_outlook,
            colWidths=[55, 110, 194, 75, 70]
        )
        bugs_outlook_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), primary_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ]))
        story.append(bugs_outlook_table)
    else:
        story.append(Paragraph("No upcoming bugs planned.", cell_body_style))
        
    story.append(Spacer(1, 10))

    # 3c. Target Releases Sub-section (Moved inside Outlook!)
    story.append(Paragraph("Target Releases", sub_section_title_style))
    rel_blocks = build_next_releases_pdf_block(st.session_state.next_release_df, primary_color, styles)
    if rel_blocks:
        story.extend(rel_blocks)
        story.append(Spacer(1, 10))
        
    doc.build(story, canvasmaker=NumberedCanvas)
    pdf_buffer.seek(0)
    return pdf_buffer


# ---------------------------------------------------------
# 7. PDF Builder: Release Notes PDF (Consolidated Single Table)
# ---------------------------------------------------------
def build_release_notes_pdf(overview_df, outlook_df):
    pdf_buffer = io.BytesIO()
    
    # Setup document
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=72,
        bottomMargin=72
    )
    
    styles = getSampleStyleSheet()
    primary_color_hex = st.session_state.primary_color
    primary_color = hex_to_reportlab_color(primary_color_hex)
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=primary_color,
        spaceAfter=12
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#475569"),
        spaceAfter=20
    )
    
    intro_style = ParagraphStyle(
        'DocIntro',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=14.5,
        textColor=colors.HexColor("#334155"),
        spaceAfter=20
    )
    
    section_title_style = ParagraphStyle(
        'SecTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=17,
        textColor=primary_color,
        spaceBefore=15,
        spaceAfter=8
    )
    
    cell_header_style = ParagraphStyle(
        'CellHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.white
    )
    
    cell_body_style = ParagraphStyle(
        'CellBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1E293B")
    )
    
    cell_body_bold_style = ParagraphStyle(
        'CellBodyBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1E293B")
    )
    
    sub_section_title_style = ParagraphStyle(
        'SubSecTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#475569"),
        spaceBefore=12,
        spaceAfter=5
    )

    # Cover Page Styles
    cover_project_style = ParagraphStyle(
        'CoverProject',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#64748B"),
        alignment=1, # Center
        spaceAfter=15
    )
    
    cover_title_style = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=32,
        leading=38,
        textColor=primary_color,
        alignment=1, # Center
        spaceAfter=10
    )
    
    cover_subtitle_style = ParagraphStyle(
        'CoverSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#334155"),
        alignment=1, # Center
        spaceAfter=25
    )
    
    cover_date_style = ParagraphStyle(
        'CoverDate',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748B"),
        alignment=1, # Center
        spaceAfter=30
    )

    story = []

    # --- STARTING COVER PAGE ---
    sprint_num = "12"
    if 'ov_sprint_num' in st.session_state and str(st.session_state.ov_sprint_num).strip() != "":
        sprint_num = str(st.session_state.ov_sprint_num).strip()
        
    from datetime import datetime
    current_date = datetime.now().strftime("%d-%m-%Y")
    
    story.append(Spacer(1, 50))
    story.append(Paragraph(st.session_state.project_name.upper(), cover_project_style))
    story.append(Paragraph("Release Notes", cover_title_style))
    story.append(Paragraph(f"Sprint: {sprint_num}", cover_subtitle_style))
    story.append(Paragraph(f"Date: {current_date}", cover_date_style))
    story.append(Spacer(1, 20))
    
    cover_image_path = st.session_state.cover_temp_path
    if cover_image_path and os.path.exists(cover_image_path):
        try:
            pil_img = PILImage.open(cover_image_path)
            orig_w, orig_h = pil_img.size
            max_w = 400  # max width in points
            max_h = 300  # max height in points
            scale = min(max_w / orig_w, max_h / orig_h)
            img = Image(cover_image_path, width=orig_w * scale, height=orig_h * scale)
            img.hAlign = 'CENTER'
            story.append(img)
            story.append(Spacer(1, 20))
        except Exception:
            pass
            
    story.append(PageBreak())
    # --- END OF COVER PAGE ---
    
    # 1. Document Title
    story.append(Paragraph("Release Notes", title_style))
    story.append(Paragraph("Release highlights and upcoming features.", subtitle_style))
    story.append(Spacer(1, 5))
    
    # 2. Render Custom User Intro Paragraphs
    intro_markdown = st.session_state.release_notes_intro
    intro_html = convert_markdown_to_pdf_rich_text(intro_markdown)
    story.append(Paragraph(intro_html, intro_style))
    
    # 3. Consolidated Changelog Table
    # 3. Overview Section
    story.append(Paragraph("Overview:", section_title_style))
    
    # 3a. Delivered Topics Sub-section
    story.append(Paragraph("Delivered Topics", sub_section_title_style))
    
    topics_ov, bugs_ov = split_bugs_and_topics(overview_df)
    
    if not topics_ov.empty:
        # Col Widths: Total = 504pt
        # Reference: 60pt, Epic Theme: 90pt, Type: 70pt, Delivered Capability: 204pt, Release Version: 80pt
        table_data = [[
            Paragraph("Reference", cell_header_style),
            Paragraph("Epic Theme", cell_header_style),
            Paragraph("Type", cell_header_style),
            Paragraph("Delivered Topic (Commercial Summary)", cell_header_style),
            Paragraph("Release Version", cell_header_style)
        ]]
        
        sorted_topics = sort_items_by_type_and_epic(topics_ov)
        
        for _, row in sorted_topics.iterrows():
            table_data.append([
                Paragraph(str(row['Key']), cell_body_bold_style),
                Paragraph(str(row['Epic']), cell_body_style),
                Paragraph(str(row.get('Type', 'User Story')), cell_body_bold_style),
                Paragraph(str(row['Summary']), cell_body_style),
                Paragraph(str(row['Fix Version']) if pd.notna(row['Fix Version']) and str(row['Fix Version']).strip() != "" else "General", cell_body_style)
            ])
            
        changelog_table = Table(
            table_data,
            colWidths=[60, 90, 70, 204, 80]
        )
        changelog_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), primary_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ]))
        story.append(changelog_table)
    else:
        story.append(Paragraph("No delivered topics in this release.", cell_body_style))
        
    story.append(Spacer(1, 10))
    
    # 3b. Resolved Bugs Sub-section
    story.append(Paragraph("Resolved Bugs", sub_section_title_style))
    if not bugs_ov.empty:
        bug_data = [[
            Paragraph("Reference", cell_header_style),
            Paragraph("Epic Theme", cell_header_style),
            Paragraph("Resolved Bug (Commercial Capability)", cell_header_style),
            Paragraph("Release Version", cell_header_style)
        ]]
        
        sorted_bugs = bugs_ov.sort_values("Epic")
        
        for _, row in sorted_bugs.iterrows():
            bug_data.append([
                Paragraph(str(row['Key']), cell_body_bold_style),
                Paragraph(str(row['Epic']), cell_body_style),
                Paragraph(str(row['Summary']), cell_body_style),
                Paragraph(str(row['Fix Version']) if pd.notna(row['Fix Version']) and str(row['Fix Version']).strip() != "" else "General", cell_body_style)
            ])
            
        bugs_table = Table(
            bug_data,
            colWidths=[70, 110, 244, 80]
        )
        bugs_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), primary_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ]))
        story.append(bugs_table)
    else:
        story.append(Paragraph("No resolved bugs in this release.", cell_body_style))
        
    story.append(Spacer(1, 15))
    
    # 4. Outlook Section (Page Break isolation)
    story.append(PageBreak())
    story.append(Paragraph("Outlook:", section_title_style))
    
    # 4a. Upcoming Topics Sub-section
    story.append(Paragraph("Upcoming Topics", sub_section_title_style))
    
    topics_ot, bugs_ot = split_bugs_and_topics(outlook_df)
    
    if not topics_ot.empty:
        # Col Widths: Total = 504pt
        # Reference: 60pt, Epic Theme: 90pt, Type: 70pt, Delivered Capability: 204pt, Release Version: 80pt
        table_data_upcoming = [[
            Paragraph("Reference", cell_header_style),
            Paragraph("Epic Theme", cell_header_style),
            Paragraph("Type", cell_header_style),
            Paragraph("Upcoming Improvement Description", cell_header_style),
            Paragraph("Target Version", cell_header_style)
        ]]
        
        sorted_outlook = sort_items_by_type_and_epic(topics_ot)
        
        for _, row in sorted_outlook.iterrows():
            table_data_upcoming.append([
                Paragraph(str(row['Key']), cell_body_bold_style),
                Paragraph(str(row['Epic']), cell_body_style),
                Paragraph(str(row.get('Type', 'User Story')), cell_body_bold_style),
                Paragraph(str(row['Summary']), cell_body_style),
                Paragraph(str(row['Fix Version']) if pd.notna(row['Fix Version']) and str(row['Fix Version']).strip() != "" else "-", cell_body_style)
            ])
            
        upcoming_table = Table(
            table_data_upcoming,
            colWidths=[60, 90, 70, 204, 80]
        )
        upcoming_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), primary_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ]))
        story.append(upcoming_table)
    else:
        story.append(Paragraph("No upcoming topics planned.", cell_body_style))
        
    story.append(Spacer(1, 10))
    
    # 4b. Upcoming Bugs Sub-section
    story.append(Paragraph("Upcoming Bugs", sub_section_title_style))
    if not bugs_ot.empty:
        bug_data_upcoming = [[
            Paragraph("Reference", cell_header_style),
            Paragraph("Epic Theme", cell_header_style),
            Paragraph("Planned Bug (Commercial Description)", cell_header_style),
            Paragraph("Target Version", cell_header_style)
        ]]
        
        sorted_outlook_bugs = bugs_ot.sort_values("Epic")
        
        for _, row in sorted_outlook_bugs.iterrows():
            bug_data_upcoming.append([
                Paragraph(str(row['Key']), cell_body_bold_style),
                Paragraph(str(row['Epic']), cell_body_style),
                Paragraph(str(row['Summary']), cell_body_style),
                Paragraph(str(row['Fix Version']) if pd.notna(row['Fix Version']) and str(row['Fix Version']).strip() != "" else "-", cell_body_style)
            ])
            
        bugs_upcoming_table = Table(
            bug_data_upcoming,
            colWidths=[70, 110, 244, 80]
        )
        bugs_upcoming_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), primary_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ]))
        story.append(bugs_upcoming_table)
    else:
        story.append(Paragraph("No upcoming bugs planned.", cell_body_style))
        
    story.append(Spacer(1, 10))

    # 4c. Target Releases Sub-section (Moved inside Outlook!)
    story.append(Paragraph("Target Releases", sub_section_title_style))
    rel_blocks = build_next_releases_pdf_block(st.session_state.next_release_df, primary_color, styles)
    if rel_blocks:
        story.extend(rel_blocks)
        story.append(Spacer(1, 10))
        
    doc.build(story, canvasmaker=NumberedCanvas)
    pdf_buffer.seek(0)
    return pdf_buffer



# ---------------------------------------------------------
# 8. Main Application Interface Rendering
# ---------------------------------------------------------
st.title("📋 Sprint Review & Release Notes Generator")
st.markdown("Automate and customize periodic reports securely by connecting directly to **Jira** or importing local files.")

# Programmatic Navigation Sidebar
st.sidebar.markdown("### 🧭 Navigation Panel")
options_en = ["🔌 Ingestion", "✍️ Workbook", "🎨 Branding", "💾 Exporter"]

if 'active_tab' not in st.session_state or st.session_state.active_tab not in options_en:
    st.session_state.active_tab = "🔌 Ingestion"
    st.session_state.nav_step_selection = "🔌 Ingestion"

if 'nav_step_selection' not in st.session_state or st.session_state.nav_step_selection not in options_en:
    st.session_state.nav_step_selection = st.session_state.active_tab

def on_nav_change():
    st.session_state.active_tab = st.session_state.nav_step_selection

st.sidebar.radio(
    "Select current step:",
    options=options_en,
    index=options_en.index(st.session_state.active_tab),
    key="nav_step_selection",
    on_change=on_nav_change
)



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
    
    # Dual Query extraction panels
    st.markdown("**2. Ingestion Query Configurations**")
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
                        st.session_state.overview_df = res_df
                        st.success(f"Success! Loaded {len(res_df)} Overview tickets.")
                        st.session_state.active_tab = "✍️ Workbook"
                        st.session_state.nav_step_selection = "✍️ Workbook"
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
                        st.session_state.outlook_df = res_df
                        st.success(f"Success! Loaded {len(res_df)} Outlook tickets.")
                        st.session_state.active_tab = "✍️ Workbook"
                        st.session_state.nav_step_selection = "✍️ Workbook"
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
        # Ingest Overview CSV
        if up_ov:
            try:
                csv_df = pd.read_csv(up_ov)
                # Normalization
                rename_map = {'key': 'Key', 'summary': 'Summary', 'epic': 'Epic', 'status': 'Status', 'fix version': 'Fix Version', 'assignee': 'Assignee', 'type': 'Type', 'issue type': 'Type', 'issuetype': 'Type'}
                norm_cols = {}
                for c in csv_df.columns:
                    for k_map, v_map in rename_map.items():
                        if c.strip().lower() == k_map:
                            norm_cols[c] = v_map
                if norm_cols:
                    csv_df.rename(columns=norm_cols, inplace=True)
                for req in ['Key', 'Summary', 'Epic', 'Status', 'Fix Version']:
                    if req not in csv_df.columns:
                        csv_df[req] = "N/A"
                if 'Assignee' not in csv_df.columns:
                    csv_df['Assignee'] = "Unassigned"
                if 'Type' not in csv_df.columns:
                    csv_df['Type'] = "User Story"
                csv_df['Outlook'] = ""
                csv_df['Sprint Review'] = True
                csv_df['Release Notes'] = True
                csv_df['Demo'] = False
                
                st.session_state.overview_df = csv_df[['Key', 'Summary', 'Epic', 'Status', 'Fix Version', 'Outlook', 'Sprint Review', 'Release Notes', 'Assignee', 'Demo', 'Type']]
                st.success("Overview CSV loaded.")
                st.rerun()
            except Exception as e:
                st.error(f"Error parsing Overview CSV: {str(e)}")
                
        # Ingest Outlook CSV
        if up_ot:
            try:
                csv_df = pd.read_csv(up_ot)
                # Normalization
                rename_map = {'key': 'Key', 'summary': 'Summary', 'epic': 'Epic', 'status': 'Status', 'fix version': 'Fix Version', 'assignee': 'Assignee', 'type': 'Type', 'issue type': 'Type', 'issuetype': 'Type'}
                norm_cols = {}
                for c in csv_df.columns:
                    for k_map, v_map in rename_map.items():
                        if c.strip().lower() == k_map:
                            norm_cols[c] = v_map
                if norm_cols:
                    csv_df.rename(columns=norm_cols, inplace=True)
                for req in ['Key', 'Summary', 'Epic', 'Status', 'Fix Version']:
                    if req not in csv_df.columns:
                        csv_df[req] = "N/A"
                if 'Assignee' not in csv_df.columns:
                    csv_df['Assignee'] = "Unassigned"
                if 'Type' not in csv_df.columns:
                    csv_df['Type'] = "User Story"
                csv_df['Sprint Review'] = True
                csv_df['Release Notes'] = True
                
                st.session_state.outlook_df = csv_df[['Key', 'Summary', 'Epic', 'Status', 'Fix Version', 'Sprint Review', 'Release Notes', 'Assignee', 'Type']]
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
    
    if st.session_state.overview_df is None and st.session_state.outlook_df is None:
        st.info("⚠️ Workspace empty. Please complete step **🔌 1. Ingestion & Connection** by fetching Jira data or clicking 'Load Mock Sprint Datasets'.")
    else:
        # Dual subtabs for separating Overview and Outlook editing
        work_subtab_ov, work_subtab_ot = st.tabs([
            "🚀 Overview Dataset (What We Have Done)",
            "🔮 Outlook Dataset (What We Will Do next)"
        ])
        
        # Overview Dataset Workspace
        with work_subtab_ov:
            st.markdown("#### 🚀 Delivered Sprint Deliverables (Overview)")
            st.write("Edit completed features. Check the **Demo** box to assign a presentation scheduled for the final PDF demos block.")
            
            if st.session_state.overview_df is None:
                st.warning("Overview dataset is empty. Load it from Step 1.")
            else:
                col_cfg_ov = {
                    "Key": st.column_config.TextColumn("Ref Key 🔑", disabled=True),
                    "Type": st.column_config.SelectboxColumn("Type 🏷️", options=["User Story", "Task", "Technical Task", "Bug"], width="medium", default="User Story"),
                    "Summary": st.column_config.TextColumn("Delivered Item (Commercial Summary) ✍️", width="large"),
                    "Epic": st.column_config.TextColumn("Epic Initiative 🎯", width="medium"),
                    "Status": st.column_config.SelectboxColumn("Status 🚥", options=["To Do", "In Progress", "Done", "Blocked", "Open", "Closed"], width="small"),
                    "Fix Version": st.column_config.TextColumn("Version 📦", width="small"),
                    "Assignee": st.column_config.TextColumn("Demo Presenter 👤", width="medium"),
                    "Demo": st.column_config.CheckboxColumn("Demo 📌", default=False, width="small"),
                    "Outlook": st.column_config.TextColumn("Item Outlook / Comments 🔮", width="large"),
                    "Sprint Review": st.column_config.CheckboxColumn("Sprint Review 📋", default=True, width="small"),
                    "Release Notes": st.column_config.CheckboxColumn("Release Notes 📣", default=True, width="small")
                }
                
                st.info("💡 **Tip:** To delete a row from the table, select it by clicking the checkbox on the far left (next to the row number) and press the **Delete** or **Backspace** key on your keyboard.")

                
                edited_ov = st.data_editor(

                    st.session_state.overview_df,
                    num_rows="dynamic",
                    use_container_width=True,
                    column_config=col_cfg_ov,
                    key="editor_ov_refined"
                )
                
                if not edited_ov.equals(st.session_state.overview_df):
                    st.session_state.overview_df = edited_ov
                    st.success("Overview workbook saved successfully!")
                    st.rerun()
                    
        # Outlook Dataset Workspace
        with work_subtab_ot:
            st.markdown("#### 🔮 Future Sprint Backlog Roadmap (Outlook)")
            st.write("Edit planned target initiatives. (Presenter names and Demo checkboxes are ignored here since Outlook represents future planning).")
            
            if st.session_state.outlook_df is None:
                st.warning("Outlook dataset is empty. Load it from Step 1.")
            else:
                col_cfg_ot = {
                    "Key": st.column_config.TextColumn("Ref Key 🔑", disabled=True),
                    "Type": st.column_config.SelectboxColumn("Type 🏷️", options=["User Story", "Task", "Technical Task", "Bug"], width="medium", default="User Story"),
                    "Summary": st.column_config.TextColumn("Planned Future Item (Commercial Summary) ✍️", width="large"),
                    "Epic": st.column_config.TextColumn("Epic Initiative 🎯", width="medium"),
                    "Status": st.column_config.SelectboxColumn("Status 🚥", options=["To Do", "In Progress", "Done", "Blocked", "Open", "Closed"], width="small"),
                    "Fix Version": st.column_config.TextColumn("Target Version 📦", width="small"),
                    "Assignee": st.column_config.TextColumn("Assignee Owner 👤", width="medium"),
                    "Sprint Review": st.column_config.CheckboxColumn("Sprint Review 📋", default=True, width="small"),
                    "Release Notes": st.column_config.CheckboxColumn("Release Notes 📣", default=True, width="small")
                }
                
                st.info("💡 **Tip:** To delete a row from the table, select it by clicking the checkbox on the far left (next to the row number) and press the **Delete** or **Backspace** key on your keyboard.")

                
                edited_ot = st.data_editor(

                    st.session_state.outlook_df,
                    num_rows="dynamic",
                    use_container_width=True,
                    column_config=col_cfg_ot,
                    key="editor_ot_refined"
                )
                
                if not edited_ot.equals(st.session_state.outlook_df):
                    st.session_state.outlook_df = edited_ot
                    st.success("Outlook workbook saved successfully!")
                    st.rerun()
                    
        # General workspace reset controls
        if st.button("🗑️ Clear and Wipe Both Workbooks"):
            st.session_state.overview_df = None
            st.session_state.outlook_df = None
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
                "Version": st.column_config.TextColumn("Release Version 📦", width="small", default="v1.3.0"),
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

                
        with col_br_right:
            st.markdown("**2. Release Notes Introduction (Rich Text / Markdown)**")
            st.write("Write the welcoming customer intro paragraph printed at the top of your Release Notes PDF document.")
            
            intro_in = st.text_area(
                "Introduction Content:",
                value=st.session_state.release_notes_intro,
                height=250
            )
            if intro_in != st.session_state.release_notes_intro:
                st.session_state.release_notes_intro = intro_in
                
            with st.expander("👁️ View Live Markdown Preview"):
                st.markdown(st.session_state.release_notes_intro)
                
            st.markdown("**3. Sprint Review Welcome Message**")
            st.write("Write the greeting message printed on the starting cover page of the Sprint Review PDF.")
            
            sprint_welcome_input = st.text_area(
                "Welcome Message Content:",
                value=st.session_state.sprint_welcome_message,
                height=120,
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
                st.download_button(
                    label="⬇️ Download PDF Sprint Review",
                    data=sr_pdf,
                    file_name=f"Sprint_Review_Report_{st.session_state.project_name.replace(' ', '_')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error compiling Sprint Review PDF: {str(e)}")
                
            st.markdown("<br/>", unsafe_allow_html=True)
            
            # 2. Release Notes Card
            st.markdown(f"""
            <div class="export-card">
                <h4 style='margin-bottom:6px; color:#FFFFFF;'>📣 Release Notes</h4>
                <p style='font-size:11.5px; line-height:14px;'>Customer-facing release document featuring:
                <ul style='margin-top:2px; margin-bottom:2px; padding-left:15px; font-size:11px;'>
                    <li>Your custom rich welcome intro paragraph.</li>
                    <li><b>Highlights:</b> Consolidated delivered items single table.</li>
                    <li><b>Roadmap:</b> Consolidated next release highlights (Target: {primary_rel}).</li>
                </ul>
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            try:
                rn_pdf = build_release_notes_pdf(rn_ov_df, rn_ot_df)
                st.download_button(
                    label="⬇️ Download PDF Release Notes",
                    data=rn_pdf,
                    file_name=f"Release_Notes_{st.session_state.project_name.replace(' ', '_')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error compiling Release Notes PDF: {str(e)}")
                
            st.markdown("<br/>", unsafe_allow_html=True)
            st.markdown("### 🔌 Confluence Publisher")
            st.markdown("""
            <div class="export-card" style="border-left: 4px solid #3B82F6;">
                <h4 style="margin-bottom:6px; color:#FFFFFF;">🌐 Atlassian Confluence Integration</h4>
                <p style="font-size:11.5px; line-height:14px; margin-bottom: 2px;">
                    Upload generated PDFs directly as attachments to a targeted page in Confluence.
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
                    placeholder="e.g. Release Notes",
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
                
            target_doc = st.selectbox(
                "Select PDF Document to Upload:",
                options=["Sprint Review Report 📋", "Release Notes 📣"],
                key="conf_target_doc"
            )
            
            if st.button("🚀 Upload PDF to Confluence", use_container_width=True):
                with st.spinner("Connecting and uploading to Confluence..."):
                    try:
                        # Compile selected PDF
                        if "Sprint Review" in target_doc:
                            pdf_data = build_sprint_review_pdf(sr_ov_df, sr_ot_df)
                            filename = f"Sprint_Review_Report_{st.session_state.project_name.replace(' ', '_')}.pdf"
                        else:
                            pdf_data = build_release_notes_pdf(rn_ov_df, rn_ot_df)
                            filename = f"Release_Notes_{st.session_state.project_name.replace(' ', '_')}.pdf"
                            
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
            st.write("Toggle between documents to see an interactive, scrollable PDF preview below:")
            
            sel_preview = st.radio(
                "Document Preview Target:",
                options=["Sprint Review Report 📋", "Release Notes 📣"],
                horizontal=True
            )
            
            active_pdf_data = None
            if "Sprint Review" in sel_preview:
                try:
                    active_pdf_data = build_sprint_review_pdf(sr_ov_df, sr_ot_df)
                except:
                    pass
            else:
                try:
                    active_pdf_data = build_release_notes_pdf(rn_ov_df, rn_ot_df)
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
