"""Release Calendar ↔ Jira linking: matching, manual links, warnings and the page tab (no network)."""
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

    def test_version_url(self):
        self.assertEqual(rcj.version_url("7", "https://j/projects/P/versions/"), "https://j/projects/P/versions/7")
        self.assertEqual(rcj.version_url("7", "", "https://j/", "P"), "https://j/projects/P/versions/7")
        self.assertEqual(rcj.version_url("", "https://j/x"), "")


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
        resp = MagicMock(status_code=200, json=lambda: JIRA)
        for p in (patch.dict(os.environ, ENV, clear=True),
                  patch("dotenv.load_dotenv", lambda *a, **k: False),
                  patch("requests.sessions.Session.request", side_effect=AssertionError("real network")),
                  patch("utils.release_calendar.fetch_ics", return_value=SAMPLE),
                  patch("utils.release_helpers.jira_request", return_value=resp),
                  patch.object(rcj, "LINKS_FILE", self.links),
                  patch.object(rcj.load_links, "__defaults__", (self.links,)),
                  patch.object(rcj.save_links, "__defaults__", (self.links,))):
            p.start()
            self.addCleanup(p.stop)
        self.at = AppTest.from_file(PAGE, default_timeout=30).run()
        self.at.button(key="rc_load").click().run()

    def test_tab_loads_jira_and_saves_manual_link(self):
        at = self.at
        self.assertEqual([t.label for t in at.tabs], ["Releases", "Jira", "Edit", "Events", "Timeline"])
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
        table = next(d.value for d in at.dataframe if "Expected name" in d.value.columns).set_index("Version")
        self.assertEqual(table.loc["36.0.0", "Expected name"], "Release 36.0.0 (HUB)")
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
