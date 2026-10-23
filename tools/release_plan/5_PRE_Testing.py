from utils import release_checks as rc
from utils import release_readiness_page as rr

P = "rr5"
rr.page_header("Release Plan · 5 PRE testing",
               "Lists issues with 'Tested in PRE = No' and whether it is explained. Runs only on Refresh.")
ctx = rr.load_context(P)
rr.refresh(ctx)
data = rr.get_data(ctx)
if data:
    rr.render_findings(rc.check_pre_testing(data["issues"]), data["checked_at"],
                       "No issue lacks PRE testing.")
