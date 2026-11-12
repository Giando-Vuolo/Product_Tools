import truststore
truststore.inject_into_ssl()  # verify TLS with the OS trust store (corporate proxies such as Zscaler)
import streamlit as st
import html
import os
import requests
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from utils.tunnel import start_tunnel, get_tunnel_url, get_tunnel_error, set_tunnel_url
from utils.ai_helpers import get_ollama_models
from utils.sonar_helpers import check_sonar_connection
from utils.sbom_helpers import check_sbom_connection
from utils.vanguard_helpers import check_vanguard_connection
from utils.access import is_remote_request, check_access_password
from utils.connection_checks import check_jira_connection, check_confluence_connection
from utils.stepper import inject_stepper_css, active_step_html, step_label

# Load environment variables
load_dotenv(override=True)
default_primary_color = os.getenv("PRIMARY_COLOR", "#3B82F6")
if 'primary_color' not in st.session_state or st.session_state.get('prev_env_color') != default_primary_color:
    st.session_state.primary_color = default_primary_color
    st.session_state.prev_env_color = default_primary_color


def _request_headers():
    """Headers of the current browser request ({} when unavailable)."""
    try:
        if hasattr(st, "context") and hasattr(st.context, "headers"):
            return dict(st.context.headers or {})
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        return dict(_get_websocket_headers() or {})
    except Exception:
        return {}


# Requests arriving through the Cloudflare tunnel (or any proxy) are "remote":
# they must authenticate and can never read or change the host credentials.
LOCAL_API_URL = os.getenv("LOCAL_API_URL", "http://localhost:8000").rstrip("/")
request_headers = _request_headers()
IS_REMOTE = is_remote_request(request_headers)


def _secret_input(label, state_key, widget_key):
    """Password input that never sends the stored secret to the browser.

    Leaving the field empty keeps the stored value; typing a new value replaces it.
    Returns the effective secret.
    """
    stored = st.session_state.get(state_key, "") or ""
    entered = st.text_input(
        label,
        value="",
        type="password",
        key=widget_key,
        placeholder="•••••••• stored (leave blank to keep)" if stored else "",
    )
    return entered if entered else stored


def save_credentials_to_env():
    if IS_REMOTE:
        raise PermissionError("Credentials can only be changed from the host machine.")
    env_path = ".env"
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    kv = {}
    for line in lines:
        line_strip = line.strip()
        if line_strip and not line_strip.startswith("#") and "=" in line_strip:
            parts = line_strip.split("=", 1)
            kv[parts[0].strip()] = parts[1].strip()
            
    kv["JIRA_SERVER"] = st.session_state.jira_server
    kv["JIRA_API_TOKEN"] = st.session_state.jira_token
    kv["JIRA_AUTH_METHOD"] = st.session_state.jira_auth_method
    kv["JIRA_EMAIL"] = st.session_state.jira_email
    kv["CONFLUENCE_SERVER"] = st.session_state.conf_server
    kv["CONFLUENCE_API_TOKEN"] = st.session_state.conf_token
    kv["OLLAMA_URL"] = st.session_state.ollama_url
    kv["SONAR_SERVER"] = st.session_state.sonar_server
    kv["SONAR_TOKEN"] = st.session_state.sonar_token
    kv["SONAR_COMPONENT"] = st.session_state.sonar_component
    kv["SBOM_SERVER"] = st.session_state.sbom_server
    kv["SBOM_API_KEY"] = st.session_state.sbom_api_key
    kv["SBOM_API_SECRET"] = st.session_state.sbom_api_secret
    kv["SBOM_NAMESPACE_ID"] = st.session_state.sbom_namespace_id
    kv["SBOM_APP_ID"] = st.session_state.sbom_app_id
    kv["VANGUARD_PROJECT_ID"] = st.session_state.vanguard_project_id
    kv["VANGUARD_CLIENT_ID"] = st.session_state.vanguard_client_id
    kv["VANGUARD_CLIENT_SECRET"] = st.session_state.vanguard_client_secret

    new_lines = []
    keys_written = set()
    for line in lines:
        line_strip = line.strip()
        if line_strip and not line_strip.startswith("#") and "=" in line_strip:
            parts = line_strip.split("=", 1)
            k_clean = parts[0].strip()
            if k_clean in kv:
                new_lines.append(f"{k_clean}={kv[k_clean]}\n")
                keys_written.add(k_clean)
                continue
        new_lines.append(line)
        
    for k, v in kv.items():
        if k not in keys_written:
            new_lines.append(f"{k}={v}\n")
            
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

# Initialize central credentials in session state if not set
if "jira_server" not in st.session_state:
    st.session_state.jira_server = os.getenv("JIRA_SERVER", "")
if "jira_token" not in st.session_state:
    st.session_state.jira_token = os.getenv("JIRA_API_TOKEN", "")
if "jira_email" not in st.session_state:
    st.session_state.jira_email = os.getenv("JIRA_EMAIL", "")
if "jira_auth_method" not in st.session_state:
    st.session_state.jira_auth_method = os.getenv("JIRA_AUTH_METHOD", "Personal Access Token (Bearer PAT)")
if "conf_server" not in st.session_state:
    st.session_state.conf_server = os.getenv("CONFLUENCE_SERVER", "")
if "conf_token" not in st.session_state:
    st.session_state.conf_token = os.getenv("CONFLUENCE_API_TOKEN", "")
if "ollama_url" not in st.session_state:
    st.session_state.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
if "ollama_models" not in st.session_state:
    st.session_state.ollama_models = []

if "sonar_server" not in st.session_state:
    st.session_state.sonar_server = os.getenv("SONAR_SERVER", "https://sonar.your-company.com")
if "sonar_token" not in st.session_state:
    st.session_state.sonar_token = os.getenv("SONAR_TOKEN", "")
if "sonar_component" not in st.session_state:
    st.session_state.sonar_component = os.getenv("SONAR_COMPONENT", "")

if "sbom_server" not in st.session_state:
    st.session_state.sbom_server = os.getenv("SBOM_SERVER", "https://sbom.your-company.com")
if "sbom_api_key" not in st.session_state:
    st.session_state.sbom_api_key = os.getenv("SBOM_API_KEY", "")
