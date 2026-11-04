import streamlit as st

from utils import release_readiness_page as rr

P = "rr9"
rr.page_header("Release Plan · 9 By owner",
               "Issues to review grouped by owner, with a copy-ready message each. Nothing is posted from here. "
               "Runs only on Refresh.")
ctx = rr.load_context(P)
rr.refresh_all(ctx)
data = rr.get_data(ctx)
if data:
    freeze = rr.freeze_date_input(P, data)
    st.caption(f"Messages name release {ctx.source_version} (the version whose Jira issues are read).")
    rr.render_by_owner(data, freeze, ctx.source_version)
