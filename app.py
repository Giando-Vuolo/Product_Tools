import streamlit as st
import os

st.set_page_config(page_title="Product Owner Suite Hub", layout="wide")

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
        .hub-badge-soon {
            background-color: #94A3B822; 
            color: #94A3B8; 
            border: 1px solid #94A3B8; 
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

# Active and Upcoming Tools Grid
st.subheader("🛠️ Active Tools & Workspace")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("""
        <div class="hub-card">
            <span class="hub-badge">ACTIVE 🚀</span>
            <h3>🎯 Quarterly Planner</h3>
            <p>Visualize backlogs, track team velocity, and build interactive hierarchical roadmap Gantt charts from Jira exports.</p>
            <p style="font-size: 12px; color: #94A3B8;">👈 Select this tool from the sidebar to launch.</p>
        </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
        <div class="hub-card">
            <span class="hub-badge-soon">UNDER DEVELOPMENT ⚙️</span>
            <h3>📊 Jira Metrics & KPIs</h3>
            <p>Analyze cycle times, work-in-progress (WIP) limits, cumulative flow diagrams, and overall backlog health analysis.</p>
            <p style="font-size: 12px; color: #94A3B8;">Release planned for next sprint.</p>
        </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown("""
        <div class="hub-card">
            <span class="hub-badge-soon">PLANNING PHASE 📅</span>
            <h3>📈 Velocity Forecasting</h3>
            <p>Predict team milestone completion rates using historical sprint velocities and Monte Carlo planning simulations.</p>
            <p style="font-size: 12px; color: #94A3B8;">Feasibility assessment underway.</p>
        </div>
    """, unsafe_allow_html=True)

st.divider()

# Setup / Quick Testing Section
st.subheader("📋 Getting Started & Testing")

col_left, col_right = st.columns([2, 1])

with col_left:
    st.markdown("""
    To get started with the active tools:
    1. **Prepare your Data**: Export your backlog from Jira or any project board into a standard CSV format.
    2. **Launch the Tool**: Select **`1 🎯 Quarterly Planner`** from the left navigation sidebar.
    3. **Upload & Analyze**: Drag and drop your file into the uploader dropzone inside the tool to instantly render the backlog tables, sprint editors, and Gantt charts.
    """)

with col_right:
    st.markdown("### ⬇️ Download Template")
    st.markdown("Don't have a Jira CSV export on hand? Download a realistic template dataset to test the workspace:")
    
    try:
        mock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jira_mock.csv")
        with open(mock_path, "r") as f:
            mock_csv = f.read()
        st.download_button(
            label="⬇️ Download jira_mock.csv", 
            data=mock_csv.encode('utf-8'), 
            file_name="jira_mock.csv", 
            mime="text/csv"
        )
    except Exception:
        st.error("Template file could not be loaded locally.")