if "sbom_api_secret" not in st.session_state:
    st.session_state.sbom_api_secret = os.getenv("SBOM_API_SECRET", "")
if "sbom_namespace_id" not in st.session_state:
    st.session_state.sbom_namespace_id = os.getenv("SBOM_NAMESPACE_ID", "")
if "sbom_app_id" not in st.session_state:
    st.session_state.sbom_app_id = os.getenv("SBOM_APP_ID", "")

if "vanguard_project_id" not in st.session_state:
    st.session_state.vanguard_project_id = os.getenv("VANGUARD_PROJECT_ID", "")
if "vanguard_client_id" not in st.session_state:
    st.session_state.vanguard_client_id = os.getenv("VANGUARD_CLIENT_ID", "")
if "vanguard_client_secret" not in st.session_state:
    st.session_state.vanguard_client_secret = os.getenv("VANGUARD_CLIENT_SECRET", "")

QUALITY_INTEGRATIONS = (
    ("sonar", "SonarQube", check_sonar_connection),
    ("sbom", "SBOM", check_sbom_connection),
    ("vanguard", "Vanguard", check_vanguard_connection),
)

def check_quality_integrations(args_by_key, skip_unconfigured=False):
    """Tests SonarQube, SBOM and Vanguard, stores each status in session state and returns (label, status, msg)."""
    results = []
    for key, label, check in QUALITY_INTEGRATIONS:
        args = args_by_key[key]
        if not all(a and str(a).strip() for a in args):
            status, msg = ("Not checked", "") if skip_unconfigured else ("Failed", "Configuration incomplete")
        else:
            ok, msg = check(*args)
            status = "Success" if ok else "Failed"
        st.session_state[f"{key}_connection_status"] = status
        st.session_state[f"{key}_connection_msg"] = msg
        results.append((label, status, msg))
    return results

def quality_integration_args():
    return {
        "sonar": (st.session_state.sonar_server, st.session_state.sonar_token, st.session_state.sonar_component),
        "sbom": (st.session_state.sbom_server, st.session_state.sbom_api_key, st.session_state.sbom_api_secret,
                 st.session_state.sbom_namespace_id, st.session_state.sbom_app_id),
        "vanguard": (st.session_state.vanguard_project_id, st.session_state.vanguard_client_id,
                     st.session_state.vanguard_client_secret),
    }

# Perform automatic connection checks on session initialization
if "jira_connection_status" not in st.session_state:
    st.session_state.jira_connection_status = "Not checked"
    st.session_state.jira_connection_msg = ""
    st.session_state.conf_connection_status = "Not checked"
    st.session_state.conf_connection_msg = ""
    st.session_state.ollama_connection_status = "Not checked"
    st.session_state.ollama_connection_msg = ""
    st.session_state.api_connection_status = "Not checked"
    st.session_state.api_connection_msg = ""

    # Test Jira and Confluence connections (shared helpers in utils/connection_checks.py)
    auth_method = st.session_state.jira_auth_method
    email = st.session_state.jira_email
    if st.session_state.jira_server and st.session_state.jira_token:
        ok, msg = check_jira_connection(st.session_state.jira_server, st.session_state.jira_token,
                                        auth_method, email, timeout=5)
        st.session_state.jira_connection_status = "Success" if ok else "Failed"
        st.session_state.jira_connection_msg = msg
    if st.session_state.conf_server and st.session_state.conf_token:
        ok, msg = check_confluence_connection(st.session_state.conf_server, st.session_state.conf_token,
                                              auth_method, email, timeout=5)
        st.session_state.conf_connection_status = "Success" if ok else "Failed"
        st.session_state.conf_connection_msg = msg

    # Test Ollama Connection
    ourl = st.session_state.ollama_url
    if ourl:
        try:
            models = get_ollama_models(ourl)
            if models:
                st.session_state.ollama_connection_status = "Success"
                st.session_state.ollama_connection_msg = f"{len(models)} models found"
                st.session_state.ollama_models = models
            else:
                st.session_state.ollama_connection_status = "Failed"
                st.session_state.ollama_connection_msg = "No models or offline"
        except Exception as e:
            st.session_state.ollama_connection_status = "Failed"
            st.session_state.ollama_connection_msg = f"Connection Failed ({e})"

    # Test API Connection
    try:
        api_resp = requests.get(f"{LOCAL_API_URL}/openapi.json", timeout=2)
        if api_resp.status_code == 200:
            st.session_state.api_connection_status = "Success"
            st.session_state.api_connection_msg = "Connected"
        else:
            st.session_state.api_connection_status = "Failed"
            st.session_state.api_connection_msg = f"HTTP {api_resp.status_code}"
    except Exception:
        st.session_state.api_connection_status = "Failed"
        st.session_state.api_connection_msg = "Offline"

    # Test SonarQube, SBOM and Vanguard (only those fully configured)
    check_quality_integrations(quality_integration_args(), skip_unconfigured=True)

# 1. Define the page objects first so they are globally accessible
progress_page = st.Page("tools/1_Quarterly_Progress.py", title="Progress", icon="📈")
planner_page = st.Page("tools/1_Quarterly_Planner.py", title="Planning", icon="🗓️")
sprint_review_page = st.Page("tools/2_Sprint_Review.py", title="Sprint Review", icon="📋")
release_notes_page = st.Page("tools/3_Release_Notes.py", title="Release Notes", icon="📣")
sprint_kpis_page = st.Page("tools/4_Sprint_KPIs.py", title="Sprint KPIs", icon="📊")
ai_creator_page = st.Page("tools/5_AI_Issue_Creator.py", title="Issue Creator", icon="🤖")
# Reachable by URL only: hidden from the menu
ai_agent_page = st.Page("tools/6_AI_Agent.py", title="AI Agent", icon="💬", visibility="hidden")
from utils.navigation import RELEASE_PLAN_PAGES
# Release Plan is a single menu entry (the Overview); its steps are switched with the stepper.
RELEASE_PLAN_STEPS = (0, 7, 8)
_rp_pages = {
    n: st.Page(
        path,
        title="Release Plan" if n == 0 else f"Release Plan · {title}",
        icon="🎯",
        visibility="visible" if n == 0 else "hidden",
        **({"url_path": url} if url else {}),
    )
    for n, path, title, url in RELEASE_PLAN_PAGES
    if n in RELEASE_PLAN_STEPS
}
_rp_step_labels = {n: title for n, _, title, _ in RELEASE_PLAN_PAGES}
rr_overview_page = _rp_pages[0]
release_plan_nav_pages = [_rp_pages[n] for n in RELEASE_PLAN_STEPS]


