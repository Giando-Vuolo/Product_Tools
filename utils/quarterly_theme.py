"""Shared page setup for the Quarterly Planning pages (Progress and Planning)."""
import os

import streamlit as st
from dotenv import load_dotenv


def apply_quarterly_page_setup():
    """Load .env, set the primary color and inject the shared dark theme CSS."""
    load_dotenv(override=True)
    default_primary_color = os.getenv("PRIMARY_COLOR", "#3B82F6")
    if 'primary_color' not in st.session_state or st.session_state.get('prev_env_color') != default_primary_color:
        st.session_state.primary_color = default_primary_color
        st.session_state.prev_env_color = default_primary_color

    # Custom CSS for Premium Dark Mode Theme
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
        
            /* Gantt chart container box specifically targeted with key or contents */
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.stPlotlyChart),
            div[data-testid="stVerticalBlockBorderWrapper"]:has([data-testid="stPlotlyChart"]),
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.js-plotly-plot),
            div[data-testid="stVerticalBlockBorderWrapper"]:has(iframe),
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-gantt_container),
            div[data-testid="stVerticalBlockBorderWrapper"]:has([key="gantt_container"]),
            div[data-testid="stVerticalBlockBorderWrapper"]:has([data-testid="st-key-gantt_container"]),
            div[data-testid="stVerticalBlockBorderWrapper"]:has([class*="gantt_container"]),
            div.stVerticalBlockBorder:has(.stPlotlyChart),
            div.stVerticalBlockBorder:has([data-testid="stPlotlyChart"]),
            .st-key-gantt_container {
                background-color: #18181D !important; /* Cohesive Charcoal background */
                border: 2px solid #3E3E4A !important; /* High contrast clean border */
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6) !important;
                border-radius: 12px !important;
                padding: 1.5rem !important;
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
        
            /* Quality validation alert card with clean high contrast text */
            .validation-card {
                background-color: #1E1B4B;
                border-left: 4px solid #F59E0B;
                padding: 1rem;
                border-radius: 8px;
                margin-bottom: 1rem;
                color: #F8FAFC;
            }
        </style>
    """, unsafe_allow_html=True)
