from utils import release_checks as rc
from utils import release_readiness_page as rr

P = "rr6"
rr.page_header("Release Plan · 6 Unassigned",
               "Lists in-scope issues without assignee. Runs only on Refresh.")
ctx = rr.load_context(P)
rr.refresh(ctx)
data = rr.get_data(ctx)
if data:
    rr.render_findings(rc.check_unassigned(data["issues"]), data["checked_at"],
                       "All issues are assigned.")
