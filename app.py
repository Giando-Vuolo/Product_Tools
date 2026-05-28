import streamlit as st
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)
default_primary_color = os.getenv("PRIMARY_COLOR", "#3B82F6")
if 'primary_color' not in st.session_state or st.session_state.get('prev_env_color') != default_primary_color:
    st.session_state.primary_color = default_primary_color
    st.session_state.prev_env_color = default_primary_color

# 1. Define the page objects first so they are globally accessible
planner_page = st.Page("tools/1_Quarterly_Planner.py", title="Quarterly Planner", icon="🎯")
review_page = st.Page("tools/2_Sprint_Review_Release_Notes.py", title="Sprint & Release Reports", icon="📋")

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

    # Active Tools Section
    st.subheader("🛠️ Available Tools")

    col1, col2 = st.columns(2)

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
                <h3>📋 Sprint & Release Reports</h3>
                <p>Extract Jira sprint data, edit items in a worktable, apply custom branding, and export PDF Sprint Reviews & Release Notes.</p>
            </div>
        """, unsafe_allow_html=True)
        st.page_link(review_page, label="Open Reports", icon="📋")


# 3. Define the page listing for navigation
home_page = st.Page(show_home, title="Home Hub", icon="🏠", default=True)

# 4. Setup and run navigation
pg = st.navigation([home_page, planner_page, review_page])
st.set_page_config(page_title="Product Owner Suite Hub", layout="wide")
pg.run()
