"""Releases → Release Calendar: read-only view of the Confluence Team Calendar (ICS subscription)."""
import os
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from utils import release_calendar as rc

load_dotenv(override=True)

ICS_URL = os.getenv(rc.ENV_ICS_URL, "")
CONF_TOKEN = os.getenv("CONFLUENCE_API_TOKEN", "")
AUTH_METHOD = os.getenv("JIRA_AUTH_METHOD", "Jira Server Token (Bearer)")
EMAIL = os.getenv("JIRA_EMAIL", "")
STATE_KEY = "release_calendar_data"

st.title("🗓️ Release Calendar")
st.caption("Read-only view of the Confluence release calendar (ICS subscription). "
           "Data is downloaded only when you click Load calendar.")

if not ICS_URL:
    st.error(f"Missing configuration (set in .env): {rc.ENV_ICS_URL}. "
             "In Confluence open the calendar → ⋯ → Subscribe → copy the link.")
    st.stop()


@st.cache_data(ttl=600, show_spinner=False)
def _download(url, token, auth, email):
    return rc.fetch_ics(url, token, auth, email)


col_btn, col_info = st.columns([1, 4])
with col_btn:
    load = st.button("Load calendar", type="primary", key="rc_load")
    refresh = st.button("Force refresh", key="rc_refresh", help="Ignore the 10-minute cache.")
if load or refresh:
    if refresh:
        _download.clear()
    try:
        with st.spinner("Downloading calendar..."):
            text = _download(ICS_URL, CONF_TOKEN, AUTH_METHOD, EMAIL)
            calendar = rc.parse_ics(text)
        st.session_state[STATE_KEY] = {"calendar": calendar, "loaded_at": datetime.now()}
    except rc.CalendarError as exc:
        st.error(str(exc))

data = st.session_state.get(STATE_KEY)
if not data:
    st.info("Click Load calendar to read the release calendar.")
    st.stop()

calendar = data["calendar"]
with col_info:
    st.write(f"**{calendar.name or 'Calendar'}** · {len(calendar.events)} events · "
             f"loaded {data['loaded_at']:%d %b %Y %H:%M}" + (f" · {calendar.timezone}" if calendar.timezone else ""))

today = date.today()
events = rc.events_dataframe(calendar)
releases = rc.releases_dataframe(events, today)
kpis = rc.calendar_kpis(events, releases, today)

# ----------------------------------------------------------------- KPIs
k1, k2, k3, k4 = st.columns(4)
k1.metric("Next Prod release", kpis["next_version"] or "—")
k2.metric("Days to next release", kpis["days_to_next"] if kpis["days_to_next"] is not None else "—")
if kpis["next_date"] is not None:
    k1.caption(f"Prod Deploy on {kpis['next_date']:%a %d %b %Y}")
k3.metric(f"Prod deploys {kpis['quarter_label']}", kpis["prod_in_quarter"])
k4.metric("Constraints next 30 days", len(kpis["constraints_30d"]))
for w in kpis["warnings"]:
    st.warning(w)

# ----------------------------------------------------------------- Filters
all_types = sorted(events["Type"].unique())
with st.container(border=True):
    f1, f2, f3 = st.columns([2, 3, 2])
    with f1:
        span = st.date_input("Date range", value=(today - timedelta(days=30), today + timedelta(days=180)),
                             key="rc_range", format="DD/MM/YYYY")
    with f2:
        types = st.multiselect("Event types", all_types, default=all_types, key="rc_types")
    with f3:
        text = st.text_input("Search", key="rc_text", placeholder="e.g. 36.0.0, BAT, holiday")
start, end = (span if isinstance(span, (tuple, list)) and len(span) == 2 else (span[0] if span else None, None))
filtered = rc.filter_events(events, start, end, types, text)

DATE_FMT = "DD MMM YYYY"

_EVENTS_CSS = """
<style>
.rc-events { max-height: 640px; overflow-y: auto; border: 1px solid rgba(148,163,184,.25); border-radius: 8px; }
.rc-events table { width: 100%; border-collapse: collapse; font-size: .85rem; table-layout: fixed; }
.rc-events th { position: sticky; top: 0; background: #1E1E24; color: #94A3B8; text-align: left;
                font-weight: 600; padding: 8px 10px; border-bottom: 1px solid rgba(148,163,184,.25); }
.rc-events td { padding: 8px 10px; vertical-align: top; border-bottom: 1px solid rgba(148,163,184,.12);
                color: #E2E8F0; overflow-wrap: anywhere; }
.rc-events td.rc-desc { white-space: pre-wrap; color: #CBD5E1; }
.rc-events td.rc-date { white-space: nowrap; }
.rc-events tr:hover td { background: rgba(59,130,246,.08); }
</style>
"""


