"""Release Calendar editing (Epic 2): Team Calendars API client, change plan and safe publish (no network)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import release_calendar as rc  # noqa: E402
from utils import release_calendar_api as api  # noqa: E402
from utils import release_calendar_edit as rce  # noqa: E402
from utils import release_calendar_jira as rcj  # noqa: E402

CAL_ID = "8eb30486-671b-435b-9387-3cd9913994ed"
TYPES = ["QS Freeze", "Pre Deploy", "Regression Test", "Load Test", "PEN test PreLive", "BAT", "Prod Deploy",
         "Constraint"]
CHILD = {t: f"child-{i}" for i, t in enumerate(TYPES)}
TYPE_ID = {t: f"type-{i}" for i, t in enumerate(TYPES)}
WINDOW = (date(2026, 6, 1), date(2027, 12, 31))


def raw_event(uid, title, etype, start, end=None, **kw):
    end = end or start
    ev = {"id": uid, "title": title, "customEventTypeId": TYPE_ID[etype], "subCalendarId": CHILD[etype],
          "allDay": True, "start": f"{start}T00:00:00.000+01:00", "end": f"{end}T00:00:00.000+01:00",
          "description": "", "eventType": "custom"}
    ev.update(kw)
    return ev


class FakeConfluence:
    """In-memory Team Calendars: subcalendars.json, events.json GET/PUT."""

    def __init__(self, events, editable=True):
        self.events = {e["id"]: e for e in events}
        self.editable = editable
        self.puts = []
        self.deletes = []
        self.ignore_delete = False
        self.fail_put_after = None   # fail the n-th PUT (0-based)
        self.ignore_description = False
        self.n = 0

    def send(self, method, path, params=None, data=None):
        params = params or {}
        if path.endswith("/subcalendars.json"):
            if params.get("include") != CAL_ID:
                return self._json({"success": True, "payload": []})
            children = [{"subCalendar": {"id": CHILD[t], "parentId": CAL_ID, "customEventTypes": [
                {"customEventTypeId": TYPE_ID[t], "title": t}]}} for t in TYPES]
            return self._json({"success": True, "payload": [{
                "subCalendar": {"id": CAL_ID, "name": "Recall 2 Release Calendar", "timeZoneId": "Europe/Madrid",
                                "spaceKey": "RECALLTWO"},
                "eventsEditable": self.editable, "childSubCalendars": children}]})
        if path.endswith("/events.json") and method == "GET":
            lo, hi = params["start"][:10], params["end"][:10]
            evs = [e for e in self.events.values() if e["subCalendarId"] == params["subCalendarId"]
                   and e["end"][:10] >= lo and e["start"][:10] <= hi]
            return self._json({"success": True, "events": evs})
        if path.endswith("/events.json") and method == "PUT":
            if self.fail_put_after is not None and len(self.puts) >= self.fail_put_after:
                return MagicMock(status_code=500, text="boom")
            form = dict(data)
            self.puts.append(form)
            etype = next(t for t, i in TYPE_ID.items() if i == form["customEventTypeId"])
            uid = form.get("uid") or f"new-{len(self.puts)}@example"
            old = self.events.get(uid, {})
            self.events[uid] = raw_event(
                uid, form["what"], etype, form["startDate"], form["endDate"],
                description=old.get("description", "") if self.ignore_description else form["description"])
            return self._json({"success": True, "event": {"id": uid}})
        if path.endswith("/events.json") and method == "DELETE":
            form = dict(data)
            self.deletes.append(form)
            ev = self.events.get(form["uid"])
            if ev is None or ev["subCalendarId"] != form["subCalendarId"]:
                return MagicMock(status_code=404, text="")
            if not self.ignore_delete:
                del self.events[form["uid"]]
            return MagicMock(status_code=204, text="")
        raise AssertionError(f"unexpected call {method} {path}")

    @staticmethod
    def _json(body):
        return MagicMock(status_code=200, text=json.dumps(body), json=lambda: body)


def sample_events():
    return [
        raw_event("qs-36", "Code Freeze 36.0.0", "QS Freeze", "2026-11-27", "2026-12-15"),
        raw_event("lt-36", "Load Test - Release 36.0.0", "Load Test", "2026-12-01", "2026-12-02"),
        raw_event("prod-36", "Release 36.0.0", "Prod Deploy", "2026-12-15", description="* Spring Boot"),
        raw_event("reg-36", "Regression Release 36.0.0", "Regression Test", "2026-11-10", allDay=False),
        raw_event("bat-37a", "BAT 37.0.0", "BAT", "2027-01-20"),
        raw_event("bat-37b", "BAT 37.0.0 (2nd)", "BAT", "2027-01-22"),
        raw_event("qs-37", "Code Freeze 37.0.0", "QS Freeze", "2027-01-15", "2027-01-28"),
        raw_event("xmas", "Christmas", "Constraint", "2026-12-24", "2026-12-25"),
        raw_event("hot", "Prod Deploy hotfix", "Prod Deploy", "2026-12-18"),
    ]


def loaded(fake=None):
    fake = fake or FakeConfluence(sample_events())
    cal = api.get_calendar(fake.send, CAL_ID)
    events = api.list_events(fake.send, cal, *WINDOW)
    return fake, cal, events


def edited_from(table, changes):
    """Copy of the table with cells changed: changes = {(version, column): value}."""
    out = table.copy()
    for (version, col), value in changes.items():
        out.loc[out["Version"] == version, col] = value
    return out


class ApiReadTests(unittest.TestCase):
    def test_calendar_and_types(self):
        fake, cal, events = loaded()
        self.assertEqual((cal.name, cal.timezone, cal.events_editable), ("Recall 2 Release Calendar", "Europe/Madrid", True))
        self.assertEqual(cal.type_by_title("prod deploy").child_id, CHILD["Prod Deploy"])
        self.assertIsNone(cal.type_by_title("Nope"))
        with self.assertRaisesRegex(api.CalendarApiError, "not found"):
            api.get_calendar(fake.send, "00000000-0000-0000-0000-000000000000")
        with self.assertRaisesRegex(api.CalendarApiError, "RELEASE_CALENDAR_ID"):
            api.get_calendar(fake.send, "")

    def test_events_parsed(self):
        _, _, events = loaded()
        by = {e.uid: e for e in events}
        self.assertEqual((by["qs-36"].start, by["qs-36"].end, by["qs-36"].version),
                         (date(2026, 11, 27), date(2026, 12, 15), "36.0.0"))
        self.assertEqual(by["prod-36"].description, "* Spring Boot")
        self.assertFalse(by["reg-36"].editable)  # timed
        self.assertTrue(by["prod-36"].editable)

    def test_parse_calendar_id(self):
        link = f"https://x/confluence/display/RECALLTWO/calendar/{CAL_ID.upper()}?calendarName=Recall"
        self.assertEqual(api.parse_calendar_id(link), CAL_ID)
        self.assertEqual(api.parse_calendar_id("nothing"), "")

    def test_http_errors(self):
        for status, msg in ((401, "Access denied"), (404, "not found"), (500, "HTTP 500")):
            with self.assertRaisesRegex(api.CalendarApiError, msg):
                api.get_calendar(lambda *a, **k: MagicMock(status_code=status, text=""), CAL_ID)
        html = MagicMock(status_code=200, text="<html>login</html>", json=MagicMock(side_effect=ValueError))
        with self.assertRaisesRegex(api.CalendarApiError, "JSON"):
            api.get_calendar(lambda *a, **k: html, CAL_ID)
        refused = MagicMock(status_code=200, text="{}", json=lambda: {"success": False, "message": "no"})
        with self.assertRaisesRegex(api.CalendarApiError, "refused"):
            api.put_event(lambda *a, **k: refused, {"what": "x"})

    def test_event_form_matches_confluence_dialog(self):
        _, cal, _ = loaded()
        et = cal.type_by_title("BAT")
        create = api.event_form(cal, et, title="BAT 38.0.0", start=date(2027, 3, 1), end=date(2027, 3, 1),
                                description="d")
        self.assertEqual({k: create[k] for k in ("subCalendarId", "childSubCalendarId", "customEventTypeId",
                                                 "eventType", "startDate", "endDate", "allDayEvent", "what",
                                                 "userTimeZoneId")},
                         {"subCalendarId": CAL_ID, "childSubCalendarId": CHILD["BAT"], "customEventTypeId": TYPE_ID["BAT"],
                          "eventType": "custom", "startDate": "2027-03-01", "endDate": "2027-03-01",
                          "allDayEvent": "true", "what": "BAT 38.0.0", "userTimeZoneId": "Europe/Madrid"})
        self.assertNotIn("uid", create)
        update = api.event_form(cal, et, title="t", start=date(2027, 3, 1), end=date(2027, 3, 1), description="",
                                uid="u1")
        self.assertEqual((update["uid"], update["originalEventSubCalendarId"], update["originalCustomEventTypeId"]),
                         ("u1", CHILD["BAT"], TYPE_ID["BAT"]))

    def test_sender_sends_xsrf_opt_out_and_bearer(self):
        with patch("utils.release_calendar_api.requests.request") as req:
            api.make_sender("https://conf/confluence/", "tok", "Personal Access Token (Bearer PAT)")("PUT", "/p", data={"a": 1})
        kw = req.call_args.kwargs
        self.assertEqual(req.call_args.args[:2], ("PUT", "https://conf/confluence/p"))
        self.assertEqual((kw["headers"]["Authorization"], kw["headers"]["X-Atlassian-Token"]), ("Bearer tok", "no-check"))


class TableAndPlanTests(unittest.TestCase):
    def setUp(self):
        self.fake, self.cal, self.events = loaded()
        self.table = rce.editable_table(self.events)

    def plan(self, edited, sandbox=None, template=rce.DEFAULT_TITLE_TEMPLATE):
        return rce.plan_changes(self.table, edited, self.events, self.cal, template, sandbox)

    def test_table(self):
        t = self.table.set_index("Version")
        self.assertEqual(list(t.index), ["36.0.0", "37.0.0"])  # hotfix has no version
        self.assertEqual((t.loc["36.0.0", "QS Freeze start"], t.loc["36.0.0", "QS Freeze end"]),
                         (date(2026, 11, 27), date(2026, 12, 15)))
        self.assertEqual(t.loc["36.0.0", "Description"], "* Spring Boot")
        self.assertEqual(t.loc["36.0.0", "Locked"], "Regression (has a time)")
        self.assertEqual(t.loc["37.0.0", "Locked"], "BAT (2 events)")
        self.assertEqual(t.loc["37.0.0", "BAT"], date(2027, 1, 20))

    def test_unchanged(self):
        p = self.plan(self.table.copy())
        self.assertEqual((p.changes, p.errors), ([], []))
        self.assertEqual(set(p.rows["Status"]), {"Unchanged"})
        # what st.data_editor gives back: datetimes, NaT for blanks
        shown = self.table.copy()
        for c in rce.DATE_COLUMNS:
            shown[c] = pd.to_datetime(shown[c])
        self.assertEqual(self.plan(shown).changes, [])

    def test_date_change_keeps_duration_and_title(self):
        p = self.plan(edited_from(self.table, {("36.0.0", "Load Test"): date(2026, 12, 3)}))
        self.assertEqual(p.errors, [])
        (c,) = p.changes
        self.assertEqual((c.action, c.uid, c.type_title), ("update", "lt-36", "Load Test"))
        self.assertEqual((c.after["start"], c.after["end"], c.after["title"]),
                         ("2026-12-03", "2026-12-04", "Load Test - Release 36.0.0"))
        self.assertEqual(c.before["start"], "2026-12-01")
        self.assertEqual(p.rows.set_index("Version").loc["36.0.0", "Status"], "Changed")

    def test_qs_freeze_and_notes_and_new_step(self):
        p = self.plan(edited_from(self.table, {
            ("36.0.0", "QS Freeze end"): date(2026, 12, 16), ("36.0.0", "Description"): "* Spring Boot\n* Java 21",
            ("36.0.0", "BAT"): date(2026, 12, 10)}))
        self.assertEqual(p.errors, [])
        by = {(c.type_title, c.action): c for c in p.changes}
        self.assertEqual(by[("QS Freeze", "update")].after["end"], "2026-12-16")
        self.assertEqual(by[("Prod Deploy", "update")].after["description"], "* Spring Boot\n* Java 21")
        self.assertEqual(by[("Prod Deploy", "update")].after["start"], "2026-12-15")  # date untouched
        self.assertEqual(by[("BAT", "create")].after,
                         {"title": "BAT - Release 36.0.0", "start": "2026-12-10", "end": "2026-12-10", "description": ""})

    def test_new_release_row(self):
        new = pd.DataFrame([{rce.KEY: None, "Version": "38.0.0", "QS Freeze start": date(2027, 3, 1),
                             "Prod Deploy": date(2027, 3, 20), "Description": "Big one"}])
        p = self.plan(pd.concat([self.table, new], ignore_index=True), template="{type} | {version}")
        self.assertEqual(p.errors, [])
        self.assertEqual(sorted((c.type_title, c.after["start"], c.after["end"], c.after["title"], c.after["description"])
                                for c in p.changes),
                         [("Prod Deploy", "2027-03-20", "2027-03-20", "Prod Deploy | 38.0.0", "Big one"),
                          ("QS Freeze", "2027-03-01", "2027-03-01", "QS Freeze | 38.0.0", "")])
        self.assertEqual(p.rows.set_index("Version").loc["38.0.0", "Status"], "New")

    def test_validation_errors(self):
        def errs(df):
            return " | ".join(self.plan(df).errors)
        base = self.table
        row = lambda **kw: pd.DataFrame([{rce.KEY: None, **kw}])  # noqa: E731
        self.assertIn("X.Y.Z", errs(pd.concat([base, row(Version="38.0", BAT=date(2027, 1, 1))])))
        self.assertIn("appears twice", errs(pd.concat([base, row(Version="38.0.0", BAT=date(2027, 1, 1)),
                                                       row(Version="38.0.0", BAT=date(2027, 1, 2))])))
        self.assertIn("appears twice", errs(pd.concat([base, row(Version="36.0.0", BAT=date(2027, 1, 1))])))
        self.assertIn("already in the calendar", errs(pd.concat([base[base["Version"] != "37.0.0"],
                                                                 row(Version="37.0.0", BAT=date(2027, 1, 1))])))
        self.assertIn("at least one date", errs(pd.concat([base, row(Version="38.0.0")])))
        self.assertIn("set a Prod Deploy date", errs(pd.concat([base, row(Version="38.0.0", BAT=date(2027, 1, 1),
                                                                          Description="x")])))
        self.assertIn("version is empty", errs(pd.concat([base, row(Version="", BAT=date(2027, 1, 1))])))
        self.assertEqual(errs(pd.concat([base, row(Version="")])), "")  # empty row ignored
        self.assertIn("clearing Load Test", errs(edited_from(base, {("36.0.0", "Load Test"): None})))
        self.assertIn("renaming", errs(edited_from(base, {("36.0.0", "Version"): "36.1.0"})))
        self.assertIn("BAT cannot be edited here (2 events)", errs(edited_from(base, {("37.0.0", "BAT"): date(2027, 1, 21)})))
        self.assertIn("Regression cannot be edited here (has a time)",
                      errs(edited_from(base, {("36.0.0", "Regression"): date(2026, 11, 11)})))
        self.assertIn("ends before it starts", errs(edited_from(base, {("36.0.0", "QS Freeze end"): date(2026, 11, 1)})))
        self.assertIn("not a date", errs(edited_from(base.astype({"BAT": object}), {("36.0.0", "BAT"): "soon"})))
        p = self.plan(edited_from(base, {("36.0.0", "Load Test"): date(2026, 12, 3)}), template="no placeholder")
        self.assertTrue(p.errors and not p.changes)

    def test_sandbox_blocks_other_versions(self):
        edited = edited_from(self.table, {("36.0.0", "Load Test"): date(2026, 12, 3)})
        self.assertIn("sandbox mode", " ".join(self.plan(edited, sandbox=("999.0.0",)).errors))
        new = pd.DataFrame([{rce.KEY: None, "Version": "999.0.0", "Prod Deploy": date(2027, 9, 9)}])
        p = self.plan(pd.concat([self.table, new], ignore_index=True), sandbox=("999.0.0",))
        self.assertEqual((p.errors, len(p.changes)), ([], 1))

    def test_write_config(self):
        self.assertEqual(rce.load_write_config({}), ("sandbox", ("999.0.0",)))
        self.assertEqual(rce.load_write_config({rce.ENV_WRITE_MODE: "LIVE"}), ("live", None))
        self.assertEqual(rce.load_write_config({rce.ENV_SANDBOX_VERSIONS: "998.0.0, 999.0.0"}),
                         ("sandbox", ("998.0.0", "999.0.0")))
        for env in ({rce.ENV_WRITE_MODE: "yolo"}, {rce.ENV_SANDBOX_VERSIONS: "999"}):
            with self.assertRaises(ValueError):
                rce.load_write_config(env)

    def test_jira_proposals(self):
        jira = rcj.jira_versions_dataframe([
            {"id": "1", "name": "DIGITAL:HUB 36.0.0", "releaseDate": "2026-12-15"},             # in calendar
            {"id": "2", "name": "DIGITAL:HUB 38.0.0", "releaseDate": "2027-03-20"},             # proposed
            {"id": "3", "name": "DIGITAL:HUB 39.0.0"},                                          # proposed, no date
            {"id": "4", "name": "DIGITAL:HUB 30.0.0", "released": True},                        # released
            {"id": "5", "name": "DIGITAL:HUB 31.0.0", "archived": True},                        # archived
            {"id": "6", "name": "MOBILE 40.0.0"},                                               # other name
            {"id": "7", "name": "DIGITAL:HUB 41.0.0"},                                          # manually linked
        ])
        links = {"37.0.0": {"jira_id": "7"}}
        props = rce.jira_proposals(jira, set(self.table["Version"]), links, "DIGITAL:HUB {version}")
        self.assertEqual(list(props["Version"]), ["38.0.0", "39.0.0"])
        self.assertEqual(props.iloc[0]["Prod Deploy"], date(2027, 3, 20))
        self.assertIsNone(props.iloc[1]["Prod Deploy"])
        rows = rce.proposal_rows(props)
        p = self.plan(pd.concat([self.table, rows.iloc[:1]], ignore_index=True))
        self.assertEqual([(c.action, c.version, c.type_title) for c in p.changes], [("create", "38.0.0", "Prod Deploy")])


class DeleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fake, self.cal, self.events = loaded()
        self.table = rce.editable_table(self.events)

    def plan(self, edited, sandbox=None, events=None):
        return rce.plan_changes(self.table, edited, events or self.events, self.cal, sandbox_versions=sandbox)

    def test_removed_row_deletes_every_step_event_of_the_release(self):
        p = self.plan(self.table[self.table["Version"] != "37.0.0"])
        self.assertEqual(p.errors, [])
        self.assertEqual(sorted((c.action, c.uid) for c in p.changes),
                         [("delete", "bat-37a"), ("delete", "bat-37b"), ("delete", "qs-37")])
        self.assertEqual(len(p.deletions), 3)
        row = p.rows.set_index("Version").loc["37.0.0"]
        self.assertEqual(row["Status"], "Deleted")
        self.assertIn("3 event(s)", row["Details"])
        # a locked (timed) step is deleted with its release too; other versions are untouched
        p36 = self.plan(self.table[self.table["Version"] != "36.0.0"])
        self.assertEqual(sorted(c.uid for c in p36.changes), ["lt-36", "prod-36", "qs-36", "reg-36"])

    def test_recurring_release_is_not_deleted(self):
        raw = sample_events() + [raw_event("pen-37", "PEN 37.0.0", "PEN test PreLive", "2027-01-19",
                                           rruleStr="FREQ=WEEKLY;COUNT=2")]
        fake, cal, events = loaded(FakeConfluence(raw))
        table = rce.editable_table(events)
        p = rce.plan_changes(table, table[table["Version"] != "37.0.0"], events, cal)
        self.assertEqual(p.changes, [])
        self.assertIn("PEN test PreLive is a recurring event", " ".join(p.errors))

    def test_sandbox_blocks_deleting_real_releases(self):
        p = self.plan(self.table[self.table["Version"] != "37.0.0"], sandbox=("999.0.0",))
        self.assertEqual(p.changes, [])
        self.assertIn("sandbox mode", " ".join(p.errors))

    def publish(self, plan, **kw):
        args = dict(allowed_id=CAL_ID, user="me@x", backup_dir=self.tmp / "bk", audit_path=self.tmp / "audit.jsonl")
        args.update(kw)
        return rce.publish(self.fake.send, self.cal, plan.changes, self.events, WINDOW, **args)

    def test_publish_deletes_verifies_and_keeps_the_rest(self):
        keep = {k: dict(v) for k, v in self.fake.events.items() if "37" not in k}
        res = self.publish(self.plan(self.table[self.table["Version"] != "37.0.0"]))
        self.assertTrue(res["ok"], res)
        self.assertEqual(sorted(d["uid"] for d in self.fake.deletes), ["bat-37a", "bat-37b", "qs-37"])
        self.assertEqual(self.fake.deletes[0]["subCalendarId"], CHILD[next(
            c.type_title for c in self.plan(self.table[self.table["Version"] != "37.0.0"]).changes)])
        self.assertEqual(self.fake.events, keep)
        backup = json.loads(Path(res["backup"]).read_text())
        self.assertTrue({"bat-37a", "bat-37b", "qs-37"} <= {e["uid"] for e in backup["events"]})
        entry = json.loads((self.tmp / "audit.jsonl").read_text().splitlines()[0])
        self.assertEqual({(c["action"], c["applied"]) for c in entry["changes"]}, {("delete", True)})

    def test_delete_conflict_and_verification(self):
        plan = self.plan(self.table[self.table["Version"] != "37.0.0"])
        self.fake.events["qs-37"]["end"] = "2027-01-30T00:00:00.000+01:00"  # moved meanwhile
        res = self.publish(plan)
        self.assertEqual(res["status"], "refused")
        self.assertEqual(self.fake.deletes, [])
        self.fake, self.cal, self.events = loaded()
        self.fake.ignore_delete = True
        res = self.publish(self.plan(self.table[self.table["Version"] != "37.0.0"]))
        self.assertEqual(res["status"], "verification_failed")
        self.assertIn("still in the calendar", res["error"])

    def test_delete_event_api(self):
        with self.assertRaises(api.CalendarApiError):
            api.delete_event(self.fake.send, "", "x")
        with self.assertRaisesRegex(api.CalendarApiError, "not found"):
            api.delete_event(self.fake.send, CHILD["BAT"], "nope")


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fake, self.cal, self.events = loaded()
        self.table = rce.editable_table(self.events)
        new = pd.DataFrame([{rce.KEY: None, "Version": "38.0.0", "Prod Deploy": date(2027, 3, 20), "Description": "n"}])
        edited = pd.concat([edited_from(self.table, {("36.0.0", "Load Test"): date(2026, 12, 3)}), new],
                           ignore_index=True)
        self.plan = rce.plan_changes(self.table, edited, self.events, self.cal)
        self.assertEqual(self.plan.errors, [])

    def publish(self, **kw):
        args = dict(allowed_id=CAL_ID, sandbox_versions=None, user="me@x", backup_dir=self.tmp / "bk",
                    audit_path=self.tmp / "audit.jsonl", now=datetime(2026, 11, 19, 15, 0))
        args.update(kw)
        return rce.publish(self.fake.send, self.cal, self.plan.changes, self.events, WINDOW, **args)

    def audit(self):
        return [json.loads(l) for l in (self.tmp / "audit.jsonl").read_text().splitlines()]

    def test_publish_writes_only_changes_verifies_backs_up_and_audits(self):
        untouched = {k: dict(v) for k, v in self.fake.events.items() if k != "lt-36"}
        res = self.publish()
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["status"], "published")
        self.assertEqual(len(self.fake.puts), 2)
        self.assertEqual(self.fake.events["lt-36"]["start"][:10], "2026-12-03")
        self.assertEqual(self.fake.events["lt-36"]["end"][:10], "2026-12-04")
        created = self.fake.events[res["applied"][1]]
        self.assertEqual((created["title"], created["description"]), ("Prod Deploy - Release 38.0.0", "n"))
        for k, v in untouched.items():  # nothing else in the calendar changed
            self.assertEqual(self.fake.events[k], v, k)
        backup = json.loads(Path(res["backup"]).read_text())
        self.assertEqual(backup["calendar"], CAL_ID)
        self.assertIn("lt-36", [e["uid"] for e in backup["events"]])
        (entry,) = self.audit()
        self.assertEqual((entry["by"], entry["status"], entry["at"]), ("me@x", "published", "2026-11-19T15:00:00"))
        self.assertEqual([(c["action"], c["version"], c["applied"]) for c in entry["changes"]],
                         [("update", "36.0.0", True), ("create", "38.0.0", True)])

    def test_conflict_blocks_publish(self):
        self.fake.events["lt-36"]["start"] = "2026-12-05T00:00:00.000+01:00"  # someone moved it meanwhile
        res = self.publish()
        self.assertEqual((res["ok"], res["status"]), (False, "refused"))
        self.assertIn("changed since you loaded it", res["error"])
        self.assertIn("36.0.0 · Load Test", res["error"])
        self.assertEqual(self.fake.puts, [])
        self.assertEqual(self.audit()[0]["status"], "refused")

    def test_conflict_when_someone_created_the_same_step(self):
        self.fake.events["p38"] = raw_event("p38", "Prod 38.0.0", "Prod Deploy", "2027-03-21")
        res = self.publish()
        self.assertIn("38.0.0 · Prod Deploy", res["error"])
        self.assertEqual(self.fake.puts, [])

    def test_unrelated_changes_do_not_block(self):
        self.fake.events["xmas"]["title"] = "Christmas holidays"
        self.fake.events["prod-36"]["description"] = "edited by someone"
        self.assertTrue(self.publish()["ok"])

    def test_allow_list_sandbox_and_permissions(self):
        self.assertIn("only allowed on the configured", self.publish(allowed_id="other")["error"])
        self.assertIn("Sandbox mode", self.publish(sandbox_versions=("999.0.0",))["error"])
        self.cal = api.CalendarInfo(**{**self.cal.__dict__, "events_editable": False})
        self.assertIn("cannot edit", self.publish()["error"])
        self.assertEqual(self.fake.puts, [])

    def test_failure_midway_reports_backup(self):
        self.fake.fail_put_after = 1
        res = self.publish()
        self.assertEqual(res["status"], "failed")
        self.assertIn("1 of 2 changes were saved", res["error"])
        self.assertIn(res["backup"], res["error"])
        self.assertEqual(len(res["applied"]), 1)
        self.assertEqual([c["applied"] for c in self.audit()[0]["changes"]], [True, False])

    def test_verification_failure(self):
        self.fake.ignore_description = True
        res = self.publish()
        self.assertEqual(res["status"], "verification_failed")
        self.assertIn("description", res["error"])
        self.assertIn("Backup", res["error"])

    def test_nothing_to_publish(self):
        res = rce.publish(self.fake.send, self.cal, [], self.events, WINDOW, allowed_id=CAL_ID,
                          audit_path=self.tmp / "audit.jsonl", backup_dir=self.tmp)
        self.assertEqual((res["ok"], res["status"]), (True, "unchanged"))


PAGE = str(ROOT / "tools/8_Release_Calendar.py")
SAMPLE = (ROOT / "tests/fixtures/release_calendar/sample.ics").read_text(encoding="utf-8")


class PageTests(unittest.TestCase):
    def start(self, env):
        import streamlit as st
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        self.fake = FakeConfluence(sample_events())
        base = {rc.ENV_ICS_URL: "https://x/cal.ics", "CONFLUENCE_SERVER": "https://conf", "CONFLUENCE_API_TOKEN": "t"}
        for p in (patch.dict(os.environ, {**base, **env}, clear=True),
                  patch("dotenv.load_dotenv", lambda *a, **k: False),
                  patch("requests.sessions.Session.request", side_effect=AssertionError("real network")),
                  patch("utils.release_calendar.fetch_ics", return_value=SAMPLE),
                  patch("utils.release_calendar_api.make_sender", lambda *a, **k: self.fake.send)):
            p.start()
            self.addCleanup(p.stop)
        at = AppTest.from_file(PAGE, default_timeout=30).run()
        at.button(key="rc_load").click().run()
        return at

    def test_needs_calendar_link(self):
        at = self.start({})
        self.assertEqual([t.label for t in at.tabs], ["Releases", "Jira", "Edit", "Events", "Timeline", "Overview"])
        self.assertTrue(any("Release Calendar link" in i.value for i in at.info))
        self.assertTrue(any("Sandbox mode" in w.value for w in at.warning))

    def test_load_for_editing_and_publish_disabled_without_changes(self):
        at = self.start({api.ENV_CALENDAR_ID: f"https://conf/display/X/calendar/{CAL_ID}?calendarName=R",
                         rce.ENV_WRITE_MODE: "live"})
        self.assertFalse(any("Sandbox mode" in w.value for w in at.warning))
        at.button(key="rc_edit_load").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertTrue(any("Recall 2 Release Calendar" in c.value for c in at.caption))
        self.assertTrue(any("0 new · 0 changed · 0 deleted · 2 unchanged" in m.value for m in at.markdown))
        self.assertTrue(at.button(key="rc_edit_publish").disabled)
        self.assertEqual(self.fake.puts, [])

    def test_bad_write_mode(self):
        at = self.start({api.ENV_CALENDAR_ID: CAL_ID, rce.ENV_WRITE_MODE: "yolo"})
        self.assertTrue(any(rce.ENV_WRITE_MODE in e.value for e in at.error))


class ConfigurationCalendarIdTests(unittest.TestCase):
    def test_field(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('st.text_input("Release Calendar link (to edit):"', src)
        self.assertIn('kv["RELEASE_CALENDAR_ID"] = st.session_state.release_calendar_id', src)
        self.assertIn("st.session_state.release_calendar_id != ccal_in", src)
        self.assertLess(src.index('"central_release_name_template"'), src.index('"central_release_calendar_id"'))
        self.assertLess(src.index('"central_release_calendar_id"'), src.index("Local AI (Ollama)"))


if __name__ == "__main__":
    unittest.main()
