from utils import release_readiness_page as rr

P = "rr0"
rr.page_header("🔎 Overview",
               "Runs all release readiness rules. Fetches only when you click Refresh (read-only).")
ctx = rr.load_context(P)
rr.refresh_all(ctx)
data = rr.get_data(ctx)
if data:
    freeze = rr.freeze_date_input(P, data)
    rr.render_overview(data, freeze)
    from datetime import date

    from utils import release_checks as rc
    from utils import release_publish as rpub
    summ = rc.summarize(rc.run_all(data["issues"], freeze, date.today()))
    rr.render_publish_panel(ctx, "readiness", rpub.render_readiness_line(summ, data["checked_at"]),
                            "Publish readiness line")
