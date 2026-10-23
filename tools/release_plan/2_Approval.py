from datetime import date

from utils import release_checks as rc
from utils import release_readiness_page as rr

P = "rr2"
rr.page_header("Release Plan · 2 Approval",
               "Checks the 'Ready to release' approval of every in-scope issue. Runs only on Refresh.")
ctx = rr.load_context(P)
rr.refresh(ctx, with_freeze=True)
data = rr.get_data(ctx)
if data:
    freeze = rr.freeze_date_input(P, data)
    rr.render_findings(rc.check_approval(data["issues"], freeze, date.today()),
                       data["checked_at"], "All in-scope issues are approved.")
