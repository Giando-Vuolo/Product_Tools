import pandas as pd
import streamlit as st

from utils import release_checks as rc
from utils import release_readiness_page as rr

P = "rr1"
rr.page_header("Release Plan · 1 Scope",
               "In-scope issues, exclusions and possibly misclassified issues. Runs only on Refresh.")
ctx = rr.load_context(P)
rr.refresh_all(ctx)
data = rr.get_data(ctx)
if data:
    scope = data["scope_issues"]
    in_scope = rc.select_in_scope(scope)
    in_keys = {i.key for i in in_scope}
    subtasks = [i for i in scope if i.issuetype not in rc.CHECKED_ISSUE_TYPES and i.issuetype.lower() in ("sub-task", "subtask")]
    out_scope = [i for i in scope if i.key not in in_keys and i not in subtasks]
    st.caption(f"Checked at {data['checked_at']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("In scope", len(in_scope))
    c2.metric("Excluded: Sub-tasks", len(subtasks))
    c3.metric("Excluded: out of scope", len(out_scope))
    if subtasks or out_scope:
        with st.expander("Excluded issues", expanded=False):
            st.dataframe(pd.DataFrame([
                {"Issue": i.key, "Summary": i.summary, "Type": i.issuetype,
                 "Fix versions": ", ".join(i.fix_versions)} for i in subtasks + out_scope
            ]), hide_index=True, width='stretch')
    st.markdown("#### Possibly misclassified")
    rr.render_findings(rc.check_scope(data["issues"]), "", "No misclassified issues found.")