def render_release_plan_stepper(current_page):
    """Horizontal stepper linking the Release Plan steps; current step highlighted."""
    current = next(
        (i for i, n in enumerate(RELEASE_PLAN_STEPS) if _rp_pages[n].url_path == current_page.url_path),
        None,
    )
    if current is None:
        return
    inject_stepper_css("rp_stepper")
    with st.container(key="rp_stepper"):
        for i, (col, n) in enumerate(zip(st.columns(len(RELEASE_PLAN_STEPS)), RELEASE_PLAN_STEPS)):
            label = _rp_step_labels[n]
            with col:
                if i == current:
                    st.markdown(active_step_html(i + 1, label), unsafe_allow_html=True)
                else:
                    st.page_link(_rp_pages[n], label=step_label(i + 1, label, done=i < current), width="stretch")

# Shared Premium Dark Mode styles for the Home Hub and Configuration pages
def _inject_hub_styles():
    # Custom CSS for Premium Dark Mode Theme matching all tools
    st.markdown("""
        <style>
            /* General dark theme override */
            .main, .block-container, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
                background-color: #27272E !important;
                color: #F8FAFC !important;
            }
            
            /* Typography high-contrast styles */
            h1, h2, h3, h4, h5, h6 {
                color: #FFFFFF !important;
                font-weight: 700 !important;
            }
            .stMarkdown p, .stMarkdown li, .stMarkdown span {
                color: #F8FAFC !important;
            }
            
            /* Sidebar dark theme improvements */
            section[data-testid="stSidebar"] {
                background-color: #18181D !important;
                border-right: 1px solid #3E3E4A !important;
            }

            /* Sidebar Toggle Button */
            button[data-testid="collapsedControl"], button[kind="header"] {
                color: #60A5FA !important;
            }
            button[data-testid="collapsedControl"] svg, button[kind="header"] svg {
                fill: #60A5FA !important;
            }
            
            /* Premium Card Layouts applied directly to the Column container */
            div[data-testid="column"]:has(.hub-card) {
                background-color: #18181D !important;
                border: 1px solid #3E3E4A !important;
                border-radius: 12px !important;
                padding: 2rem !important;
                box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5) !important;
                margin-bottom: 1.5rem;
                transition: all 0.3s ease-in-out;
            }
            div[data-testid="column"]:has(.hub-card):hover {
                border-color: #60A5FA !important;
                transform: translateY(-2px);
            }
            .hub-card {
                background-color: transparent !important;
                border: none !important;
                border-radius: 0 !important;
                padding: 0 !important;
                box-shadow: none !important;
                margin: 0 !important;
            }
            .hub-badge {
                background-color: #60A5FA22; 
                color: #60A5FA; 
                border: 1px solid #60A5FA; 
                padding: 3px 10px; 
                border-radius: 12px; 
                font-size: 11px; 
                font-weight: 600; 
                display: inline-block;
                margin-bottom: 10px;
            }
            
            /* Style st.page_link to be a premium pill button inside the card container */
            div[data-testid="column"]:has(.hub-card) [data-testid="stPageLink"],
            div[data-testid="column"]:has(.hub-card) [data-testid="stPageLink"] a,
            div[data-testid="column"]:has(.hub-card) .stPageLink,
            div[data-testid="column"]:has(.hub-card) .stPageLink a,
            div[data-testid="column"]:has(.hub-card) a[class*="stPageLink"],
            div[data-testid="column"]:has(.hub-card) div[class*="stPageLink"] a,
            [data-testid="stPageLink"] a,
            .stPageLink a,
            a[class*="stPageLink"] {
                background: linear-gradient(135deg, #3B82F6 0%, #1D4ED8 100%) !important;
                color: #FFFFFF !important;
                padding: 0.5rem 1.5rem !important;
                border-radius: 24px !important;
                font-weight: 600 !important;
                font-size: 14px !important;
                text-decoration: none !important;
                display: inline-flex !important;
                align-items: center !important;
                justify-content: center !important;
                border: none !important;
                box-shadow: none !important;
                transition: all 0.2s ease-in-out !important;
                margin-top: 15px !important;
                width: fit-content !important;
                height: 2.25rem !important;
                box-sizing: border-box !important;
            }
            
            div[data-testid="column"]:has(.hub-card) [data-testid="stPageLink"]:hover,
            div[data-testid="column"]:has(.hub-card) [data-testid="stPageLink"] a:hover,
            div[data-testid="column"]:has(.hub-card) .stPageLink:hover,
            div[data-testid="column"]:has(.hub-card) .stPageLink a:hover,
            div[data-testid="column"]:has(.hub-card) a[class*="stPageLink"]:hover,
            div[data-testid="column"]:has(.hub-card) div[class*="stPageLink"] a:hover,
            [data-testid="stPageLink"] a:hover,
            .stPageLink a:hover,
            a[class*="stPageLink"]:hover {
                background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%) !important;
                color: #FFFFFF !important;
                border: none !important;
                transform: translateY(-1px) !important;
                box-shadow: none !important;
            }
            
            /* Force the inner page link text to be white and bold */
            div[data-testid="column"]:has(.hub-card) [data-testid="stPageLink"] p,
            div[data-testid="column"]:has(.hub-card) .stPageLink p,
            div[data-testid="column"]:has(.hub-card) a[class*="stPageLink"] p,
            div[data-testid="column"]:has(.hub-card) div[class*="stPageLink"] a p,
            [data-testid="stPageLink"] a p,
            .stPageLink a p,
            a[class*="stPageLink"] p {
                color: #FFFFFF !important;
                margin: 0 !important;
                padding: 0 !important;
                font-weight: 600 !important;
                font-size: 14px !important;
                line-height: 1 !important;
            }
            
            /* Hide page link icon completely */
            div[data-testid="column"]:has(.hub-card) [data-testid="stPageLink"] img,
            div[data-testid="column"]:has(.hub-card) [data-testid="stPageLink"] svg,
            div[data-testid="column"]:has(.hub-card) [data-testid="stPageLink"] [data-testid="stIcon"],
            div[data-testid="column"]:has(.hub-card) .stPageLink img,
            div[data-testid="column"]:has(.hub-card) .stPageLink svg,
            div[data-testid="column"]:has(.hub-card) .stPageLink [data-testid="stIcon"],
            [data-testid="stPageLink"] img,
            [data-testid="stPageLink"] svg,
            [data-testid="stPageLink"] [data-testid="stIcon"],
            .stPageLink img,
            .stPageLink svg,
            .stPageLink [data-testid="stIcon"] {
                display: none !important;
            }
            
            /* Premium button styles without box-shadow */
            .stButton>button, .stDownloadButton>button { 
                border-radius: 24px; 
                border: none; 
                background: linear-gradient(135deg, #3B82F6 0%, #1D4ED8 100%) !important; 
                color: #FFFFFF !important; 
                padding: 0.5rem 1.5rem; 
                font-weight: 600;
                box-shadow: none !important;
                transition: all 0.2s ease-in-out;
            }
            .stButton>button:hover, .stDownloadButton>button:hover { 
                background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%) !important;
                color: #FFFFFF !important;
                box-shadow: none !important;
                transform: translateY(-1px);
            }
        </style>
    """, unsafe_allow_html=True)


