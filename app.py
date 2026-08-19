import streamlit as st
import os
import requests
from dotenv import load_dotenv
from utils.tunnel import start_tunnel, get_tunnel_url, get_tunnel_error

# Load environment variables
load_dotenv(override=True)
default_primary_color = os.getenv("PRIMARY_COLOR", "#3B82F6")
if 'primary_color' not in st.session_state or st.session_state.get('prev_env_color') != default_primary_color:
    st.session_state.primary_color = default_primary_color
    st.session_state.prev_env_color = default_primary_color

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



# 1. Define the page objects first so they are globally accessible
planner_page = st.Page("tools/1_Quarterly_Planner.py", title="Quarterly Planner", icon="🎯")
sprint_review_page = st.Page("tools/2_Sprint_Review.py", title="Sprint Review", icon="📋")
release_notes_page = st.Page("tools/3_Release_Notes.py", title="Release Notes", icon="📣")

# 2. Define the Home Page rendering function
def show_home():

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
            section[data-testid="stSidebar"] h1,
            section[data-testid="stSidebar"] h2,
            section[data-testid="stSidebar"] h3,
            section[data-testid="stSidebar"] h4,
            section[data-testid="stSidebar"] label,
            section[data-testid="stSidebar"] .stMarkdown {
                color: #FFFFFF !important;
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
                height: 2.25rem !important; /* Force standard height matching other buttons */
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
            
            /* Hide page link icon completely to match clean text style of other buttons */
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

    # Main Title and Welcome
    st.title("💼 Product Owner Suite Hub")
    st.markdown("Welcome to the **Product Owner & Project Management Tools Suite**. Use the sidebar to seamlessly navigate between the different tools available in this workspace.")

    st.divider()

    tab_tools, tab_integrations = st.tabs(["🛠️ Available Tools", "🔌 Centralized Integrations"])

    with tab_tools:
        st.subheader("Available Tools")
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("""
                <div class="hub-card">
                    <span class="hub-badge">ACTIVE 🚀</span>
                    <h3>🎯 Quarterly Planner</h3>
                    <p>Create and customize high-level, interactive Gantt charts from your backlog data or Jira CSV exports.</p>
                </div>
            """, unsafe_allow_html=True)
            st.page_link(planner_page, label="Open Planner", icon="🎯")

        with col2:
            st.markdown("""
                <div class="hub-card">
                    <span class="hub-badge">ACTIVE 🚀</span>
                    <h3>📋 Sprint Review</h3>
                    <p>Extract Jira sprint data, edit items in a workbook, apply custom branding, and export PDF Sprint Review reports.</p>
                </div>
            """, unsafe_allow_html=True)
            st.page_link(sprint_review_page, label="Open Sprint Review", icon="📋")

        with col3:
            st.markdown("""
                <div class="hub-card">
                    <span class="hub-badge">ACTIVE 🚀</span>
                    <h3>📣 Release Notes</h3>
                    <p>Compile completed features, write release highlight intro text, and export PDF Release Notes for customers and stakeholders.</p>
                </div>
            """, unsafe_allow_html=True)
            st.page_link(release_notes_page, label="Open Release Notes", icon="📣")

    with tab_integrations:
        st.subheader("🔌 Connection & Integrations Settings")
        st.write("Configure your Jira and Confluence server details here. These settings are shared globally across all tools in the suite.")

        col_jserv, col_jtok = st.columns(2)
        with col_jserv:
            srv_in = st.text_input("Jira Server URL:", value=st.session_state.jira_server, key="central_jira_server")
        with col_jtok:
            tok_in = st.text_input("Jira API Token:", value=st.session_state.jira_token, type="password", key="central_jira_token")

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
            ctok_in = st.text_input("Confluence Personal Access Token (PAT):", value=st.session_state.conf_token, type="password", key="central_conf_token")

        # Save updates to session state
        st.session_state.jira_server = srv_in
        st.session_state.jira_token = tok_in
        st.session_state.jira_auth_method = auth_in
        st.session_state.jira_email = mail_in
        st.session_state.conf_server = csrv_in
        st.session_state.conf_token = ctok_in

        st.success("Integrations updated and saved in active session! ✅")

        st.markdown("<br/>", unsafe_allow_html=True)
        if st.button("🔌 Check Integration Status", use_container_width=True):
            st.markdown("### 🔍 Connection Test Results")
            
            # 1. Test Jira Connection
            if srv_in and tok_in:
                with st.spinner("Testing Jira Connection..."):
                    try:
                        headers = {"Accept": "application/json"}
                        auth = None
                        token_clean = tok_in.strip().removeprefix("Bearer ").strip()
                        if auth_in in ["Corporate Login (Username + Password)", "Jira Cloud/Server Basic (Email/User + Token)"]:
                            auth = (mail_in.strip(), token_clean)
                        else:
                            headers["Authorization"] = f"Bearer {token_clean}"
                        
                        resp = requests.get(f"{srv_in.rstrip('/')}/rest/api/2/myself", headers=headers, auth=auth, timeout=8)
                        if resp.status_code == 200:
                            user_name = resp.json().get("displayName", "User")
                            st.session_state.jira_connection_status = "Success"
                            st.session_state.jira_connection_msg = f"Connected as `{user_name}`"
                            st.success(f"✅ **Jira Connection Successful!** Connected as `{user_name}`.")
                        else:
                            st.session_state.jira_connection_status = "Failed"
                            st.session_state.jira_connection_msg = f"Auth Failed (HTTP {resp.status_code})"
                            st.error(f"❌ **Jira Authentication Failed (HTTP {resp.status_code})**. Check server URL and API token.")
                    except Exception as e:
                        st.session_state.jira_connection_status = "Failed"
                        st.session_state.jira_connection_msg = f"Connection Failed ({e})"
                        st.error(f"❌ **Jira Connection Failed**: Could not connect to server. ({e})")
            else:
                st.session_state.jira_connection_status = "Failed"
                st.session_state.jira_connection_msg = "Server URL or Token empty"
                st.warning("⚠️ **Jira not tested**: Server URL or token is empty.")

            # 2. Test Confluence Connection
            if csrv_in and ctok_in:
                with st.spinner("Testing Confluence Connection..."):
                    try:
                        headers = {"Accept": "application/json"}
                        auth = None
                        token_clean = ctok_in.strip().removeprefix("Bearer ").strip()
                        if auth_in in ["Corporate Login (Username + Password)", "Jira Cloud/Server Basic (Email/User + Token)"]:
                            auth = (mail_in.strip(), token_clean)
                        else:
                            headers["Authorization"] = f"Bearer {token_clean}"
                            
                        base_url = csrv_in.rstrip("/")
                        if "atlassian.net" in base_url and not base_url.endswith("/wiki"):
                            base_url = base_url + "/wiki"
                            
                        resp = requests.get(f"{base_url}/rest/api/content?limit=1", headers=headers, auth=auth, timeout=8)
                        if resp.status_code == 200:
                            st.session_state.conf_connection_status = "Success"
                            st.session_state.conf_connection_msg = "Connected successfully"
                            st.success(f"✅ **Confluence Connection Successful!**")
                        else:
                            st.session_state.conf_connection_status = "Failed"
                            st.session_state.conf_connection_msg = f"Auth Failed (HTTP {resp.status_code})"
                            st.error(f"❌ **Confluence Authentication Failed (HTTP {resp.status_code})**. Check URL and token.")
                    except Exception as e:
                        st.session_state.conf_connection_status = "Failed"
                        st.session_state.conf_connection_msg = f"Connection Failed ({e})"
                        st.error(f"❌ **Confluence Connection Failed**: Could not connect to server. ({e})")
            else:
                st.session_state.conf_connection_status = "Failed"
                st.session_state.conf_connection_msg = "Server URL or Token empty"
                st.warning("⚠️ **Confluence not tested**: Server URL or token is empty.")




# 3. Define the page listing for navigation
home_page = st.Page(show_home, title="Home Hub", icon="🏠", default=True)

# 4. Setup and run navigation
pg = st.navigation([home_page, planner_page, sprint_review_page, release_notes_page])
st.set_page_config(page_title="Product Owner Suite Hub", layout="wide")

# Display live collaboration tunnel link in the sidebar
st.sidebar.markdown("### 🤝 Live Collaboration")

if "tunnel_enabled" not in st.session_state:
    st.session_state.tunnel_enabled = False

tunnel_url = get_tunnel_url()

if st.session_state.tunnel_enabled:
    if not tunnel_url:
        from utils.tunnel import start_tunnel
        tunnel_url = start_tunnel(8501)
        
    if tunnel_url:
        st.sidebar.success("Tunnel Active ✅")
        st.sidebar.code(tunnel_url, language="text")
        st.sidebar.link_button("🌐 Open Link", tunnel_url, use_container_width=True)
        st.sidebar.caption("Share this URL with team members to collaborate in real-time.")
    else:
        tunnel_err = get_tunnel_error()
        if tunnel_err:
            st.sidebar.error("❌ Tunnel Error")
            st.sidebar.warning(tunnel_err)
            st.sidebar.caption("You can still use the app locally at http://localhost:8501")
        else:
            st.sidebar.info("🌀 Starting tunnel...")
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=1000, limit=10, key="tunnel_startup_refresher")
            
    if st.sidebar.button("🛑 Stop Tunnel", use_container_width=True):
        from utils.tunnel import stop_tunnel
        stop_tunnel()
        st.session_state.tunnel_enabled = False
        st.rerun()
else:
    if tunnel_url:
        from utils.tunnel import stop_tunnel
        stop_tunnel()
        
    st.sidebar.info("Cloudflare tunnel is disabled.")
    if st.sidebar.button("🚀 Start Collaboration Tunnel", use_container_width=True):
        st.session_state.tunnel_enabled = True
        st.rerun()

pg.run()


