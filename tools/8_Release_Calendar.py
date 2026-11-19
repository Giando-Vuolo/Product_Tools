"""Releases → Release Calendar: read-only view of the Confluence Team Calendar (ICS subscription)."""
import os
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from utils import release_calendar as rc
from utils import release_calendar_api as rca
from utils import release_calendar_edit as rce
from utils import release_calendar_jira as rcj

load_dotenv(override=True)

ICS_URL = os.getenv(rc.ENV_ICS_URL, "")
CONF_TOKEN = os.getenv("CONFLUENCE_API_TOKEN", "")
AUTH_METHOD = os.getenv("JIRA_AUTH_METHOD", "Jira Server Token (Bearer)")
EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_SERVER = os.getenv("JIRA_SERVER", "")
JIRA_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_PROJECT = os.getenv("RELEASE_PLAN_JIRA_PROJECT", "RECALLTWO").strip() or "RECALLTWO"
NAME_TEMPLATE = os.getenv(rcj.ENV_NAME_TEMPLATE, "").strip() or rcj.DEFAULT_NAME_TEMPLATE
VERSION_LINK_BASE = os.getenv("JIRA_VERSION_LINK_BASE", "")
STATE_KEY = "release_calendar_data"
JIRA_STATE_KEY = "release_calendar_jira_versions"
CONF_SERVER = os.getenv("CONFLUENCE_SERVER", "")
CALENDAR_ID = rca.parse_calendar_id(os.getenv(rca.ENV_CALENDAR_ID, ""))
EVENT_TITLE_TEMPLATE = os.getenv(rce.ENV_TITLE_TEMPLATE, "").strip() or rce.DEFAULT_TITLE_TEMPLATE
EDIT_STATE_KEY = "release_calendar_edit"

st.title("🗓️ Release Calendar")
st.caption("Read-only view of the Confluence release calendar (ICS subscription). "
           "Data is downloaded only when you click Load calendar.")