# 2. Define the Home Page rendering function
def _inject_home_styles():
    st.markdown("""
        <style>
            .po-hero {
                background: linear-gradient(135deg, #1E3A8A 0%, #18181D 70%);
                border: 1px solid #3E3E4A;
                border-radius: 16px;
                padding: 1.1rem 1.5rem;
                margin-bottom: 0.75rem;
            }
            .po-hero h1 { margin: 0 0 0.2rem 0 !important; padding: 0 !important; font-size: 1.7rem !important; }
            .po-hero p { margin: 0 !important; color: #CBD5E1 !important; font-size: 0.95rem; max-width: 760px; }
            .po-section {
                color: #94A3B8 !important; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em;
                text-transform: uppercase; margin: 0.4rem 0 0.3rem 0.25rem;
            }
            /* Equal-size cards: every card is a fixed-height bordered container */
            [class*="st-key-pocard_"] {
                background-color: #18181D !important;
                border: 1px solid #3E3E4A !important;
                border-radius: 14px !important;
                padding: 0.25rem 0.5rem !important;
                box-shadow: 0 6px 14px -4px rgba(0, 0, 0, 0.5) !important;
                transition: border-color 0.2s ease-in-out, transform 0.2s ease-in-out;
            }
            [class*="st-key-pocard_"]:hover { border-color: #60A5FA !important; transform: translateY(-2px); }
            .po-card-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.35rem; }
            .po-icon {
                width: 34px; height: 34px; border-radius: 10px; font-size: 18px;
                display: flex; align-items: center; justify-content: center;
                background: #60A5FA22; border: 1px solid #60A5FA55;
            }
            .po-badge {
                background-color: #60A5FA22; color: #60A5FA; border: 1px solid #60A5FA;
                padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: 600;
            }
            /* Card buttons: same size, side by side with a 10px gap, at the same height in every card */
            [class*="st-key-poLinks_"] { gap: 10px !important; flex-wrap: nowrap !important; }
            [class*="st-key-poLinks_"] > div { flex: 0 0 calc(50% - 5px) !important; width: calc(50% - 5px) !important; min-width: 0 !important; }
            [class*="st-key-poLinks_"] [data-testid="stPageLink"] a {
                width: 100% !important; height: 2.25rem !important; padding: 0 0.75rem !important; margin-top: 0 !important;
            }
            [class*="st-key-poLinks_"] [data-testid="stPageLink"] a p {
                white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important;
            }
            .po-card h3 { margin: 0 0 0.2rem 0 !important; padding: 0 !important; font-size: 1.05rem !important; }
            /* Fixed three-line description so the buttons start at the same height in every card */
            .po-card p {
                margin: 0 !important; color: #CBD5E1 !important; font-size: 0.85rem; line-height: 1.35;
                height: calc(0.85rem * 1.35 * 3); overflow: hidden; margin-bottom: 10px !important;
            }
        </style>
    """, unsafe_allow_html=True)


def _home_card(key, icon, title, desc, badge, links):
    """One home card: fixed height so every card has the same size regardless of text length.

    links is a list of (page, label, icon); several links sit side by side.
    """
    with st.container(border=True, height=215, key=f"poCard_{key}"):
        st.markdown(f"""
            <div class="po-card">
                <div class="po-card-top"><div class="po-icon">{icon}</div><span class="po-badge">{badge}</span></div>
                <h3>{title}</h3>
                <p>{desc}</p>
            </div>
        """, unsafe_allow_html=True)
        with st.container(horizontal=True, key=f"poLinks_{key}"):
            for page, label, link_icon in links:
                st.page_link(page, label=label, icon=link_icon)


