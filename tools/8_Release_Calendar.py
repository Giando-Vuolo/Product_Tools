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
from utils import release_overview as ro
from utils.slide_templates import render_slide_template_selector

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
tab_rel, tab_jira, tab_edit, tab_events, tab_timeline, tab_overview = st.tabs(
    ["Releases", "Jira", "Edit", "Events", "Timeline", "Overview"])

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
        linked_all = rcj.link_releases(releases, jira_df, links, NAME_TEMPLATE)
        jf1, jf2 = st.columns([2, 3])
        with jf1:
            prod_span = st.date_input("Prod Deploy between", key="rc_jira_range", format="DD/MM/YYYY",
                                      value=(today - timedelta(days=90), today + timedelta(days=365)),
                                      help="Shows the releases whose Prod Deploy date is in this range.")
        with jf2:
            st.write("")
            include_missing = st.checkbox("Include releases without a Prod Deploy date", value=True,
                                          key="rc_jira_no_prod")
        if isinstance(prod_span, (tuple, list)):
            p_start = prod_span[0] if len(prod_span) > 0 else None
            p_end = prod_span[1] if len(prod_span) > 1 else None
        else:
            p_start, p_end = prod_span, None
        linked = rcj.filter_by_prod_date(linked_all, p_start, p_end, include_missing)
        st.caption(f"{len(linked)} of {len(linked_all)} releases")
        for w in rcj.link_warnings(linked, today):
            st.warning(w)
        view = linked[["Version", "Prod Deploy", "Jira version", "Jira release date", "Date check", "Link",
                       "Released", "Jira id"]].copy()
        view["Open"] = [rcj.version_url(j, VERSION_LINK_BASE, JIRA_SERVER, JIRA_PROJECT) or None
                        for j in view.pop("Jira id")]
        for col in ("Prod Deploy", "Jira release date"):
            view[col] = [rc._iso(v) for v in view[col]]
        if linked.empty:
            st.info("No releases with a Prod Deploy date in the selected range.")
        else:
            st.dataframe(view, hide_index=True, width="stretch", column_config={
                "Open": st.column_config.LinkColumn("Jira", display_text="Open"),
                "Released": st.column_config.CheckboxColumn("Released in Jira"),
            })

        # ---- release date and description in Jira vs the calendar's Prod Deploy event
        sync = rcj.jira_sync_status(linked, jira_df, events)
        todo = sync[sync["Date status"].isin([rcj.MISSING, rcj.DIFFERS]) | sync["Description status"].isin([rcj.MISSING, rcj.DIFFERS])]
        if not sync.empty:
            with st.container(border=True):
                n_date = int(sync["Date status"].isin([rcj.MISSING, rcj.DIFFERS]).sum())
                n_desc = int(sync["Description status"].isin([rcj.MISSING, rcj.DIFFERS]).sum())
                st.markdown(f"**Release date & description in Jira** · {len(sync)} linked versions · "
                            f"{n_date} release date(s) and {n_desc} description(s) to fill or fix")
                if todo.empty:
                    st.caption("✅ Every linked Jira version has the calendar's Prod Deploy date and description.")
                else:
                    st.caption("Compared with the release's Prod Deploy event in Confluence (date and description). "
                               "Missing values are ticked to be filled; tick the ones that differ to overwrite them.")
                    try:
                        sync_mode, _ = rce.load_write_config(os.environ)
                    except ValueError:
                        sync_mode = None
                    grid = pd.DataFrame({
                        "Version": todo["Version"],
                        "Jira version": todo["Jira version"],
                        "Prod Deploy": [rc._iso(v) if v is not None else "" for v in todo["Prod Deploy"]],
                        "Jira release date": [rc._iso(v) for v in todo["Jira release date"]],
                        "Date": todo["Date status"],
                        "Fill date": todo["Date status"].eq(rcj.MISSING),
                        "Calendar description": todo["Calendar description"],
                        "Jira description": todo["Jira description"],
                        "Description": todo["Description status"],
                        "Fill description": todo["Description status"].eq(rcj.MISSING),
                    }).reset_index(drop=True)
                    picked = st.data_editor(
                        grid, hide_index=True, width="stretch", key="rc_jira_sync_grid",
                        disabled=[c for c in grid.columns if c not in ("Fill date", "Fill description")],
                        column_config={
                            "Fill date": st.column_config.CheckboxColumn("Fill date", help="Set the Jira release date "
                                                                         "to the Prod Deploy date."),
                            "Fill description": st.column_config.CheckboxColumn("Fill description", help="Set the Jira description "
                                                                                "to the Prod Deploy event's description."),
                            "Calendar description": st.column_config.TextColumn("Calendar description", width="medium"),
                            "Jira description": st.column_config.TextColumn("Jira description", width="medium"),
                        })
                    updates = []
                    for i, row in todo.reset_index(drop=True).iterrows():
                        do_date = bool(picked.loc[i, "Fill date"]) and row["Date status"] in (rcj.MISSING, rcj.DIFFERS)
                        do_desc = bool(picked.loc[i, "Fill description"]) and row["Description status"] in (rcj.MISSING, rcj.DIFFERS)
                        payload = rcj.sync_payload(row, do_date, do_desc)
                        if payload:
                            updates.append((row, payload))
                    if sync_mode == "sandbox":
                        st.caption(f"🧪 Sandbox mode: updating Jira versions is blocked. Set {rce.ENV_WRITE_MODE}=live "
                                   "in .env to update them.")
                    if st.button(f"Update {len(updates)} Jira version(s)" if updates else "Update Jira versions",
                                 key="rc_jira_sync", disabled=not updates or sync_mode != "live"):
                        put = rcj.make_jira_poster(JIRA_SERVER, JIRA_TOKEN, AUTH_METHOD, EMAIL, method="PUT")
                        new_df, done, failed = st.session_state[JIRA_STATE_KEY], [], []
                        for row, payload in updates:
                            entry = {"at": datetime.now().isoformat(timespec="seconds"), "by": _who(),
                                     "action": "jira_version_update", "project": JIRA_PROJECT,
                                     "version": row["Version"], "jira_id": row["Jira id"], "name": row["Jira version"],
                                     "before": {"releaseDate": rc._iso(row["Jira release date"]) or None,
                                                "description": row["Jira description"]},
                                     "after": payload}
                            try:
                                body = rcj.update_jira_version(put, row["Jira id"], payload)
                                new_df = rcj.apply_version_update(new_df, row["Jira id"], body, payload)
                                entry["status"] = "updated"
                                done.append(row["Jira version"])
                            except rcj.JiraVersionsError as exc:
                                entry.update(status="failed", error=str(exc))
                                failed.append(f"{row['Jira version']}: {exc}")
                            try:
                                rce.append_audit(entry)
                            except OSError:
                                pass
                        st.session_state[JIRA_STATE_KEY] = new_df
                        for f in failed:
                            st.error(f)
                        if done and not failed:
                            st.toast(f"Updated {len(done)} Jira version(s).")
                            st.rerun()
                        elif done:
                            st.success(f"Updated: {', '.join(done)}")

        if not linked.empty:
            with st.container(border=True):
                st.markdown("**Link to Jira**")
                needs = linked[linked["Link"].isin([rcj.UNLINKED, rcj.NAME_DIFFERS])]["Version"].tolist()
                ordered = needs + [v for v in linked["Version"] if v not in needs]
                c1, c2 = st.columns([1, 3])
                version = c1.selectbox("Calendar release", ordered, key="rc_link_version",
                                       format_func=lambda v: f"{v} ⚠️" if v in needs else v)
                current = linked.set_index("Version").loc[version]
                opts = rcj.link_options(jira_df, linked_all, version, NAME_TEMPLATE)  # taken = by any release
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

                # ---- create the release in Jira when it is not there
                if current["Link"] in (rcj.UNLINKED, rcj.NAME_DIFFERS, rcj.NOT_IN_JIRA):
                    st.markdown("**Create in Jira**")
                    new_name = rcj.release_name(NAME_TEMPLATE, version)
                    try:
                        jira_mode, _ = rce.load_write_config(os.environ)
                    except ValueError as exc:
                        jira_mode = None
                        st.error(str(exc))
                    exists = rcj.name_exists(jira_df, new_name)
                    prod_info = rc.prod_deploy_info(events, version)
                    if prod_info["title"]:
                        st.caption(f"From the calendar's Prod Deploy event “{prod_info['title']}”"
                                   f" on {prod_info['date']:%d %b %Y}: release date and description below.")
                    else:
                        st.caption("This release has no Prod Deploy event in the calendar: no date or description to copy.")
                    j1, j2 = st.columns([1, 2])
                    new_date = j1.date_input("Release date", key=f"rc_jira_new_date_{version}", format="DD/MM/YYYY",
                                             value=prod_info["date"].date() if prod_info["date"] is not None else None,
                                             help="Prefilled with the Prod Deploy date of the Confluence calendar.")
                    new_desc = j2.text_area("Description", value=prod_info["description"],
                                            key=f"rc_jira_new_desc_{version}", height=90,
                                            help="Prefilled with the description of the Prod Deploy event in "
                                                 "Confluence. Edit or clear it before creating.")
                    if exists:
                        st.caption(f"Jira already has a version named {new_name}. Reload Jira versions.")
                    elif jira_mode == "sandbox":
                        st.caption(f"🧪 Sandbox mode: creating Jira versions is blocked. Set {rce.ENV_WRITE_MODE}=live "
                                   "in .env to create them.")
                    else:
                        st.caption(f"Creates the unreleased version **{new_name}** in Jira project {JIRA_PROJECT} "
                                   f"and links it to release {version}.")
                    if st.button(f"Create {new_name} in Jira", key="rc_jira_create",
                                 disabled=exists or jira_mode != "live"):
                        audit = {"at": datetime.now().isoformat(timespec="seconds"), "by": _who(),
                                 "action": "jira_version_create", "project": JIRA_PROJECT, "version": version,
                                 "name": new_name, "release_date": f"{new_date}" if new_date else None}
                        try:
                            created = rcj.create_jira_version(
                                rcj.make_jira_poster(JIRA_SERVER, JIRA_TOKEN, AUTH_METHOD, EMAIL), JIRA_PROJECT,
                                new_name, new_date, new_desc, existing=jira_df)
                        except rcj.JiraVersionsError as exc:
                            audit.update(status="failed", error=str(exc))
                            st.error(str(exc))
                        else:
                            audit.update(status="created", jira_id=str(created["id"]))
                            st.session_state[JIRA_STATE_KEY] = pd.concat(
                                [jira_df, rcj.jira_versions_dataframe([created])], ignore_index=True)
                            try:  # link it explicitly, so it stays linked even if the template changes later
                                rcj.save_links(rcj.set_link(links, version, str(created["id"]),
                                                            created.get("name") or new_name, linked_by=_who()))
                                audit["linked"] = True
                                st.toast(f"Created {new_name} in Jira and linked it to release {version}.")
                            except OSError as exc:
                                audit["linked"] = False
                                st.toast(f"Created {new_name} in Jira, but the link could not be saved: {exc}")
                        try:
                            rce.append_audit(audit)
                        except OSError:
                            pass
                        if audit["status"] == "created":
                            st.rerun()

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
    st.caption("Add, change or delete releases in the Confluence Team Calendar. Only the events behind "
               "the cells you change are written; deleting a row deletes that release's step events. Before "
               "publishing you see every change, and the calendar is re-read: if someone changed those events "
               "meanwhile, publishing is blocked.")
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
                    rce.NOTES: st.column_config.TextColumn("Description", help="Saved as the description of the Prod Deploy event.",
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
                        f"{counts.get('Deleted', 0)} deleted · {counts.get('Unchanged', 0)} unchanged · "
                        f"{len(plan.changes)} event writes")
            if plan.changes:
                st.dataframe(pd.DataFrame([{
                    "Release": c.version, "Step": c.type_title, "Action": c.action.capitalize(),
                    "Before": (f"{c.before['start']} → {c.before['end']}" if c.before else "—"),
                    "After": f"{c.after['start']} → {c.after['end']}" if c.after else "deleted",
                    "Title": (c.after or c.before)["title"],
                    "Description": ("" if c.action == "delete" else
                                    "changed" if c.before and c.before["description"] != c.after["description"]
                                    else ("set" if not c.before and c.after["description"] else "")),
                } for c in plan.changes]), hide_index=True, width="stretch")
                changed_rows = plan.rows[plan.rows["Status"] != "Unchanged"]
                if not changed_rows.empty:
                    st.dataframe(changed_rows, hide_index=True, width="stretch")

            confirmed = True
            if plan.deletions and not plan.errors:
                versions = sorted({c.version for c in plan.deletions}, key=rc.version_key)
                st.warning(f"🗑️ Deleting release(s) {', '.join(versions)} removes {len(plan.deletions)} event(s) "
                           "from the Confluence calendar. They cannot be restored from Confluence; the JSON backup "
                           "keeps their details.")
                confirmed = st.checkbox(f"Yes, delete {len(plan.deletions)} event(s) of {', '.join(versions)}",
                                        key=f"rc_edit_confirm_delete_{state['gen']}")
            can_publish = (bool(plan.changes) and not plan.errors and write_mode is not None and cal.events_editable
                           and confirmed)
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

