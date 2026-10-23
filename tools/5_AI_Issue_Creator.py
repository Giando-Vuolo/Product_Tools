import streamlit as st
from utils.ai_helpers import get_ollama_models, generate_issue_with_ollama, extract_text_from_pdf, load_issue_structures
from utils.jira_helpers import fetch_jira_projects, fetch_jira_issue_types, create_jira_issue, attach_files_to_jira_issue
import os
import json

st.set_page_config(page_title="AI Issue Creator", page_icon="🤖", layout="wide")

st.title("🤖 AI Issue Creator (Ollama)")
st.markdown("Use local AI models to automatically format and create structured Jira issues from informal ideas.")

# Ensure session state variables
if "ollama_url" not in st.session_state:
    st.session_state.ollama_url = "http://localhost:11434"
if "ollama_models" not in st.session_state:
    st.session_state.ollama_models = []
if "generated_description" not in st.session_state:
    st.session_state.generated_description = ""
if "jira_projects" not in st.session_state:
    st.session_state.jira_projects = []

# Auto-fetch models on load if empty
if not st.session_state.get("ollama_models"):
    st.session_state.ollama_models = get_ollama_models(st.session_state.get("ollama_url", "http://localhost:11434"))

st.divider()

# ==========================================
# 0. JIRA INTEGRATION (SETTINGS)
# ==========================================
st.subheader("⚙️ Jira Settings & Target")
st.markdown("Configure where this issue will be created in Jira.")

jira_connected = st.session_state.get("jira_connection_status") == "Success"

if not jira_connected:
    st.warning("Jira is not connected. Go to the Home Hub to configure your connection.")
    selected_proj_key = ""
    jira_issue_type = ""
    jira_parent = ""
    jira_linked = ""
    jira_sp = ""
    jira_fv = ""
    jira_sprint = ""
    jira_assignee = ""
    jira_labels = ""
else:
    col_btn, col_proj = st.columns([1, 2])
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Fetch Jira Projects", use_container_width=True):
            with st.spinner("Fetching..."):
                projs = fetch_jira_projects(
                    st.session_state.get("jira_server"),
                    st.session_state.get("jira_token"),
                    st.session_state.get("jira_auth_method"),
                    st.session_state.get("jira_email")
                )
                if projs:
                    st.session_state.jira_projects = projs
                    st.success("Projects fetched!")
                else:
                    st.error("Failed to fetch projects.")
    
    with col_proj:
        if st.session_state.get("jira_projects"):
            proj_dict = {f"{k} - {n}": k for k, n in st.session_state.jira_projects}
            proj_keys = list(proj_dict.keys())
            
            # Try to pre-select default project
            default_proj = os.getenv("AI_ISSUE_PROJECT_KEY", "")
            default_index = 0
            if default_proj:
                for i, key_label in enumerate(proj_keys):
                    if proj_dict[key_label].upper() == default_proj.upper():
                        default_index = i
                        break
                        
            selected_proj_label = st.selectbox("Select Jira Project *", proj_keys, index=default_index)
            selected_proj_key = proj_dict[selected_proj_label]
        else:
            selected_proj_key = st.text_input("Jira Project Key *", value=os.getenv("AI_ISSUE_PROJECT_KEY", ""), placeholder="e.g. REC", help="Type manually or fetch projects using the button.")
            
    jira_issue_type = st.text_input("Jira Issue Type *", value=os.getenv("AI_ISSUE_TARGET_TYPE", "Story"), help="The exact Issue Type name as it appears in Jira (e.g., Story, Task, Bug, Epic).")

    st.markdown("##### Optional Fields")
    
    col_parent, col_linked = st.columns(2)
    with col_parent:
        jira_parent = st.text_input("Parent Issue (Epic / Story)", placeholder="e.g. REC-123", help="Link to an Epic or a Parent Story.")
    with col_linked:
        jira_linked = st.text_input("Related Issue (Relates to)", placeholder="e.g. REC-124", help="Link to a related task/bug.")
        
    col_sp, col_fv, col_sprint = st.columns(3)
    with col_sp:
        jira_sp = st.text_input("Story Points", value=os.getenv("AI_ISSUE_STORY_POINTS", ""), placeholder="e.g. 5", help="Numeric value for estimation.")
    with col_fv:
        jira_fv = st.text_input("Fix Version", value=os.getenv("AI_ISSUE_FIX_VERSION", ""), placeholder="e.g. DIGITAL:HUB 35.0.0", help="Exact release version name.")
    with col_sprint:
        jira_sprint = st.text_input("Sprint Number / Name:", value=os.getenv("AI_ISSUE_SPRINT", ""), placeholder="e.g. 142 or Next Sprint Overview", help="Numeric ID or exact Sprint name.")
        
    col_assignee, col_labels = st.columns(2)
    with col_assignee:
        jira_assignee = st.text_input("Assignee (ID/Email)", value=os.getenv("AI_ISSUE_ASSIGNEE", ""), placeholder="e.g. jsmith", help="Leave blank to leave unassigned.")
    with col_labels:
        jira_labels = st.text_input("Labels", value=os.getenv("AI_ISSUE_LABELS", ""), placeholder="e.g. frontend, backend", help="Comma-separated list of labels.")
        
    st.caption("Make sure the issue type exists in your Jira project (e.g., Story, Task, Bug, Epic).")