def show_home():
    _inject_hub_styles()
    _inject_home_styles()

    st.markdown("""
        <div class="po-hero">
            <h1>💼 Product Tools</h1>
            <p>Product workflows, data visualization, integrations and AI-assisted capabilities in one modular platform.</p>
        </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="po-section">Planning, reviews & releases</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3, gap="medium")
    with c1:
        _home_card("quarterly", "📅", "Quarterly Review",
                   "Track committed Epics and export the progress report, or plan the backlog, Gantt and delivery roadmap.",
                   "ACTIVE 🚀", [(progress_page, "Progress", "📈"), (planner_page, "Planning", "🗓️")])
    with c2:
        _home_card("sprint", "🏃", "Sprint",
                   "Build branded Sprint Review reports from Jira, or calculate KPIs such as cycle times and committed vs achieved points.",
                   "ACTIVE 🚀", [(sprint_review_page, "Review", "📋"), (sprint_kpis_page, "KPIs", "📊")])
    with c3:
        _home_card("releases", "🚀", "Releases",
                   "Create and publish Release Notes from a Jira version, or check a release plan before go-live.",
                   "ACTIVE 🚀", [(release_notes_page, "Notes", "📣"), (rr_overview_page, "Plan", "🎯")])

    st.markdown('<div class="po-section">AI</div>', unsafe_allow_html=True)
    c4, _, _ = st.columns(3, gap="medium")
    with c4:
        _home_card("ai", "🤖", "AI Issue Creator",
                   "Draft, format and upload Jira issues effortlessly using a local Ollama AI model.",
                   "NEW ✨", [(ai_creator_page, "AI Creator", "🤖")])



# Configuration page: centralized integrations and connection checks
def show_configuration():
    _inject_hub_styles()
    st.subheader("🔌 Centralized Integrations")
    st.write("Configure connection configurations for Jira, Confluence, Ollama, SonarQube, SBOM and Vanguard below.")

    # Display current status in nice columns
    stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
    with stat_col1:
        j_status = st.session_state.get("jira_connection_status", "Not checked")
        j_msg = st.session_state.get("jira_connection_msg", "")
        if j_status == "Success":
            st.success(f"🟢 **Jira**: {j_msg}")
        elif j_status == "Failed":
            st.error(f"🔴 **Jira**: {j_msg}")
        else:
            st.warning(f"🟡 **Jira**: {j_status}")
    with stat_col2:
        c_status = st.session_state.get("conf_connection_status", "Not checked")
        c_msg = st.session_state.get("conf_connection_msg", "")
        if c_status == "Success":
            st.success(f"🟢 **Confluence**: {c_msg}")
        elif c_status == "Failed":
            st.error(f"🔴 **Confluence**: {c_msg}")
        else:
            st.warning(f"🟡 **Confluence**: {c_status}")
    with stat_col3:
        o_status = st.session_state.get("ollama_connection_status", "Not checked")
        o_msg = st.session_state.get("ollama_connection_msg", "")
        if o_status == "Success":
            st.success(f"🟢 **Ollama**: {o_msg}")
        elif o_status == "Failed":
            st.error(f"🔴 **Ollama**: {o_msg}")
        else:
            st.warning(f"🟡 **Ollama**: {o_status}")
    with stat_col4:
        a_status = st.session_state.get("api_connection_status", "Not checked")
        a_msg = st.session_state.get("api_connection_msg", "")
        if a_status == "Success":
            st.success(f"🟢 **Local API**: {a_msg}")
        elif a_status == "Failed":
            st.error(f"🔴 **Local API**: {a_msg}")
        else:
            st.warning(f"🟡 **Local API**: {a_status}")

    for col, (key, label, _) in zip(st.columns(4), QUALITY_INTEGRATIONS):
        with col:
            q_status = st.session_state.get(f"{key}_connection_status", "Not checked")
            q_msg = st.session_state.get(f"{key}_connection_msg", "")
            if q_status == "Success":
                st.success(f"🟢 **{label}**: {q_msg}")
            elif q_status == "Failed":
                st.error(f"🔴 **{label}**: {q_msg}")
            else:
                st.warning(f"🟡 **{label}**: {q_status}")

    st.markdown("---")

    if IS_REMOTE:
        st.info("🔒 Integration settings can only be viewed or changed from the host machine (http://localhost:8501).")
        return

    col_jserv, col_jtok = st.columns(2)
    with col_jserv:
        srv_in = st.text_input("Jira Server Base URL:", value=st.session_state.jira_server, key="central_jira_server")
    with col_jtok:
        tok_in = _secret_input("Jira Personal Access Token (PAT):", "jira_token", "central_jira_token")

    col_jauth, col_jmail = st.columns(2)
    with col_jauth:
        auth_options = [
            "Personal Access Token (Bearer PAT)",
            "Corporate Login (Username + Password)",
            "Jira Cloud/Server Basic (Email/User + Token)"
        ]
        auth_in = st.selectbox(
            "Jira Auth Method:",
            options=auth_options,
            index=auth_options.index(st.session_state.jira_auth_method) if st.session_state.jira_auth_method in auth_options else 0,
            key="central_jira_auth"
        )
    with col_jmail:
        mail_in = st.text_input("Jira Email/Username (Optional):", value=st.session_state.jira_email, key="central_jira_email")

    st.markdown("---")
    col_cserv, col_ctok = st.columns(2)
    with col_cserv:
        csrv_in = st.text_input("Confluence Server URL:", value=st.session_state.conf_server, key="central_conf_server")
    with col_ctok:
        ctok_in = _secret_input("Confluence Personal Access Token (PAT):", "conf_token", "central_conf_token")

    st.markdown("---")
    st.markdown("##### 🤖 Local AI (Ollama)")
    col_ourl, _ = st.columns(2)
    with col_ourl:
        ourl_in = st.text_input("Ollama API URL:", value=st.session_state.ollama_url, key="central_ollama_url")

    st.markdown("---")
    st.markdown("##### 📡 Quality & Security Integrations (KPIs)")

    st.markdown("**SonarQube**")
    sq_col1, sq_col2, sq_col3 = st.columns(3)
    with sq_col1:
        sonar_server_in = st.text_input("SonarQube Server:", value=st.session_state.sonar_server, key="central_sonar_server")
    with sq_col2:
        sonar_token_in = _secret_input("SonarQube Token:", "sonar_token", "central_sonar_token")
    with sq_col3:
        sonar_comp_in = st.text_input("SonarQube Component:", value=st.session_state.sonar_component, key="central_sonar_component")

    st.markdown("**SBOM Inventory**")
    sb_col1, sb_col2, sb_col3 = st.columns(3)
    with sb_col1:
        sbom_server_in = st.text_input("SBOM Server:", value=st.session_state.sbom_server, key="central_sbom_server")
        sbom_namespace_in = st.text_input("SBOM Namespace ID:", value=st.session_state.sbom_namespace_id, key="central_sbom_namespace")
    with sb_col2:
        sbom_api_key_in = _secret_input("SBOM API Key:", "sbom_api_key", "central_sbom_api_key")
        sbom_app_in = st.text_input("SBOM App ID:", value=st.session_state.sbom_app_id, key="central_sbom_app_id")
    with sb_col3:
        sbom_api_secret_in = _secret_input("SBOM API Secret:", "sbom_api_secret", "central_sbom_api_secret")

    st.markdown("**Vanguard**")
    vg_col1, vg_col2, vg_col3 = st.columns(3)
    with vg_col1:
        vg_project_in = st.text_input("Vanguard Project ID:", value=st.session_state.vanguard_project_id, key="central_vg_project")
    with vg_col2:
        vg_client_id_in = st.text_input("Vanguard Client ID:", value=st.session_state.vanguard_client_id, key="central_vg_client_id")
    with vg_col3:
        vg_client_secret_in = _secret_input("Vanguard Client Secret:", "vanguard_client_secret", "central_vg_secret")

    settings_changed = (
        st.session_state.jira_server != srv_in or
        st.session_state.jira_token != tok_in or
        st.session_state.jira_auth_method != auth_in or
        st.session_state.jira_email != mail_in or
        st.session_state.conf_server != csrv_in or
        st.session_state.conf_token != ctok_in or
        st.session_state.ollama_url != ourl_in or
        st.session_state.sonar_server != sonar_server_in or
        st.session_state.sonar_token != sonar_token_in or
        st.session_state.sonar_component != sonar_comp_in or
        st.session_state.sbom_server != sbom_server_in or
        st.session_state.sbom_api_key != sbom_api_key_in or
        st.session_state.sbom_api_secret != sbom_api_secret_in or
        st.session_state.sbom_namespace_id != sbom_namespace_in or
        st.session_state.sbom_app_id != sbom_app_in or
        st.session_state.vanguard_project_id != vg_project_in or
        st.session_state.vanguard_client_id != vg_client_id_in or
        st.session_state.vanguard_client_secret != vg_client_secret_in
    )

    if settings_changed:
        st.session_state.jira_server = srv_in
        st.session_state.jira_token = tok_in
        st.session_state.jira_auth_method = auth_in
        st.session_state.jira_email = mail_in
        st.session_state.conf_server = csrv_in
        st.session_state.conf_token = ctok_in
        st.session_state.ollama_url = ourl_in
        st.session_state.sonar_server = sonar_server_in
        st.session_state.sonar_token = sonar_token_in
        st.session_state.sonar_component = sonar_comp_in
        st.session_state.sbom_server = sbom_server_in
        st.session_state.sbom_api_key = sbom_api_key_in
        st.session_state.sbom_api_secret = sbom_api_secret_in
        st.session_state.sbom_namespace_id = sbom_namespace_in
        st.session_state.sbom_app_id = sbom_app_in
        st.session_state.vanguard_project_id = vg_project_in
        st.session_state.vanguard_client_id = vg_client_id_in
        st.session_state.vanguard_client_secret = vg_client_secret_in
        save_credentials_to_env()
        st.toast("Integrations updated and saved centrally! ✅")

    st.markdown("<br/>", unsafe_allow_html=True)
    if st.button("🔌 Check Integration Status", use_container_width=True):
        st.markdown("### 🔍 Connection Test Results")

        # 1. Test Jira Connection
        if srv_in and tok_in:
            with st.spinner("Testing Jira Connection..."):
                ok, msg = check_jira_connection(srv_in, tok_in, auth_in, mail_in, timeout=8)
            st.session_state.jira_connection_status = "Success" if ok else "Failed"
            st.session_state.jira_connection_msg = msg
            if ok:
                st.success(f"✅ **Jira Connection Successful!** {msg}.")
            else:
                st.error(f"❌ **Jira Connection Failed**: {msg}. Check server URL and API token.")
        else:
            st.session_state.jira_connection_status = "Failed"
            st.session_state.jira_connection_msg = "Server URL or Token empty"
            st.warning("⚠️ **Jira not tested**: Server URL or token is empty.")

        # 2. Test Confluence Connection
        if csrv_in and ctok_in:
            with st.spinner("Testing Confluence Connection..."):
                ok, msg = check_confluence_connection(csrv_in, ctok_in, auth_in, mail_in, timeout=8)
            st.session_state.conf_connection_status = "Success" if ok else "Failed"
            st.session_state.conf_connection_msg = msg
            if ok:
                st.success("✅ **Confluence Connection Successful!**")
            else:
                st.error(f"❌ **Confluence Connection Failed**: {msg}. Check URL and token.")
        else:
            st.session_state.conf_connection_status = "Failed"
            st.session_state.conf_connection_msg = "Server URL or Token empty"
            st.warning("⚠️ **Confluence not tested**: Server URL or token is empty.")

        # 3. Test Ollama Connection
        if ourl_in:
            with st.spinner("Testing Ollama Connection..."):
                models = get_ollama_models(ourl_in)
                if models:
                    st.session_state.ollama_connection_status = "Success"
                    st.session_state.ollama_connection_msg = f"{len(models)} models found"
                    st.session_state.ollama_models = models
                    st.success(f"✅ **Ollama Connection Successful!** Found {len(models)} models.")
                else:
                    st.session_state.ollama_connection_status = "Failed"
                    st.session_state.ollama_connection_msg = "No models or offline"
                    st.session_state.ollama_models = []
                    st.error(f"❌ **Ollama Connection Failed**: Could not fetch models from {ourl_in}.")
        else:
            st.session_state.ollama_connection_status = "Failed"
            st.session_state.ollama_connection_msg = "URL empty"
            st.warning("⚠️ **Ollama not tested**: URL is empty.")

        # 4. Test Local API Connection
        with st.spinner("Testing Local API Connection..."):
            try:
                api_resp = requests.get(f"{LOCAL_API_URL}/openapi.json", timeout=2)
                if api_resp.status_code == 200:
                    st.session_state.api_connection_status = "Success"
                    st.session_state.api_connection_msg = "Connected"
                    st.success("�� **Local API Connection Successful!**")
                else:
                    st.session_state.api_connection_status = "Failed"
                    st.session_state.api_connection_msg = f"HTTP {api_resp.status_code}"
                    st.error(f"❌ **Local API Connection Failed (HTTP {api_resp.status_code})**")
            except Exception:
                st.session_state.api_connection_status = "Failed"
                st.session_state.api_connection_msg = "Offline"
                st.error(f"❌ **Local API Connection Failed**: Could not connect to {LOCAL_API_URL}.")

        # 5-7. Test SonarQube, SBOM and Vanguard Connections
        with st.spinner("Testing SonarQube, SBOM and Vanguard Connections..."):
            quality_results = check_quality_integrations(quality_integration_args())
        for label, q_status, q_msg in quality_results:
            if q_status == "Success":
                st.success(f"✅ **{label} Connection Successful!** {q_msg}.")
            elif q_msg == "Configuration incomplete":
                st.warning(f"⚠️ **{label} not tested**: configuration is incomplete.")
            else:
                st.error(f"❌ **{label} Connection Failed**: {q_msg}")

# Collaboration page: Cloudflare tunnel controls (host only)
def show_collaboration():
    _inject_hub_styles()
    st.title("🤝 Live Collaboration")
    st.markdown("Share this workspace with your team in real time through a Cloudflare tunnel.")
    st.divider()

    current_url = tunnel_url
    if IS_REMOTE:
        # Remote collaborators can use the tools but never control the host tunnel.
        st.info("Connected remotely through the collaboration tunnel.")
    elif st.session_state.tunnel_enabled:
        if not current_url:
            current_url = start_tunnel(8501)

        if current_url:
            st.success("Tunnel Active 🟢")
            st.code(current_url, language="text")
            st.link_button("🌐 Open Link", current_url)
            st.caption("Share this URL with team members to collaborate in real-time.")
            if not os.getenv("REMOTE_ACCESS_PASSWORD"):
                st.warning("Set REMOTE_ACCESS_PASSWORD in .env: remote visitors are blocked until a password is configured.")
        else:
            tunnel_err = get_tunnel_error()
            if tunnel_err:
                st.error("❌ Tunnel Error")
                st.warning(tunnel_err)
                st.caption("You can still use the app locally at http://localhost:8501")
            else:
                st.info("🌀 Starting tunnel...")
                from streamlit_autorefresh import st_autorefresh
                st_autorefresh(interval=1000, limit=10, key="tunnel_startup_refresher")

        if st.button("🛑 Stop Tunnel"):
            from utils.tunnel import stop_tunnel
            stop_tunnel()
            st.session_state.tunnel_enabled = False
            st.rerun()
    else:
        if current_url:
            from utils.tunnel import stop_tunnel
            stop_tunnel()
        st.info("Cloudflare tunnel is disabled.")
        if st.button("🚀 Start Collaboration Tunnel", type="primary"):
            st.session_state.tunnel_enabled = True
            st.rerun()


# 3. Define the page listing for navigation
home_page = st.Page(show_home, title="Home", icon="🏠", default=True)
configuration_page = st.Page(show_configuration, title="Configuration", icon="⚙️", url_path="configuration")
collaboration_page = st.Page(show_collaboration, title="Collaboration", icon="🤝", url_path="collaboration")

# 4. Setup and run navigation (top menu: direct links, then one dropdown per section)
pg = st.navigation(
    {
        # Single pages are direct links; Streamlit renders them before the dropdown sections,
        # so the final order is set with CSS in the top menu styles below
        "": [home_page, ai_creator_page, ai_agent_page, configuration_page],
        "🏃 Sprint": [sprint_review_page, sprint_kpis_page],
        "🚀 Releases": [release_notes_page, *release_plan_nav_pages],
        "📅 Quarterly Review": [progress_page, planner_page],
    },
    position="top",
)
st.set_page_config(page_title="Product Owner Suite Hub", layout="wide")

# Remote access gate: tunnel/proxy visitors must provide REMOTE_ACCESS_PASSWORD.
if IS_REMOTE and not st.session_state.get("remote_authenticated", False):
    expected_remote_password = os.getenv("REMOTE_ACCESS_PASSWORD", "")
    st.title("🔒 Product Owner Suite Hub")
    if not expected_remote_password:
        st.error("Remote access is disabled. The host must set REMOTE_ACCESS_PASSWORD in its .env file to allow it.")
        st.stop()
    with st.form("remote_login"):
        provided_password = st.text_input("Access password", type="password")
        submitted = st.form_submit_button("Enter")
    if submitted:
        if check_access_password(provided_password, expected_remote_password):
            st.session_state.remote_authenticated = True
            st.rerun()
        st.error("Invalid password.")
    st.stop()

# Auto-detect tunnel URL from request headers if accessed via Cloudflare
headers = request_headers
host = headers.get("Host", "")
x_forwarded_host = headers.get("X-Forwarded-Host", "")
tunnel_host = None
if "trycloudflare.com" in host:
    tunnel_host = host
elif "trycloudflare.com" in x_forwarded_host:
    tunnel_host = x_forwarded_host

if tunnel_host:
    detected_url = f"https://{tunnel_host}"
    set_tunnel_url(detected_url)

tunnel_url = get_tunnel_url()

if tunnel_url:
    st.session_state.tunnel_enabled = True

if "tunnel_enabled" not in st.session_state:
    st.session_state.tunnel_enabled = False

# Top menu: full-width framed bar with a larger font (applies to every page)
st.markdown("""
    <style>
        nav[data-testid="stTopNav"] {
            background-color: #18181D;
            border: 1px solid #3E3E4A;
            border-radius: 12px;
            flex: 0 0 auto;
            width: fit-content;
            max-width: 100%;
            justify-content: flex-start;
            gap: 0.25rem;
            padding: 0.25rem 0.5rem;
            /* centered on the page header, independent of the Deploy button on the right */
            position: absolute;
            left: 50%;
            transform: translateX(-50%);
            margin: 0.5rem 0;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        }
        /* Menu order: Home, Sprint, Releases, Quarterly Review, Issue Creator, Configuration.
           Streamlit renders the individual pages first (Home, Issue Creator, Configuration;
           AI Agent is hidden) and then the sections in dict order (Sprint, Releases, Quarterly Review). */
        nav[data-testid="stTopNav"] > :nth-child(1) { order: 1 !important; }
        nav[data-testid="stTopNav"] > :nth-child(2) { order: 5 !important; }
        nav[data-testid="stTopNav"] > :nth-child(3) { order: 6 !important; }
        nav[data-testid="stTopNav"] > :nth-child(4) { order: 2 !important; }
        nav[data-testid="stTopNav"] > :nth-child(5) { order: 3 !important; }
        nav[data-testid="stTopNav"] > :nth-child(6) { order: 4 !important; }
        nav[data-testid="stTopNav"] > :nth-child(n+7) { order: 7 !important; }
        nav[data-testid="stTopNav"] [data-testid="stTopNavLinkContainer"],
        nav[data-testid="stTopNav"] [data-testid="stTopNavSection"] {
            margin: 0;
        }
        nav[data-testid="stTopNav"] [data-testid="stTopNavLink"],
        nav[data-testid="stTopNav"] [data-testid="stTopNavSection"],
        nav[data-testid="stTopNav"] [data-testid="stTopNavLink"] p,
        nav[data-testid="stTopNav"] [data-testid="stTopNavSection"] p,
        nav[data-testid="stTopNav"] span {
            font-size: 1rem !important;
            font-weight: 600;
        }
        nav[data-testid="stTopNav"] [data-testid="stTopNavLink"],
        nav[data-testid="stTopNav"] [data-testid="stTopNavSection"] {
            padding: 0.3rem 0.7rem !important;
            border-radius: 8px;
        }
    </style>
""", unsafe_allow_html=True)
# Connections each tool needs: (label, session-state prefix of its check, is it configured?, (target name, value))
def _ss(key):
    return str(st.session_state.get(key) or "")


def _quality_configured(key):
    return lambda: all(a and str(a).strip() for a in quality_integration_args()[key])


_JIRA = ("Jira", "jira", lambda: bool(_ss("jira_server")), lambda: ("Server", _ss("jira_server")))
_CONFLUENCE = ("Confluence", "conf", lambda: bool(_ss("conf_server")), lambda: ("Server", _ss("conf_server")))
_OLLAMA = ("Ollama", "ollama", lambda: bool(_ss("ollama_url")), lambda: ("Server", _ss("ollama_url")))
_SONAR = ("SonarQube", "sonar", _quality_configured("sonar"),
          lambda: ("Project", f"{_ss('sonar_component')} on {_ss('sonar_server')}"))
_SBOM = ("SBOM", "sbom", _quality_configured("sbom"),
         lambda: ("Application", f"{_ss('sbom_app_id')} on {_ss('sbom_server')}"))
_VANGUARD = ("Vanguard", "vanguard", _quality_configured("vanguard"), lambda: ("Project", _ss("vanguard_project_id")))
PAGE_CONNECTIONS = {
    progress_page.url_path: [_JIRA],
    planner_page.url_path: [_JIRA],
    sprint_review_page.url_path: [_JIRA, _CONFLUENCE],
    sprint_kpis_page.url_path: [_JIRA, _CONFLUENCE, _SONAR, _SBOM, _VANGUARD],
    release_notes_page.url_path: [_JIRA, _CONFLUENCE],
    ai_creator_page.url_path: [_JIRA, _OLLAMA],
    ai_agent_page.url_path: [_OLLAMA],
    **{page.url_path: [_JIRA, _CONFLUENCE] for page in release_plan_nav_pages},
}


def _connection_state(prefix, configured):
    """(dot, status title, explanation) for one connection, from the checks stored in session state."""
    status = st.session_state.get(f"{prefix}_connection_status", "Not checked")
    msg = str(st.session_state.get(f"{prefix}_connection_msg", "") or "").replace("`", "")
    if not configured:
        return "⚪", "Not configured", "Its settings are missing. Add them on the Configuration page."
    if status == "Success":
        return "🟢", "Connected", msg or "The last connection check succeeded."
    if status == "Failed":
        return "🔴", "Connection failed", (f"{msg}. " if msg else "") + \
            "Check the settings on the Configuration page and run 'Check Integration Status' again."
    return "🟡", "Not checked yet", \
        "Configured but not tested yet. Run 'Check Integration Status' on the Configuration page."


def render_connection_status(current_page):
    """Small list of the connections the current tool needs, top right under the menu; hover for details."""
    connections = PAGE_CONNECTIONS.get(current_page.url_path)
    if not connections:
        return
    items = []
    for label, prefix, is_configured, target in connections:
        configured = is_configured()
        dot, title, detail = _connection_state(prefix, configured)
        target_name, target_value = target()
        items.append(
            f'<span class="po-conn" tabindex="0">{dot} {html.escape(label)}'
            f'<span class="po-conn-tip" role="tooltip">'
            f'<b>{dot} {html.escape(label)}: {html.escape(title)}</b>'
            f'<span>{html.escape(detail)}</span>'
            f'<span class="po-conn-server">{html.escape(target_name)}: '
            f'{html.escape(target_value if configured else "not set")}</span>'
            f'</span></span>'
        )
    st.markdown(f"""
        <style>
            .po-conn-bar {{ display: flex; justify-content: flex-end; gap: 0.9rem; margin: -5rem 0 3.5rem 0;
                            font-size: 0.78rem; color: #94A3B8; position: relative; z-index: 1000; }}
            .po-conn {{ position: relative; cursor: help; white-space: nowrap; outline: none; }}
            .po-conn-tip {{
                display: none; position: absolute; top: calc(100% + 6px); right: 0; width: 280px;
                padding: 0.6rem 0.75rem; border-radius: 8px; border: 1px solid #60A5FA;
                background: #18181D; color: #E2E8F0; box-shadow: 0 8px 20px rgba(0, 0, 0, 0.45);
                white-space: normal; font-size: 0.8rem; line-height: 1.35; text-align: left;
            }}
            .po-conn-tip b {{ display: block; margin-bottom: 0.25rem; color: #FFFFFF; }}
            .po-conn-tip span {{ display: block; }}
            .po-conn-tip .po-conn-server {{ margin-top: 0.35rem; color: #94A3B8; word-break: break-all; }}
            .po-conn:hover .po-conn-tip, .po-conn:focus .po-conn-tip {{ display: block; }}
        </style>
        <div class="po-conn-bar">{"".join(items)}</div>
    """, unsafe_allow_html=True)


render_connection_status(pg)
render_release_plan_stepper(pg)
pg.run()
