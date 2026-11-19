"""Release Calendar ↔ Jira linking: matching, manual links, warnings and the page tab (no network)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import release_calendar as rc  # noqa: E402
from utils import release_calendar_edit as rce  # noqa: E402
from utils import release_calendar_jira as rcj  # noqa: E402

SAMPLE = (ROOT / "tests/fixtures/release_calendar/sample.ics").read_text(encoding="utf-8")
TODAY = date(2026, 11, 19)
TEMPLATE = "DIGITAL:HUB {version}"
JIRA = [
    {"id": "100", "name": "DIGITAL:HUB 35.0.0", "releaseDate": "2026-11-05", "released": True},
    {"id": "101", "name": "DIGITAL:HUB 36.0.0", "releaseDate": "2026-12-17", "released": False},
    {"id": "102", "name": "MOBILE 36.0.0", "releaseDate": "2026-12-01", "released": False},
    {"id": "103", "name": "DIGITAL:HUB 37.1", "released": False},
    {"id": "104", "name": "DIGITAL:HUB 30.0.0", "releaseDate": "2026-01-10", "released": True, "archived": True},
    {"id": "105", "name": "Backlog"},
    {"name": "no id"},
]


def releases():
    return rc.releases_dataframe(rc.events_dataframe(rc.parse_ics(SAMPLE)), TODAY)


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.rel = releases()
        self.jira = rcj.jira_versions_dataframe(JIRA)

    def test_jira_dataframe(self):
        self.assertEqual(list(self.jira["Jira id"]), ["100", "101", "102", "103", "104", "105"])
        by_id = self.jira.set_index("Jira id")
        self.assertEqual(by_id.loc["103", "Version"], "37.1.0")
        self.assertEqual(by_id.loc["105", "Version"], "")
        self.assertTrue(pd.isna(by_id.loc["103", "Jira release date"]))
        self.assertTrue(by_id.loc["104", "Archived"])

    def test_auto_link_by_template_name_and_dates_compared(self):
        linked = rcj.link_releases(self.rel, self.jira, {}, TEMPLATE).set_index("Version")
        self.assertEqual(linked.loc["35.0.0", ["Jira id", "Link", "Date check"]].tolist(), ["100", "Auto", "Match"])
        self.assertEqual(linked.loc["36.0.0", ["Jira id", "Link", "Date check"]].tolist(),
                         ["101", "Auto", "Jira +2 d"])
        self.assertEqual(linked.loc["36.0.0", "Days off"], 2)
        self.assertEqual(linked.loc["37.0.0", ["Jira id", "Link"]].tolist(), ["", "Not linked"])
        self.assertEqual(linked.loc["37.0.0", "Expected name"], "DIGITAL:HUB 37.0.0")
        # the calendar columns are kept untouched
        self.assertTrue(linked.reset_index()[self.rel.columns].equals(self.rel))

    def test_same_number_other_name_is_not_auto_linked(self):
        jira = self.jira[self.jira["Jira id"] != "101"]  # only "MOBILE 36.0.0" left for 36
        linked = rcj.link_releases(self.rel, jira, {}, TEMPLATE)
        self.assertEqual(linked.set_index("Version").loc["36.0.0", ["Jira id", "Link"]].tolist(), ["", "Name differs"])
        self.assertTrue(any("no Jira version named 'DIGITAL:HUB 36.0.0'" in w and "another name" in w
                            for w in rcj.link_warnings(linked, TODAY)))

    def test_other_template(self):
        jira = rcj.jira_versions_dataframe([{"id": "1", "name": "Release 36.0.0 (HUB)"},
                                            {"id": "2", "name": "DIGITAL:HUB 36.0.0"}])
        linked = rcj.link_releases(self.rel, jira, {}, "Release {version} (HUB)").set_index("Version")
        self.assertEqual(linked.loc["36.0.0", ["Expected name", "Jira id", "Link"]].tolist(),
                         ["Release 36.0.0 (HUB)", "1", "Auto"])

    def test_template_name_ignores_case_and_spaces(self):
        jira = rcj.jira_versions_dataframe([{"id": "9", "name": "digital:hub   36.0.0 "}])
        linked = rcj.link_releases(self.rel, jira, {}, TEMPLATE).set_index("Version")
        self.assertEqual(linked.loc["36.0.0", ["Jira id", "Link"]].tolist(), ["9", "Auto"])

    def test_template_helpers(self):
        self.assertEqual(rcj.release_name(" DIGITAL:HUB {version} ", "37.0.0"), "DIGITAL:HUB 37.0.0")
        for bad in ("DIGITAL:HUB", "{version} {version}", ""):
            with self.assertRaisesRegex(ValueError, "{version}"):
                rcj.validate_template(bad)
        with self.assertRaises(ValueError):
            rcj.link_releases(self.rel, self.jira, {}, "DIGITAL:HUB")
        self.assertTrue(rcj.follows_template("DIGITAL:HUB 37.0.0", TEMPLATE))
        self.assertTrue(rcj.follows_template("digital:hub  37.0.0", TEMPLATE))
        for name in ("DIGITAL:HUB37.0.0", "MOBILE 37.0.0", "DIGITAL:HUB 37.0", "DIGITAL:HUB 37.0.0 hotfix"):
            self.assertFalse(rcj.follows_template(name, TEMPLATE), name)
        self.assertEqual(rcj.template_regex(TEMPLATE).match("DIGITAL:HUB 37.0.0")["version"], "37.0.0")

    def test_manual_link_wins_and_not_in_jira(self):
        links = rcj.set_link({}, "36.0.0", "102", "MOBILE 36.0.0", linked_by="me")
        links = rcj.set_link(links, "37.0.0", "103", "DIGITAL:HUB 37.1")
        links = rcj.set_link(links, "35.0.0", "", "")
        linked = rcj.link_releases(self.rel, self.jira, links, TEMPLATE).set_index("Version")
        self.assertEqual(linked.loc["36.0.0", ["Jira id", "Link", "Days off"]].tolist(), ["102", "Manual", -14])
        self.assertEqual(linked.loc["37.0.0", ["Jira id", "Link", "Date check"]].tolist(),
                         ["103", "Manual", "No Jira date"])
        self.assertEqual(linked.loc["35.0.0", ["Jira id", "Link"]].tolist(), ["", "Not in Jira"])
        back = rcj.link_releases(self.rel, self.jira, rcj.clear_link(links, "35.0.0"), TEMPLATE)
        self.assertEqual(back.set_index("Version").loc["35.0.0", "Link"], "Auto")

    def test_manual_link_to_deleted_version(self):
        links = rcj.set_link({}, "36.0.0", "999", "DIGITAL:HUB 36.0.0 (old)")
        linked = rcj.link_releases(self.rel, self.jira, links, TEMPLATE).set_index("Version")
        self.assertEqual(linked.loc["36.0.0", ["Jira id", "Jira version", "Link"]].tolist(),
                         ["999", "DIGITAL:HUB 36.0.0 (old)", "Manual (missing in Jira)"])
        self.assertTrue(any("no longer exists" in w for w in rcj.link_warnings(linked.reset_index(), TODAY)))

    def test_warnings_skip_history(self):
        linked = rcj.link_releases(self.rel, self.jira, {}, TEMPLATE)
        w = rcj.link_warnings(linked, TODAY)
        self.assertTrue(any("36.0.0" in x and "differs" in x for x in w))
        self.assertTrue(any("37.0.0 is not linked" in x for x in w))
        self.assertFalse(any("35.0.0" in x for x in w))
        unlinked_35 = rcj.link_releases(self.rel, self.jira.iloc[0:0], {}, TEMPLATE)
        self.assertFalse(any("35.0.0" in x for x in rcj.link_warnings(unlinked_35, TODAY)))  # deployed: history

    def test_options_exclude_archived_and_taken(self):
        linked = rcj.link_releases(self.rel, self.jira, {}, TEMPLATE)
        opts = rcj.link_options(self.jira, linked, "37.0.0", TEMPLATE)
        self.assertNotIn("104", set(opts["Jira id"]))  # archived
        self.assertFalse({"100", "101"} & set(opts["Jira id"]))  # linked to 35 and 36
        self.assertEqual(opts.iloc[0]["Jira id"], "103")  # nothing with 37.0.0: unreleased versions first
        own = rcj.link_options(self.jira, linked, "36.0.0", TEMPLATE)
        self.assertEqual(list(own["Jira id"][:2]), ["101", "102"])  # template name, then same X.Y.Z

    def test_filter_by_prod_date(self):
        linked = rcj.link_releases(self.rel, self.jira, {}, TEMPLATE)  # Prod: 35 -> 05 Nov, 36 -> 15 Dec, 37 -> none
        def versions(*a, **k):
            return list(rcj.filter_by_prod_date(linked, *a, **k)["Version"])
        self.assertEqual(versions(date(2026, 12, 1), date(2026, 12, 31)), ["36.0.0", "37.0.0"])
        self.assertEqual(versions(date(2026, 12, 1), date(2026, 12, 31), include_missing=False), ["36.0.0"])
        self.assertEqual(versions(date(2026, 11, 5), date(2026, 12, 15), include_missing=False), ["35.0.0", "36.0.0"])
        self.assertEqual(versions(None, date(2026, 11, 30), include_missing=False), ["35.0.0"])
        self.assertEqual(versions(date(2026, 12, 16), None), ["37.0.0"])
        self.assertEqual(versions(), ["35.0.0", "36.0.0", "37.0.0"])

    def test_prod_deploy_info(self):
        ev = rc.events_dataframe(rc.parse_ics(SAMPLE))
        info = rc.prod_deploy_info(ev, "36.0.0")
        self.assertEqual((info["date"], info["title"]), (pd.Timestamp("2026-12-15"), "Release 36.0.0"))
        self.assertTrue(info["description"].startswith("* Spring Boot"))
        self.assertEqual(rc.prod_deploy_info(ev, "37.0.0"), {"date": None, "title": "", "description": ""})
        two = pd.concat([ev, ev[ev["UID"] == "prod-36@example"].assign(
            Start=pd.Timestamp("2026-12-10"), Summary="Prod 36.0.0 early", Description="Other notes")])
        info = rc.prod_deploy_info(two, "36.0.0")
        self.assertEqual(info["date"], pd.Timestamp("2026-12-10"))
        self.assertEqual(info["title"], "Prod 36.0.0 early / Release 36.0.0")
        self.assertTrue(info["description"].startswith("Other notes\n\n* Spring Boot"))

    def test_version_url(self):
        self.assertEqual(rcj.version_url("7", "https://j/projects/P/versions/"), "https://j/projects/P/versions/7")
        self.assertEqual(rcj.version_url("7", "", "https://j/", "P"), "https://j/projects/P/versions/7")
        self.assertEqual(rcj.version_url("", "https://j/x"), "")


class CreateVersionTests(unittest.TestCase):
    def test_payload_and_success(self):
        post = MagicMock(return_value=MagicMock(status_code=201, json=lambda: {"id": "9", "name": "DIGITAL:HUB 38.0.0"}))
        body = rcj.create_jira_version(post, "PROJ", " DIGITAL:HUB 38.0.0 ", date(2027, 3, 20), "")
        self.assertEqual(body["id"], "9")
        post.assert_called_once_with("/rest/api/2/version", {"name": "DIGITAL:HUB 38.0.0", "project": "PROJ",
                                                             "released": False, "archived": False,
                                                             "releaseDate": "2027-03-20"})
        self.assertNotIn("releaseDate", rcj.version_payload("P", "n"))

    def test_refusals_and_errors(self):
        jira = rcj.jira_versions_dataframe(JIRA)
        post = MagicMock()
        with self.assertRaisesRegex(rcj.JiraVersionsError, "already has"):
            rcj.create_jira_version(post, "P", "digital:hub  36.0.0", existing=jira)
        post.assert_not_called()
        for args, msg in ((("", "x"), "project"), (("P", " "), "empty")):
            with self.assertRaisesRegex(rcj.JiraVersionsError, msg):
                rcj.create_jira_version(post, *args)
        bad = MagicMock(status_code=400, json=lambda: {"errorMessages": [], "errors": {"name": "A version with this name already exists"}})
        with self.assertRaisesRegex(rcj.JiraVersionsError, "HTTP 400.*already exists"):
            rcj.create_jira_version(lambda p, b: bad, "P", "n")
        with self.assertRaisesRegex(rcj.JiraVersionsError, "Manage versions"):
            rcj.create_jira_version(lambda p, b: MagicMock(status_code=403), "P", "n")
        with self.assertRaisesRegex(rcj.JiraVersionsError, "reach Jira"):
            rcj.create_jira_version(MagicMock(side_effect=ConnectionError()), "P", "n")

    def test_poster_auth(self):
        with patch("requests.request") as rp_:
            rcj.make_jira_poster("https://j/", "Bearer t", "Personal Access Token (Bearer PAT)")("/p", {"a": 1})
        self.assertEqual(rp_.call_args.args[:2], ("POST", "https://j/p"))
        self.assertEqual(rp_.call_args.kwargs["headers"]["Authorization"], "Bearer t")
        with patch("requests.request") as rp_:
            rcj.make_jira_poster("https://j", "t", "Jira Cloud/Server Basic (Email/User + Token)", "me@x",
                                 method="PUT")("/p", {})
        self.assertEqual(rp_.call_args.kwargs["auth"], ("me@x", "t"))
        self.assertEqual(rp_.call_args.args[0], "PUT")


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.events = rc.events_dataframe(rc.parse_ics(SAMPLE))
        self.rel = rc.releases_dataframe(self.events, TODAY)

    def status(self, versions):
        jira = rcj.jira_versions_dataframe(versions)
        linked = rcj.link_releases(self.rel, jira, {}, TEMPLATE)
        return rcj.jira_sync_status(linked, jira, self.events).set_index("Version"), jira

    def test_status(self):
        st_, _ = self.status(JIRA)
        # 35: same date, no calendar description; 36: Jira date 2 days later, Jira has no description; 37: not linked
        self.assertEqual(list(st_.index), ["35.0.0", "36.0.0"])
        self.assertEqual(st_.loc["35.0.0", ["Date status", "Description status"]].tolist(), [rcj.OK, rcj.NO_SOURCE])
        self.assertEqual(st_.loc["36.0.0", ["Date status", "Description status"]].tolist(), [rcj.DIFFERS, rcj.MISSING])
        other = [dict(v, description=" * Spring Boot  * HTTPS, maybe? * Functional: multicountry") if v.get("id") == "101"
                 else v for v in JIRA]
        other[1] = {**other[1], "releaseDate": None}
        st2, _ = self.status(other)
        self.assertEqual(st2.loc["36.0.0", ["Date status", "Description status"]].tolist(), [rcj.MISSING, rcj.OK])
        st3, _ = self.status([dict(v, description="old description") if v.get("id") == "101" else v for v in JIRA])
        self.assertEqual(st3.loc["36.0.0", "Description status"], rcj.DIFFERS)

    def test_payload_update_and_apply(self):
        st_, jira = self.status(JIRA)
        row = st_.reset_index().set_index("Version", drop=False).loc["36.0.0"]
        self.assertEqual(rcj.sync_payload(row, True, True),
                         {"releaseDate": "2026-12-15", "description": "* Spring Boot\n* HTTPS, maybe?\n* Functional: multicountry"})
        self.assertEqual(rcj.sync_payload(row, False, False), {})
        put = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {"id": "101", "releaseDate": "2026-12-15"}))
        body = rcj.update_jira_version(put, "101", {"releaseDate": "2026-12-15"})
        put.assert_called_once_with("/rest/api/2/version/101", {"releaseDate": "2026-12-15"})
        new = rcj.apply_version_update(jira, "101", body, {"releaseDate": "2026-12-15", "description": "n"})
        self.assertEqual(new.set_index("Jira id").loc["101", "Jira release date"], pd.Timestamp("2026-12-15"))
        self.assertEqual(new.set_index("Jira id").loc["101", "Jira description"], "n")
        self.assertTrue(pd.isna(jira.set_index("Jira id").loc["103", "Jira release date"]))  # original untouched

    def test_update_errors(self):
        with self.assertRaisesRegex(rcj.JiraVersionsError, "Nothing"):
            rcj.update_jira_version(MagicMock(), "101", {})
        with self.assertRaisesRegex(rcj.JiraVersionsError, "Manage versions"):
            rcj.update_jira_version(lambda p, b: MagicMock(status_code=403), "1", {"description": "x"})
        bad = MagicMock(status_code=400, json=lambda: {"errorMessages": ["Invalid date"], "errors": {}})
        with self.assertRaisesRegex(rcj.JiraVersionsError, "\\(HTTP 400\\)\\. Invalid date"):
            rcj.update_jira_version(lambda p, b: bad, "1", {"releaseDate": "x"})


class LinksFileTests(unittest.TestCase):
    def test_round_trip_and_audit_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "links.json"
            self.assertEqual(rcj.load_links(path), {})
            links = rcj.set_link({}, "36.0.0", "101", "DIGITAL:HUB 36.0.0", linked_by="me@x",
                                 now=datetime(2026, 11, 19, 10, 0))
            rcj.save_links(links, path)
            self.assertEqual(rcj.load_links(path), {"36.0.0": {
                "jira_id": "101", "jira_name": "DIGITAL:HUB 36.0.0", "linked_by": "me@x",
                "linked_at": "2026-11-19T10:00:00"}})
            self.assertEqual([p.name for p in path.parent.iterdir()], ["links.json"])  # no temp file left
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(rcj.JiraVersionsError):
                rcj.load_links(path)


class FetchTests(unittest.TestCase):
    def test_ok_and_path(self):
        req = MagicMock(return_value=MagicMock(status_code=200, json=lambda: JIRA))
        self.assertEqual(rcj.fetch_jira_versions(req, "PROJ"), JIRA)
        req.assert_called_once_with("/rest/api/2/project/PROJ/versions")

    def test_errors(self):
        for status, msg in ((401, "Access denied"), (404, "not found"), (500, "HTTP 500")):
            with self.assertRaisesRegex(rcj.JiraVersionsError, msg):
                rcj.fetch_jira_versions(lambda p: MagicMock(status_code=status), "P")
        with self.assertRaisesRegex(rcj.JiraVersionsError, "reach Jira"):
            rcj.fetch_jira_versions(MagicMock(side_effect=ConnectionError()), "P")
        with self.assertRaisesRegex(rcj.JiraVersionsError, "project"):
            rcj.fetch_jira_versions(MagicMock(), " ")


PAGE = str(ROOT / "tools/8_Release_Calendar.py")
ENV = {rc.ENV_ICS_URL: "https://x/cal.ics", "JIRA_SERVER": "https://jira.example.com", "JIRA_API_TOKEN": "t",
       "RELEASE_PLAN_JIRA_PROJECT": "PROJ", "JIRA_VERSION_LINK_BASE": "https://jira.example.com/projects/PROJ/versions/"}


class PageTests(unittest.TestCase):
    def setUp(self):
        import streamlit as st
        st.cache_data.clear()  # the page caches the ICS download across tests
        self.addCleanup(st.cache_data.clear)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.links = Path(self.tmp.name) / "links.json"
        self.audit = Path(self.tmp.name) / "audit.jsonl"
        resp = MagicMock(status_code=200, json=lambda: JIRA)
        for p in (patch.dict(os.environ, ENV, clear=True),
                  patch("dotenv.load_dotenv", lambda *a, **k: False),
                  patch("requests.sessions.Session.request", side_effect=AssertionError("real network")),
                  patch("utils.release_calendar.fetch_ics", return_value=SAMPLE),
                  patch("utils.release_helpers.jira_request", return_value=resp),
                  patch.object(rcj, "LINKS_FILE", self.links),
                  patch.object(rcj.load_links, "__defaults__", (self.links,)),
                  patch.object(rcj.save_links, "__defaults__", (self.links,)),
                  patch.object(rce.append_audit, "__defaults__", (self.audit,))):
            p.start()
            self.addCleanup(p.stop)
        self.at = AppTest.from_file(PAGE, default_timeout=30).run()
        self.at.button(key="rc_load").click().run()

    def test_tab_loads_jira_and_saves_manual_link(self):
        at = self.at
        self.assertEqual([t.label for t in at.tabs], ["Releases", "Jira", "Edit", "Events", "Timeline", "Overview"])
        self.assertTrue(any("Load Jira versions" in i.value for i in at.info))
        at.button(key="rc_jira_load").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        table = next(d.value for d in at.dataframe if "Jira version" in d.value.columns).set_index("Version")
        self.assertEqual(table.loc["36.0.0", "Jira version"], "DIGITAL:HUB 36.0.0")
        self.assertEqual(table.loc["36.0.0", "Open"], ENV["JIRA_VERSION_LINK_BASE"] + "101")
        self.assertTrue(any("37.0.0 is not linked" in w.value for w in at.warning))
        # releases needing a link come first; the unreleased candidate is preselected
        self.assertEqual(at.selectbox(key="rc_link_version").value, "37.0.0")
        self.assertTrue(at.button(key="rc_link_clear").disabled)
        at.button(key="rc_link_save").click().run()
        self.assertEqual(rcj.load_links(self.links)["37.0.0"]["jira_id"], "103")
        table = next(d.value for d in at.dataframe if "Jira version" in d.value.columns).set_index("Version")
        self.assertEqual(table.loc["37.0.0", "Link"], "Manual")
        self.assertFalse(any("37.0.0 is not linked" in w.value for w in at.warning))
        # back to the automatic match
        at.selectbox(key="rc_link_version").set_value("37.0.0").run()
        at.button(key="rc_link_clear").click().run()
        self.assertNotIn("37.0.0", rcj.load_links(self.links))

    def test_prod_date_filter_in_tab(self):
        at = self.at
        at.button(key="rc_jira_load").click().run()
        at.date_input(key="rc_jira_range").set_value((date(2026, 12, 1), date(2026, 12, 31))).run()
        at.checkbox(key="rc_jira_no_prod").uncheck().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        table = next(d.value for d in at.dataframe if "Jira version" in d.value.columns)
        self.assertEqual(list(table["Version"]), ["36.0.0"])
        self.assertTrue(any("1 of 3 releases" in c.value for c in at.caption))
        self.assertFalse(any("37.0.0 is not linked" in w.value for w in at.warning))  # Jira warnings follow the filter
        self.assertEqual(at.selectbox(key="rc_link_version").options, ["36.0.0"])
        at.date_input(key="rc_jira_range").set_value((date(2030, 1, 1), date(2030, 2, 1))).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertTrue(any("No releases with a Prod Deploy date" in i.value for i in at.info))
        self.assertNotIn("rc_link_version", [s.key for s in at.selectbox])

    def test_create_in_jira_blocked_in_sandbox(self):
        at = self.at
        at.button(key="rc_jira_load").click().run()
        self.assertEqual(at.selectbox(key="rc_link_version").value, "37.0.0")  # not linked
        self.assertTrue(at.button(key="rc_jira_create").disabled)
        self.assertTrue(any("creating Jira versions is blocked" in c.value for c in at.caption))

    def test_create_in_jira_links_the_release(self):
        post = MagicMock(return_value=MagicMock(status_code=201, json=lambda: {
            "id": "200", "name": "DIGITAL:HUB 37.0.0", "released": False}))
        with patch.dict(os.environ, {rce.ENV_WRITE_MODE: "live"}), \
                patch("utils.release_calendar_jira.make_jira_poster", return_value=post):
            at = AppTest.from_file(PAGE, default_timeout=30).run()
            at.button(key="rc_load").click().run()
            at.button(key="rc_jira_load").click().run()
            self.assertEqual(at.selectbox(key="rc_link_version").value, "37.0.0")
            self.assertEqual(at.button(key="rc_jira_create").label, "Create DIGITAL:HUB 37.0.0 in Jira")
            self.assertEqual(at.text_area(key="rc_jira_new_desc_37.0.0").value, "")  # 37 has no Prod Deploy event
            self.assertIsNone(at.date_input(key="rc_jira_new_date_37.0.0").value)
            at.text_area(key="rc_jira_new_desc_37.0.0").set_value("Q1 release").run()
            at.date_input(key="rc_jira_new_date_37.0.0").set_value(date(2027, 1, 28)).run()
            at.button(key="rc_jira_create").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        post.assert_called_once_with("/rest/api/2/version", {
            "name": "DIGITAL:HUB 37.0.0", "project": "PROJ", "released": False, "archived": False,
            "releaseDate": "2027-01-28", "description": "Q1 release"})
        table = next(d.value for d in at.dataframe if "Jira version" in d.value.columns).set_index("Version")
        self.assertEqual(table.loc["37.0.0", ["Jira version", "Link"]].tolist(), ["DIGITAL:HUB 37.0.0", "Manual"])
        saved = rcj.load_links(self.links)["37.0.0"]
        self.assertEqual((saved["jira_id"], saved["jira_name"]), ("200", "DIGITAL:HUB 37.0.0"))
        entry = json.loads(self.audit.read_text().splitlines()[0])
        self.assertEqual((entry["action"], entry["status"], entry["jira_id"], entry["linked"]),
                         ("jira_version_create", "created", "200", True))

    def test_create_prefilled_from_prod_deploy_event(self):
        without_36 = [v for v in JIRA if v.get("id") not in ("101", "102")]
        post = MagicMock(return_value=MagicMock(status_code=201, json=lambda: {"id": "201", "name": "DIGITAL:HUB 36.0.0"}))
        with patch.dict(os.environ, {rce.ENV_WRITE_MODE: "live"}), \
                patch("utils.release_helpers.jira_request", return_value=MagicMock(status_code=200, json=lambda: without_36)), \
                patch("utils.release_calendar_jira.make_jira_poster", return_value=post):
            at = AppTest.from_file(PAGE, default_timeout=30).run()
            at.button(key="rc_load").click().run()
            at.button(key="rc_jira_load").click().run()
            at.selectbox(key="rc_link_version").set_value("36.0.0").run()
            self.assertEqual(at.date_input(key="rc_jira_new_date_36.0.0").value, date(2026, 12, 15))
            self.assertEqual(at.text_area(key="rc_jira_new_desc_36.0.0").value,
                             "* Spring Boot\n* HTTPS, maybe?\n* Functional: multicountry")
            self.assertTrue(any("Prod Deploy event “Release 36.0.0” on 15 Dec 2026" in c.value for c in at.caption))
            at.button(key="rc_jira_create").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(rcj.load_links(self.links)["36.0.0"]["jira_id"], "201")
        payload = post.call_args.args[1]
        self.assertEqual((payload["releaseDate"], payload["description"]),
                         ("2026-12-15", "* Spring Boot\n* HTTPS, maybe?\n* Functional: multicountry"))

    def test_sync_panel_blocked_in_sandbox(self):
        at = self.at
        at.button(key="rc_jira_load").click().run()
        self.assertTrue(any("1 release date(s) and 1 description(s) to fill or fix" in m.value for m in at.markdown))
        self.assertTrue(at.button(key="rc_jira_sync").disabled)

    def test_sync_fills_missing_description(self):
        put = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {"id": "101"}))
        with patch.dict(os.environ, {rce.ENV_WRITE_MODE: "live"}), \
                patch("utils.release_calendar_jira.make_jira_poster", return_value=put):
            at = AppTest.from_file(PAGE, default_timeout=30).run()
            at.button(key="rc_load").click().run()
            at.button(key="rc_jira_load").click().run()
            self.assertEqual(at.button(key="rc_jira_sync").label, "Update 1 Jira version(s)")
            at.button(key="rc_jira_sync").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        # only the missing description is filled by default; the differing date is left to the user
        put.assert_called_once_with("/rest/api/2/version/101",
                                    {"description": "* Spring Boot\n* HTTPS, maybe?\n* Functional: multicountry"})
        self.assertTrue(any("1 release date(s) and 0 description(s)" in m.value for m in at.markdown))
        entry = json.loads(self.audit.read_text().splitlines()[0])
        self.assertEqual((entry["action"], entry["status"], entry["jira_id"]), ("jira_version_update", "updated", "101"))

    def test_jira_not_configured(self):
        with patch.dict(os.environ, {"JIRA_API_TOKEN": ""}):
            at = AppTest.from_file(PAGE, default_timeout=30).run()
            at.button(key="rc_load").click().run()
        self.assertTrue(any("JIRA_SERVER and JIRA_API_TOKEN" in i.value for i in at.info))

    def test_template_from_configuration(self):
        with patch.dict(os.environ, {rcj.ENV_NAME_TEMPLATE: "Release {version} (HUB)"}):
            at = AppTest.from_file(PAGE, default_timeout=30).run()
            at.button(key="rc_load").click().run()
            at.button(key="rc_jira_load").click().run()
        self.assertTrue(any("Release 37.0.0 (HUB)" in c.value for c in at.caption))
        table = next(d.value for d in at.dataframe if "Jira version" in d.value.columns).set_index("Version")
        self.assertNotIn("Expected name", table.columns)
        self.assertEqual(table.loc["36.0.0", "Link"], "Name differs")  # Jira uses DIGITAL:HUB names

    def test_invalid_template_is_reported(self):
        with patch.dict(os.environ, {rcj.ENV_NAME_TEMPLATE: "DIGITAL:HUB"}):
            at = AppTest.from_file(PAGE, default_timeout=30).run()
            at.button(key="rc_load").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertTrue(any("{version}" in e.value and "Configuration" in e.value for e in at.error))
        self.assertNotIn("rc_jira_load", [b.key for b in at.button])  # no Jira load with a broken template


class ConfigurationTemplateTests(unittest.TestCase):
    """Configuration → Confluence block holds the release name template, saved to .env."""

    def test_field_saved_and_validated(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('st.text_input("Release name template:"', src)
        self.assertIn('kv["RELEASE_NAME_TEMPLATE"] = st.session_state.release_name_template', src)
        self.assertIn('os.getenv("RELEASE_NAME_TEMPLATE", "") or "DIGITAL:HUB {version}"', src)
        self.assertIn("st.session_state.release_name_template != rname_in", src)
        self.assertIn('rname_typed.count("{version}") == 1', src)
        self.assertLess(src.index('"central_conf_ics"'), src.index('"central_release_name_template"'))
        self.assertLess(src.index('"central_release_name_template"'), src.index("Local AI (Ollama)"))


if __name__ == "__main__":
    unittest.main()
