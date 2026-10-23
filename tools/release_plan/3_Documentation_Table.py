from utils import release_checks as rc
from utils import release_readiness_page as rr

P = "rr3"
rr.page_header("Release Plan · 3 Documentation table",
               "Checks the Approval Documentation table of every in-scope issue. Runs only on Refresh.")
ctx = rr.load_context(P)
rr.refresh(ctx)
data = rr.get_data(ctx)
if data:
    rr.render_findings(rc.check_doc_table(data["issues"]), data["checked_at"],
                       "Documentation tables look complete.")