st.divider()

# ==========================================
# 1. DEFINE YOUR ISSUE
# ==========================================
st.subheader("📝 1. Define your Issue")

# Show status indicator and select box
if st.session_state.get("ollama_models"):
    st.success(f"🟢 Ollama Running ({len(st.session_state.ollama_models)} models found)")
    
    # Try to pre-select default model from .env
    default_model = os.getenv("AI_ISSUE_MODEL", "")
    default_model_index = 0
    if default_model and default_model in st.session_state.ollama_models:
        default_model_index = st.session_state.ollama_models.index(default_model)
        
    selected_model = st.selectbox("Select AI Model", st.session_state.ollama_models, index=default_model_index)
else:
    st.error("🔴 Ollama Not Running or no models available. Please configure it in the Home Hub -> Integrations tab.")
    selected_model = None

# Load structures from ai_issue_structures.json with fallback
issue_structures = load_issue_structures()
structures_warning = getattr(issue_structures, "warning", None)
if structures_warning:
    st.warning(structures_warning)

default_preset_by_type = issue_structures.get("default_preset_by_type", {})
presets = issue_structures.get("presets", {})
extra_sections = issue_structures.get("extra_sections", [])

# Build ALL_SECTIONS as a deduplicated list combining all sections across presets (preserving order) + extra_sections
all_sections = []
seen_sections = set()
for p_sections in presets.values():
    for s in p_sections:
        if s not in seen_sections:
            seen_sections.add(s)
            all_sections.append(s)
for s in extra_sections:
    if s not in seen_sections:
        seen_sections.add(s)
        all_sections.append(s)

issue_types = ["User Story", "Task", "Bug", "Epic", "Improvement", "Risk", "Technical Task"]

col_fmt, col_preset = st.columns(2)
with col_fmt:
    selected_type = st.selectbox("Desired Format (AI Generation)", issue_types)

with col_preset:
    preset_names = list(presets.keys())
    preset_options = preset_names + ["Custom (Freeform Instructions)"]
    rec_preset = default_preset_by_type.get(selected_type, preset_names[0] if preset_names else "Custom (Freeform Instructions)")
    rec_index = preset_options.index(rec_preset) if rec_preset in preset_options else 0
    selected_preset = st.selectbox(
        "Issue Structure Template",
        preset_options,
        index=rec_index,
        key=f"preset_select_{selected_type}"
    )

if selected_preset != "Custom (Freeform Instructions)":
    default_preset_sections = [s for s in presets.get(selected_preset, []) if s in all_sections]
    selected_sections = st.multiselect(
        "Included Sections (Add, remove, or reorder headings for the AI)",
        options=all_sections,
        default=default_preset_sections,
        key=f"sections_multiselect_{selected_preset}"
    )
    custom_structure_notes = st.text_input(
        "Additional Formatting Notes (Optional)",
        placeholder="e.g. Write in Spanish, or include a Markdown table for API endpoints"
    )
else:
    selected_sections = []
    custom_structure_notes = st.text_area(
        "Custom Structure Instructions *",
        placeholder="Describe the exact sections, tables, or format you want the AI to follow..."
    )

st.markdown("<br>", unsafe_allow_html=True)

issue_summary = st.text_input("Issue Summary (Title) *", placeholder="e.g. Add Google Login to the portal")
issue_idea = st.text_area("Informal Idea or Requirements *", height=150, placeholder="Type your informal idea, bullet points, or notes here. The AI will format it professionally.")

