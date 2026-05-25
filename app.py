import streamlit as st
import os

# 1. Define the page objects first so they are globally accessible
planner_page = st.Page("tools/1_Quarterly_Planner.py", title="Quarterly Planner", icon="🎯")

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
            
            /* Premium Card Layouts */
            .hub-card {
                background-color: #18181D !important;
                border: 1px solid #3E3E4A !important;
                border-radius: 12px !important;
                padding: 2rem !important;
                box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5) !important;
                margin-bottom: 1.5rem;
                transition: all 0.3s ease-in-out;
            }
            .hub-card:hover {
                border-color: #60A5FA !important;
                transform: translateY(-2px);
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

    col_card, _ = st.columns([2, 1])

    with col_card:
        st.markdown("""
            <div class="hub-card">
                <span class="hub-badge">ACTIVE 🚀</span>
                <h3>🎯 Quarterly Planner</h3>
                <p>Create and customize high-level, interactive Gantt charts from your backlog data or Jira CSV exports.</p>
            </div>
        """, unsafe_allow_html=True)
        
        # Clickable Native Page Link using the actual st.Page object (completely bug-free!)
        st.page_link(planner_page, label="Launch Quarterly Planner", icon="🎯")

# 3. Define the page listing for navigation
home_page = st.Page(show_home, title="Home Hub", icon="🏠", default=True)

# 4. Setup and run navigation
pg = st.navigation([home_page, planner_page])
st.set_page_config(page_title="Product Owner Suite Hub", layout="wide")
pg.run()