# ----------------------------------------------------------------- Overview (Release Overview slide)
with tab_overview:
    st.caption("Builds the Release Overview slide: a timeline of the Prod Deploys of the calendar with "
               "highlights of the main releases and remarkable events. Kind follows the version "
               "(X.0.0 major, X.Y.0 minor, X.Y.Z hot fix); releases from today on are drawn as upcoming. "
               "Only the PowerPoint is created: the calendar and Jira are not changed.")
    o1, o2 = st.columns([1, 2])
    with o1:
        first = (pd.Timestamp(today) - pd.DateOffset(months=3)).date()
        last = (pd.Timestamp(today) + pd.DateOffset(months=1)).date()
        months = st.date_input("Months shown", value=(first, last), key="rc_ov_range", format="DD/MM/YYYY",
                               help="The slide shows the whole months of this range.")
    if not (isinstance(months, (tuple, list)) and len(months) == 2):
        st.info("Choose the first and last month of the slide.")
        st.stop()
    ov_start, ov_end = months
    range_key = f"{ov_start:%Y%m}_{ov_end:%Y%m}"
    with o2:
        ov_title = st.text_input("Title", key="rc_ov_title",
                                 value=f"{os.getenv('PROJECT_NAME', 'Release').strip() or 'Release'} | "
                                       "Overview on current releases")

    base_rows = ro.overview_rows(releases, events, ov_start, ov_end, today)
    headline = st.text_area(
        "Summary lines", value=ro.default_headline(base_rows, today), key=f"rc_ov_headline_{range_key}", height=80,
        help="Shown under the title, one line each. Release names (R35.0.0) and text between **two "
             "asterisks** are highlighted in green.")

    st.markdown("**Releases**")
    if base_rows.empty:
        st.info("No Prod Deploy dates in these months.")
        ov_rows = base_rows
    else:
        edited = st.data_editor(
            base_rows.drop(columns=["Highlights"]), key=f"rc_ov_rows_{range_key}", hide_index=True,
            width="stretch", disabled=["Version", "Prod Deploy"],
            column_config={
                "Prod Deploy": st.column_config.DateColumn("Prod Deploy", format="DD MMM YYYY"),
                "Kind": st.column_config.SelectboxColumn("Kind", options=list(ro.KINDS), required=True),
                "Box": st.column_config.CheckboxColumn("Box", help="Box with highlights above the timeline."),
                "Incidents": st.column_config.SelectboxColumn(
                    "Traffic light", options=list(ro.INCIDENT_LEVELS),
                    help="Green / yellow / red dot in the box of a deployed release: without, minor or major "
                         "incidents. Green by default; leave it empty to hide it. Upcoming releases have none."),
            })
        ov_rows = edited.copy()
        highlights = dict(zip(base_rows["Version"], base_rows["Highlights"]))
        boxed = ov_rows[ov_rows["Box"].fillna(False).astype(bool)]
        if not boxed.empty:
            st.caption("Highlights of each box, one bullet per line. Prefilled with the description of the "
                       "Prod Deploy event in the calendar.")
            cols = st.columns(min(len(boxed), 3))
            for i, version in enumerate(boxed["Version"]):
                with cols[i % len(cols)]:
                    highlights[version] = st.text_area(f"R{version}", value=highlights.get(version, ""),
                                                       key=f"rc_ov_hl_{version}", height=130)
        ov_rows["Highlights"] = ov_rows["Version"].map(highlights).fillna("")

    st.markdown("**Remarkable events**")
    events_key = f"rc_ov_events_base_{range_key}"
    if events_key not in st.session_state:
        st.session_state[events_key] = pd.DataFrame({"Date": pd.Series(dtype="object"), "Text": pd.Series(dtype="str")})
    remarkable = st.data_editor(
        st.session_state[events_key], key=f"rc_ov_events_{range_key}", num_rows="dynamic", hide_index=True,
        width="stretch",
        column_config={
            "Date": st.column_config.DateColumn("Date", format="DD MMM YYYY", required=True),
            "Text": st.column_config.TextColumn(
                "Text", width="large",
                help="Drawn in a box under the timeline. Separate lines with | ; lines starting with - are bullets, "
                     "e.g. Report generation saturated | - Non critical reports moved to 35.0.0"),
        })
    remarkable = remarkable.assign(Text=remarkable["Text"].fillna("").astype(str).str.replace(r"\s*\|\s*", "\n", regex=True))

    config = st.session_state.setdefault("rc_overview_config", {})
    template_path = render_slide_template_selector(config, "rc_ov_template")

    elements = ro.plan_overview(ov_rows, remarkable, ov_start, ov_end, ov_title, headline, today)
    st.markdown("**Preview**")
    st.image(ro.overview_svg(elements), width="stretch")
    st.caption("Approximate preview; the PowerPoint uses the template's fonts, logo and footer.")
    try:
        pptx_bytes = ro.build_overview_pptx(elements, template_path)
    except Exception as exc:  # unreadable template
        st.error(f"Could not build the PowerPoint: {exc}")
    else:
        st.download_button("Download Release Overview (.pptx)", pptx_bytes, type="primary", key="rc_ov_download",
                           file_name=f"Release_Overview_{today:%Y-%m-%d}.pptx",
                           mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")