st.markdown("##### Optional: Extract Requirements from PDF")
pdf_req_file = st.file_uploader("Upload a PDF to append its text to the requirements", type=["pdf"], key="pdf_req")
if pdf_req_file:
    with st.spinner("Extracting text from PDF..."):
        pdf_text = extract_text_from_pdf(pdf_req_file.getvalue())
        if pdf_text.startswith("[Error") or pdf_text.startswith("[PDF"):
            st.error(pdf_text)
        else:
            issue_idea += f"\n\n--- Extracted from {pdf_req_file.name} ---\n{pdf_text}"
            st.success("PDF text successfully added to the requirements in memory!")

if st.button("✨ Generate Description with AI", use_container_width=True):
    if not selected_model:
        st.error("Please ensure Ollama is running and select a model first.")
    elif not issue_idea or not issue_summary:
        st.warning("Please provide both a Summary and an Idea (or upload a PDF).")
    elif selected_preset == "Custom (Freeform Instructions)" and not custom_structure_notes.strip():
        st.warning("Please provide custom structure instructions.")
    elif selected_preset != "Custom (Freeform Instructions)" and not selected_sections:
        st.warning("Please select at least one section for the issue structure.")
    else:
        with st.spinner("Generating issue description..."):
            combined_input = f"Title: {issue_summary}\nDetails: {issue_idea}"
            result = generate_issue_with_ollama(
                model=selected_model,
                issue_type=selected_type,
                prompt_input=combined_input,
                ollama_url=st.session_state.ollama_url,
                sections=selected_sections,
                custom_instructions=custom_structure_notes,
                preset_name=selected_preset
            )
            if result.startswith("Error") or result.startswith("Exception"):
                st.error(result)
            else:
                st.session_state.generated_description = result
                st.success("Description generated!")

st.divider()

# ==========================================
# 2. REVIEW AND UPLOAD
# ==========================================
st.subheader("🔍 2. Review and Upload")

final_description = st.text_area("Generated Description (Editable)", value=st.session_state.generated_description, height=500)

st.markdown("##### Attachments")
uploaded_files = st.file_uploader("Upload files to attach to the new issue", accept_multiple_files=True)

if st.button("🚀 Create Issue in Jira", type="primary", use_container_width=True):
    if not issue_summary or not final_description:
        st.error("Summary and Description are required.")
    elif not selected_proj_key:
        st.error("Jira Project Key is required.")
    else:
        with st.spinner("Creating issue..."):
            res = create_jira_issue(
                st.session_state.get("jira_server"),
                st.session_state.get("jira_token"),
                st.session_state.get("jira_auth_method"),
                st.session_state.get("jira_email"),
                selected_proj_key,
                jira_issue_type.strip(),
                issue_summary,
                final_description,
                jira_assignee.strip(),
                jira_labels.strip(),
                jira_parent.strip(),
                jira_sp.strip() if jira_sp.strip() else None,
                jira_fv.strip(),
                jira_linked.strip(),
                jira_sprint.strip()
            )
            
            if res.startswith("Error"):
                # Try to parse the JSON error for better formatting
                error_text = res
                if " - {" in res:
                    try:
                        status_part, json_part = res.split(" - ", 1)
                        err_data = json.loads(json_part)
                        err_msgs = err_data.get("errorMessages", [])
                        errors_dict = err_data.get("errors", {})
                        
                        formatted_errors = ""
                        if err_msgs:
                            for msg in err_msgs:
                                formatted_errors += f"- {msg}\n"
                        if errors_dict:
                            for field, msg in errors_dict.items():
                                formatted_errors += f"- **{field}**: {msg}\n"
                                
                        if formatted_errors:
                            error_text = f"**Jira rejected the request ({status_part.strip()}):**\n\n{formatted_errors}"
                    except Exception:
                        pass
                st.error(error_text)
            elif res.startswith("Exception"):
                st.error(res)
            else:
                jira_server = st.session_state.get("jira_server", "").rstrip("/")
                issue_link = f"{jira_server}/browse/{res}"
                
                st.success(f"Issue successfully created! [**{res}**]({issue_link})")
                
                if uploaded_files:
                    with st.spinner(f"Attaching {len(uploaded_files)} files to {res}..."):
                        attach_results = attach_files_to_jira_issue(
                            st.session_state.get("jira_server"),
                            st.session_state.get("jira_token"),
                            st.session_state.get("jira_auth_method"),
                            st.session_state.get("jira_email"),
                            res,
                            uploaded_files
                        )
                        for file_name, success, msg in attach_results:
                            if success:
                                st.success(f"Attached: {file_name}")
                            else:
                                st.error(f"Failed to attach {file_name}: {msg}")
                
                st.balloons()