def _events_html(df):
    """Events as an HTML table whose Description wraps inside the cell (st.dataframe rows have a fixed height)."""
    from html import escape

    def date_cell(v):
        return f'<td class="rc-date">{v:%d %b %Y}</td>'

    rows = "".join(
        "<tr>" + date_cell(r.Start) + date_cell(r.End)
        + f"<td>{escape(r.Type)}</td><td>{escape(r.Summary)}</td><td>{escape(r.Version)}</td>"
        + f'<td class="rc-desc">{escape(r.Description)}</td></tr>'
        for r in df.itertuples(index=False)
    )
    cols = '<colgroup><col style="width:9%"><col style="width:9%"><col style="width:12%">' \
           '<col style="width:22%"><col style="width:7%"><col style="width:41%"></colgroup>'
    head = "<tr><th>Start</th><th>End</th><th>Type</th><th>Summary</th><th>Version</th><th>Description</th></tr>"
    return f'{_EVENTS_CSS}<div class="rc-events"><table>{cols}<thead>{head}</thead><tbody>{rows}</tbody></table></div>'
tab_rel, tab_events, tab_timeline = st.tabs(["Releases", "Events", "Timeline"])

# ----------------------------------------------------------------- Releases (one row per version)
with tab_rel:
    rel = releases
    if start is not None or end is not None:
        lo = pd.Timestamp(start) if start else pd.Timestamp.min
        hi = pd.Timestamp(end) if end else pd.Timestamp.max
        step_cols = [c for c, _, _ in rc.RELEASE_STEPS]
        in_range = rel[step_cols].apply(lambda col: col.between(lo, hi)).any(axis=1)
        rel = rel[in_range]
    if text.strip():
        rel = rel[rel["Version"].str.contains(text.strip(), regex=False)]
    if rel.empty:
        st.info("No releases with calendar steps in the selected range.")
    else:
        st.caption("One row per version: QS Freeze as a start → end range, earliest date for the other steps. "
                   "Status is based on the Prod Deploy date.")
        st.dataframe(rc.releases_display(rel), hide_index=True, width="stretch",
                     column_config={"Days to Prod": st.column_config.NumberColumn("Days to Prod", format="%d")})

# ----------------------------------------------------------------- Events
with tab_events:
    cap_col, toggle_col = st.columns([3, 1])
    cap_col.caption(f"{len(filtered)} events")
    wrap = toggle_col.toggle("Full descriptions", value=True, key="rc_wrap",
                             help="On: descriptions wrap inside the cell. Off: interactive table (sort, resize).")
    if filtered.empty:
        st.info("No events in the selected range.")
    elif wrap:
        st.markdown(_events_html(filtered), unsafe_allow_html=True)
    else:
        st.dataframe(
            filtered.drop(columns=["UID"]), hide_index=True, width="stretch",
            column_config={
                "Start": st.column_config.DateColumn("Start", format=DATE_FMT),
                "End": st.column_config.DateColumn("End", format=DATE_FMT),
                "Description": st.column_config.TextColumn("Description", width="large"),
            },
        )

# ----------------------------------------------------------------- Timeline
with tab_timeline:
    if filtered.empty:
        st.info("No events in the selected range.")
    else:
        show_titles = st.toggle("Show titles", value=True, key="rc_titles",
                                help="Event title above each bar (below it when two titles would overlap).")
        plot = filtered.copy()
        plot["Finish"] = plot["End"] + pd.Timedelta(days=1)  # bars cover the whole last day
        plot["Label"] = plot["Summary"].str.strip().str.slice(0, 40)
        n_rows = plot["Type"].nunique()
        levels = rc.timeline_label_levels(plot, plot["Label"]) if show_titles else []
        bar_px, line_px = 18, 14  # bar thickness and height of one title line
        tiers = (max(levels) // 2 + 1) if levels else 0  # title lines needed on each side of a bar
        row_px = bar_px + 2 * tiers * line_px + 14 if show_titles else 45
        fig = px.timeline(plot, x_start="Start", x_end="Finish", y="Type", color="Type",
                          hover_name="Summary", hover_data={"Version": True, "Start": "|%d %b %Y",
                                                            "End": "|%d %b %Y", "Finish": False, "Type": False,
                                                            "Label": False})
        fig.update_yaxes(autorange="reversed", title=None)
        fig.add_vline(x=pd.Timestamp(today).to_pydatetime(), line_dash="dash", line_color="#EF4444")
        if show_titles:
            for (_, r), level in zip(plot.iterrows(), levels):
                above, tier = level % 2 == 0, level // 2  # 0 above, 1 below, 2 above that, 3 below that...
                shift = bar_px / 2 + 1 + tier * line_px
                fig.add_annotation(
                    x=r["Start"].to_pydatetime(), y=r["Type"], text=r["Label"], showarrow=False,
                    xanchor="left", yanchor="bottom" if above else "top", yshift=shift if above else -shift,
                    font=dict(size=11, color="#E2E8F0"), hovertext=r["Summary"],
                )
            fig.update_layout(bargap=1 - bar_px / row_px)
        fig.update_layout(height=90 + row_px * n_rows, showlegend=False,
                          margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
