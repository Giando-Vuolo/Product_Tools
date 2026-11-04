from utils import release_checks as rc
from utils import release_readiness_page as rr

P = "rr4"
rr.page_header("Release Plan · 4 Critical changes",
               "Lists in-scope issues flagged as critical changes by their Documentation table. Runs only on Load Information.")
ctx = rr.load_context(P)
rr.refresh(ctx)
data = rr.get_data(ctx)
if data:
    critical = rc.find_critical_changes(data["issues"])
    critical_keys = {r.issue_key for r in critical}
    others = [i for i in rc.select_in_scope(data["issues"]) if i.key not in critical_keys]
    rr.render_critical(critical, data["checked_at"], others)
    from utils import release_publish as rpub
    rr.render_publish_panel(ctx, "critical", rpub.render_critical_table(critical, ctx.server),
                            "Publish to Confluence")