if not ICS_URL:
    st.error("Release Calendar not configured. Add the Confluence calendar's .ics link in "
             "Configuration → Release Calendar ICS URL (or set RELEASE_CALENDAR_ICS_URL in .env). "
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
tab_rel, tab_jira, tab_edit, tab_events, tab_timeline = st.tabs(["Releases", "Jira", "Edit", "Events", "Timeline"])

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

# ----------------------------------------------------------------- Jira (link calendar releases to fixVersions)
def _jira_request(path):
    from utils.release_helpers import jira_request
    return jira_request(JIRA_SERVER, JIRA_TOKEN, path, auth_type=AUTH_METHOD, email=EMAIL)


def _who():
    if EMAIL:
        return EMAIL
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return ""


with tab_jira:
    try:
        template_error = ""
        example = rcj.release_name(NAME_TEMPLATE, "37.0.0")
    except ValueError as exc:
        template_error, example = str(exc), ""
    st.caption(f"Links each calendar release to its Jira fixVersion in project {JIRA_PROJECT}. A release is "
               f"linked automatically to the Jira version named with the release name template "
               f"`{NAME_TEMPLATE}`" + (f" (e.g. {example})" if example else "") + ". Change the template in "
               "Configuration → Release name template. A manual link always wins and is saved locally in "
               "PO Tools. The Confluence calendar is not changed.")
    if template_error:
        st.error(f"{template_error} Fix it in Configuration → Release name template.")
    elif not (JIRA_SERVER and JIRA_TOKEN):
        st.info("Set JIRA_SERVER and JIRA_API_TOKEN in Configuration to link releases to Jira.")
    elif st.button("Load Jira versions", key="rc_jira_load"):
        try:
            with st.spinner("Reading Jira versions..."):
                versions = rcj.fetch_jira_versions(_jira_request, JIRA_PROJECT)
            st.session_state[JIRA_STATE_KEY] = rcj.jira_versions_dataframe(versions)
        except rcj.JiraVersionsError as exc:
            st.error(str(exc))

    jira_df = st.session_state.get(JIRA_STATE_KEY) if not template_error else None
    try:
        links = rcj.load_links()
    except rcj.JiraVersionsError as exc:
        st.error(str(exc))
        links = {}
    if template_error:
        pass
    elif jira_df is None:
        st.info("Click Load Jira versions to match the calendar releases with Jira.")
    elif releases.empty:
        st.info("The calendar has no releases to link.")
    else:
        linked = rcj.link_releases(releases, jira_df, links, NAME_TEMPLATE)
        for w in rcj.link_warnings(linked, today):
            st.warning(w)
        view = linked[["Version", "Prod Deploy", "Expected name", "Jira version", "Jira release date", "Date check", "Link",
                       "Released", "Jira id"]].copy()
        view["Open"] = [rcj.version_url(j, VERSION_LINK_BASE, JIRA_SERVER, JIRA_PROJECT) or None
                        for j in view.pop("Jira id")]
        for col in ("Prod Deploy", "Jira release date"):
            view[col] = [rc._iso(v) for v in view[col]]
        st.dataframe(view, hide_index=True, width="stretch", column_config={
            "Open": st.column_config.LinkColumn("Jira", display_text="Open"),
            "Released": st.column_config.CheckboxColumn("Released in Jira"),
        })

        with st.container(border=True):
            st.markdown("**Link to Jira**")
            needs = linked[linked["Link"].isin([rcj.UNLINKED, rcj.NAME_DIFFERS])]["Version"].tolist()
            ordered = needs + [v for v in linked["Version"] if v not in needs]
            c1, c2 = st.columns([1, 3])
            version = c1.selectbox("Calendar release", ordered, key="rc_link_version",
                                   format_func=lambda v: f"{v} ⚠️" if v in needs else v)
            current = linked.set_index("Version").loc[version]
            opts = rcj.link_options(jira_df, linked, version, NAME_TEMPLATE)
            not_in_jira = "— Not in Jira —"
            labels = [not_in_jira] + [
                f"{r['Jira version']}" + (f" · {rc._iso(r['Jira release date'])}" if rc._iso(r["Jira release date"]) else "")
                + (" · released" if r["Released"] else "") for _, r in opts.iterrows()]
            ids = [""] + opts["Jira id"].tolist()
            if current["Link"] == rcj.NOT_IN_JIRA:
                default = 0
            elif current["Jira id"] and current["Jira id"] in ids:
                default = ids.index(current["Jira id"])
            else:  # not linked yet: preselect the best candidate (same X.Y.Z, unreleased first)
                default = 1 if len(ids) > 1 else 0
            choice = c2.selectbox("Jira version", range(len(ids)), index=default, key=f"rc_link_jira_{version}",
                                  format_func=lambda i: labels[i])
            c2.caption(f"Now: {current['Link']}" + (f" → {current['Jira version']}" if current["Jira version"] else ""))
            b1, b2, _ = st.columns([1, 1, 3])
            if b1.button("Save link", type="primary", key="rc_link_save"):
                name = "" if choice == 0 else opts.iloc[choice - 1]["Jira version"]
                try:
                    rcj.save_links(rcj.set_link(links, version, ids[choice], name, linked_by=_who()))
                    st.toast(f"Release {version} linked to {name or 'nothing (not in Jira)'}.")
                    st.rerun()
                except OSError as exc:
                    st.error(f"Could not save the link: {exc}")
            if b2.button("Use automatic match", key="rc_link_clear", disabled=version not in links,
                         help="Remove the manual link of this release and match it by X.Y.Z again."):
                try:
                    rcj.save_links(rcj.clear_link(links, version))
                    st.rerun()
                except OSError as exc:
                    st.error(f"Could not save the link: {exc}")

# ----------------------------------------------------------------- Edit (Epic 2: write to the Team Calendar)
def _sender():
    return rca.make_sender(CONF_SERVER, CONF_TOKEN, AUTH_METHOD, EMAIL)


def _load_for_editing():
    send = _sender()
    cal = rca.get_calendar(send, CALENDAR_ID)
    window = (today - timedelta(days=180), today + timedelta(days=730))
    events = rca.list_events(send, cal, *window)
    st.session_state[EDIT_STATE_KEY] = {
        "cal": cal, "events": events, "window": window, "loaded_at": datetime.now(),
        "table": rce.editable_table(events), "extra": rce.proposal_rows(pd.DataFrame(columns=["Version", "Prod Deploy"])),
        "gen": st.session_state.get(EDIT_STATE_KEY, {}).get("gen", 0) + 1,
    }


with tab_edit:
    st.caption("Add releases or change their dates in the Confluence Team Calendar. Only the events behind "
               "the cells you change are written; nothing is deleted. Before publishing you see every change, "
               "and the calendar is re-read: if someone changed those events meanwhile, publishing is blocked.")
    try:
        write_mode, sandbox_versions = rce.load_write_config(os.environ)
    except ValueError as exc:
        write_mode, sandbox_versions = None, None
        st.error(str(exc))
    if write_mode == "sandbox":
        st.warning(f"🧪 Sandbox mode: only {', '.join(sandbox_versions)} can be published. "
                   f"Set {rce.ENV_WRITE_MODE}=live in .env to edit real releases.")
    if not (CONF_SERVER and CONF_TOKEN and CALENDAR_ID):
        st.info("To edit, set the Confluence server and token and the Release Calendar link "
                "(Configuration → Release Calendar link).")
    else:
        if st.button("Load for editing", key="rc_edit_load",
                     help="Reads the calendar events through the Confluence API (needed to write)."):
            try:
                with st.spinner("Reading the calendar events..."):
                    _load_for_editing()
            except rca.CalendarApiError as exc:
                st.error(str(exc))
        state = st.session_state.get(EDIT_STATE_KEY)
        if not state:
            st.info("Click Load for editing to edit the release calendar.")
        else:
            cal = state["cal"]
            st.caption(f"**{cal.name}** · {len(state['events'])} events between {state['window'][0]:%d %b %Y} and "
                       f"{state['window'][1]:%d %b %Y} · loaded {state['loaded_at']:%H:%M} · new events are "
                       f"titled `{EVENT_TITLE_TEMPLATE}`")
            if not cal.events_editable:
                st.error("Your user cannot edit events in this calendar.")

            # ---- add from Jira
            jira_df = st.session_state.get(JIRA_STATE_KEY)
            with st.expander("Add releases from Jira", expanded=False):
                if jira_df is None:
                    st.caption("Load Jira versions in the Jira tab to get proposals.")
                else:
                    try:
                        prop_links = rcj.load_links()
                    except rcj.JiraVersionsError:
                        prop_links = {}
                    in_table = set(state["table"]["Version"]) | set(state["extra"]["Version"])
                    props = rce.jira_proposals(jira_df, in_table, prop_links, NAME_TEMPLATE)
                    if props.empty:
                        st.caption("Every unreleased Jira version is already in the calendar.")
                    else:
                        labels = {r["Jira id"]: f"{r['Jira version']}" + (f" · {r['Prod Deploy']:%d %b %Y}"
                                  if r["Prod Deploy"] else " · no release date") for _, r in props.iterrows()}
                        chosen = st.multiselect("Jira versions not in the calendar", list(labels),
                                                format_func=labels.get, key="rc_edit_props")
                        if st.button("Add to the table", key="rc_edit_add", disabled=not chosen):
                            state["extra"] = pd.concat([state["extra"], rce.proposal_rows(
                                props[props["Jira id"].isin(chosen)])], ignore_index=True)
                            state["gen"] += 1
                            st.rerun()

            # ---- editor
            base = pd.concat([state["table"], state["extra"]], ignore_index=True)
            shown = base.copy()
            for col in rce.DATE_COLUMNS:
                shown[col] = pd.to_datetime(shown[col])
            edited = st.data_editor(
                shown, key=f"rc_editor_{state['gen']}", num_rows="dynamic", hide_index=True, width="stretch",
                column_order=["Version", *rce.DATE_COLUMNS, rce.NOTES, rce.LOCKED],
                column_config={
                    "Version": st.column_config.TextColumn("Version", help="X.Y.Z", required=False),
                    **{c: st.column_config.DateColumn(c, format=DATE_FMT) for c in rce.DATE_COLUMNS},
                    rce.NOTES: st.column_config.TextColumn("Notes", help="Saved as the Prod Deploy description.",
                                                           width="large"),
                    rce.LOCKED: st.column_config.TextColumn("Locked steps", disabled=True,
                                                            help="Steps with several, recurring or timed events: "
                                                                 "edit them in Confluence."),
                },
            )
            plan = rce.plan_changes(state["table"], edited, state["events"], cal, EVENT_TITLE_TEMPLATE,
                                    sandbox_versions)

            # ---- preview
            for err in plan.errors:
                st.error(err)
            counts = plan.rows["Status"].value_counts() if not plan.rows.empty else pd.Series(dtype=int)
            st.markdown(f"**Preview** · {counts.get('New', 0)} new · {counts.get('Changed', 0)} changed · "
                        f"{counts.get('Unchanged', 0)} unchanged · {len(plan.changes)} event writes")
            if plan.changes:
                st.dataframe(pd.DataFrame([{
                    "Release": c.version, "Step": c.type_title, "Action": c.action.capitalize(),
                    "Before": (f"{c.before['start']} → {c.before['end']}" if c.before else "—"),
                    "After": f"{c.after['start']} → {c.after['end']}",
                    "Title": c.after["title"],
                    "Description": ("changed" if c.before and c.before["description"] != c.after["description"]
                                    else ("set" if not c.before and c.after["description"] else "")),
                } for c in plan.changes]), hide_index=True, width="stretch")
                changed_rows = plan.rows[plan.rows["Status"] != "Unchanged"]
                if not changed_rows.empty:
                    st.dataframe(changed_rows, hide_index=True, width="stretch")

            can_publish = bool(plan.changes) and not plan.errors and write_mode is not None and cal.events_editable
            if st.button(f"Publish {len(plan.changes)} change(s)" if plan.changes else "Publish", type="primary",
                         key="rc_edit_publish", disabled=not can_publish):
                with st.spinner("Publishing to the calendar..."):
                    res = rce.publish(_sender(), cal, plan.changes, state["events"], state["window"],
                                      allowed_id=CALENDAR_ID, sandbox_versions=sandbox_versions, user=_who())
                if res["ok"]:
                    st.success(f"Published {len(res['applied'])} change(s) and verified them in Confluence. "
                               f"Backup: {res['backup']}")
                    _download.clear()  # the other tabs read the ICS: refresh it on the next load
                    try:
                        _load_for_editing()
                    except rca.CalendarApiError as exc:
                        st.warning(f"Published, but reloading failed: {exc}")
                else:
                    st.error(res["error"] or "Publishing failed.")
                    if res.get("backup"):
                        st.caption(f"Backup of the events before writing: {res['backup']}")

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
