"""Stage 2: AppTest for the readiness sub-pages 2, 3, 5, 6 (fixtures only, no network, no writes)."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PAGES = ROOT / "tools" / "release_plan"
FIX = ROOT / "tests" / "fixtures"
PARENT = "7177194568"
ENV = {
    "JIRA_SERVER": "https://jira.example.com/jira",
    "JIRA_API_TOKEN": "x",
    "CONFLUENCE_SERVER": "https://conf.example.com",
    "CONFLUENCE_API_TOKEN": "x",
    "RELEASE_PLAN_PARENT_PAGE": PARENT,
}
SANDBOX_ENV = dict(ENV, RELEASE_PLAN_SANDBOX_MAP="999.0.0:35.0.0")
PAGE_FILES = {
    "rr2": "2_Approval.py", "rr3": "3_Documentation_Table.py",
    "rr4": "4_Critical_Changes.py", "rr5": "5_PRE_Testing.py", "rr6": "6_Unassigned.py", "rr8": "8_Notifications.py",
}


def load(path):
    return json.loads((FIX / path).read_text(encoding="utf-8"))


class PagesCase(unittest.TestCase):
    def run_page(self, prefix, version="", click=True, env=ENV, page=None, title=None, issues=None):
        self.jqls = []
        self.conf_calls = 0
        issues = issues if issues is not None else load("release_readiness/issues.json")
        page = page if page is not None else load("release_plan/confluence_page_35.json")
        title = title or f"Release Plan {version}"

        def fake_jira(server, token, auth, email, jql, page_size=50, fields=None):
            self.jqls.append((jql, fields))
            return issues(jql) if callable(issues) else issues

        def fake_children(*a, **k):
            self.conf_calls += 1
            return {"results": [{"id": page.get("id", "1"), "title": title, "url": ""}]}

        def fake_page(*a, **k):
            self.conf_calls += 1
            return page

        self.writes = []
        patches = [
            patch.dict(os.environ, env, clear=True),
            patch("dotenv.load_dotenv", lambda *a, **k: False),
            patch("utils.jira_helpers.fetch_release_issues_with_comments", fake_jira),
            patch("utils.confluence_helpers.list_child_pages", fake_children),
            patch("utils.confluence_helpers.get_confluence_page", fake_page),
            patch("utils.confluence_helpers.update_confluence_page", side_effect=AssertionError("write")),
            patch("requests.sessions.Session.request", side_effect=AssertionError("real network")),
        ]
        self.rpost = patch("requests.post", side_effect=AssertionError("POST"))
        self.rput = patch("requests.put", side_effect=AssertionError("PUT"))
        self.rdel = patch("requests.delete", side_effect=AssertionError("DELETE"))
        self.mocks = [m.start() for m in (self.rpost, self.rput, self.rdel)]
        patches.extend([self.rpost, self.rput, self.rdel])
        for p in patches[:-3]:
            p.start()
        for p in patches:
            self.addCleanup(p.stop)
        at = AppTest.from_file(str(PAGES / PAGE_FILES[prefix]), default_timeout=20).run()
        if version:
            at.text_input(key=f"{prefix}_version").set_value(version).run()
        if click:
            at.button(key=f"{prefix}_refresh").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    def assert_no_writes(self):
        for m in self.mocks:
            m.assert_not_called()


class NoFetchBeforeClickTests(PagesCase):
    def test_nothing_fetched_before_click(self):
        for prefix in PAGE_FILES:
            with self.subTest(prefix):
                at = self.run_page(prefix, "35.0.0", click=False)
                self.assertEqual(self.jqls, [])
                self.assertEqual(self.conf_calls, 0)
                self.assertEqual(len(at.dataframe), 0)
                self.assertEqual([b.key for b in at.button], [f"{prefix}_refresh"])
                self.assert_no_writes()

    def test_refresh_disabled_without_valid_version(self):
        at = self.run_page("rr6", "", click=False)
        self.assertTrue(at.button(key="rr6_refresh").disabled)


class RenderTests(PagesCase):
    def test_pages_render_results_after_click_with_timestamp(self):
        for prefix in PAGE_FILES:
            with self.subTest(prefix):
                at = self.run_page(prefix, "35.0.0")
                self.assertEqual(len(self.jqls), 2 if prefix == "rr8" else 1)
                self.assertTrue(any(c.value.startswith("Checked at ") for c in at.caption))
                self.assertIn(f"{prefix}_data", at.session_state)
                self.assert_no_writes()

    def test_unassigned_only_own_rule_and_sorted(self):
        at = self.run_page("rr6", "35.0.0")
        df = at.dataframe[0].value
        self.assertEqual(list(df["Issue"]), ["RP-5"])
        self.assertEqual(list(df["Severity"]), ["INFO"])  # closed, no assignee
        self.assertEqual(list(df["Assignee"]), ["Unassigned"])

    def test_approval_sorted_error_warn_info(self):
        page = load("release_plan/confluence_page_35.json")
        at = self.run_page("rr2", "35.0.0", page=page)
        sev = list(at.dataframe[0].value["Severity"])
        order = {"ERROR": 0, "WARN": 1, "INFO": 2}
        self.assertEqual(sev, sorted(sev, key=order.get))
        self.assertIn("RP-2", list(at.dataframe[0].value["Issue"]))  # missing approval always listed

    def test_pre_page_lists_pre_no(self):
        at = self.run_page("rr5", "35.0.0")
        self.assertIn("RP-2", list(at.dataframe[0].value["Issue"]))

    def test_fields_param_requests_readiness_fields(self):
        from utils.jira_helpers import RELEASE_READINESS_FIELDS
        self.run_page("rr3", "35.0.0")
        self.assertEqual(self.jqls[0][1], RELEASE_READINESS_FIELDS)

    def test_phase1_no_confluence_for_non_approval_pages(self):
        self.run_page("rr3", "35.0.0")
        self.assertEqual(self.conf_calls, 0)


class SandboxTests(PagesCase):
    def test_typed_999_reads_35_and_shows_banner(self):
        page = load("release_plan/confluence_page_999_v22.json")
        at = self.run_page("rr6", "999.0.0", env=SANDBOX_ENV, page=page)
        self.assertIn("DIGITAL:HUB 35.0.0", self.jqls[0][0])
        self.assertNotIn("999.0.0", self.jqls[0][0])
        self.assertTrue(any("SANDBOX" in w.value for w in at.warning))
        self.assert_no_writes()

    def test_no_banner_without_sandbox_map(self):
        at = self.run_page("rr6", "35.0.0")
        self.assertEqual([w for w in at.warning if "SANDBOX" in w.value], [])
        self.assertIn("DIGITAL:HUB 35.0.0", self.jqls[0][0])


class FreezeDateTests(PagesCase):
    def test_freeze_date_read_from_page(self):
        page = load("release_plan/confluence_page_999_v22.json")
        at = self.run_page("rr2", "999.0.0", env=SANDBOX_ENV, page=page)
        self.assertTrue(any(c.value.startswith("Freeze date (from the Release Plan page)") for c in at.caption))
        self.assertEqual(len(at.date_input), 0)
        self.assert_no_writes()

    def test_manual_date_input_when_page_has_no_freeze_date(self):
        at = self.run_page("rr2", "35.0.0")
        self.assertEqual(len(at.date_input), 1)
        self.assertEqual(at.date_input[0].key, "rr2_freeze_manual")
        # without any date: missing approval is WARN, never ERROR (AC9)
        df = at.dataframe[0].value
        self.assertNotIn("ERROR", list(df["Severity"][df["Issue"] == "RP-2"]))

    def test_manual_past_date_turns_missing_approval_into_error(self):
        from datetime import date, timedelta
        at = self.run_page("rr2", "35.0.0")
        at.date_input[0].set_value(date.today() - timedelta(days=30)).run()
        df = at.dataframe[0].value
        row = df[df["Issue"] == "RP-2"].iloc[0]
        self.assertEqual(row["Severity"], "ERROR")
        self.assertIn("needs freeze exception", row["Reason"])
        self.assertEqual(self.jqls.__len__(), 1)  # no refetch on date change
        self.assert_no_writes()

    def test_page8_manual_date_input_and_past_date_gives_error_text(self):
        from datetime import date, timedelta
        at = self.run_page("rr8", "35.0.0")
        self.assertEqual(len(at.date_input), 1)
        self.assertEqual(at.date_input[0].key, "rr8_freeze_manual")
        before = "\n".join(c.value for c in at.code)
        self.assertNotIn("[ERROR] ", before.split("RP-2")[1].split("\n")[0] if "RP-2" in before else "")
        at.date_input[0].set_value(date.today() - timedelta(days=30)).run()
        text = "\n".join(c.value for c in at.code)
        self.assertRegex(text, r"RP-2.*\[ERROR\].*needs freeze exception")
        self.assertEqual(len(self.jqls), 2)  # scope + not-relevant, no refetch on date change
        self.assert_no_writes()

    def test_page8_no_manual_input_when_page_has_freeze_date(self):
        page = load("release_plan/confluence_page_999_v22.json")
        at = self.run_page("rr8", "999.0.0", env=SANDBOX_ENV, page=page)
        self.assertEqual(len(at.date_input), 0)
        self.assertTrue(any(c.value.startswith("Freeze date (from the Release Plan page)") for c in at.caption))
        self.assert_no_writes()


class CriticalPageTests(PagesCase):
    def test_critical_table_first_and_non_critical_excluded(self):
        at = self.run_page("rr4", "35.0.0")
        first = at.dataframe[0].value
        self.assertEqual(list(first.columns), ["Issue", "Summary", "Assignee", "Reasons"])
        self.assertIn("RP-2", list(first["Issue"]))
        self.assertNotIn("RP-1", list(first["Issue"]))
        self.assertEqual(len(at.expander), 1)
        self.assertEqual(at.expander[0].label, "Other in-scope issues")
        self.assertFalse(at.expander[0].proto.expanded)
        self.assertIn("RP-1", list(at.dataframe[1].value["Issue"]))
        self.assertTrue(any(c.value.startswith("Checked at ") for c in at.caption))
        self.assertEqual(len(self.jqls), 1)
        self.assert_no_writes()

    def test_multi_reason_row(self):
        issues = load("release_readiness/issues.json")
        f = issues["issues"][0]["fields"]
        t = f["customfield_25263"]
        t = t.replace("|Critical modification|No|", "|Critical modification|Yes|")
        t = t.replace("|Downtime required|No|", "|Downtime required|Yes|")
        t = t.replace("|Tested in PRE|Yes|", "|Tested in PRE|No|")
        t = t.replace("|Load test completed|No|", "|Load test completed|Yes|")
        f["customfield_25263"] = t
        at = self.run_page("rr4", "35.0.0", issues=issues)
        df = at.dataframe[0].value
        row = df[df["Issue"] == "RP-1"].iloc[0]
        self.assertEqual(len(row["Reasons"].split("; ")), 3)
        self.assertIn("Critical modification = Yes", row["Reasons"])
        self.assertIn("Downtime required = Yes", row["Reasons"])
        self.assertIn("Tested in PRE = No", row["Reasons"])
        self.assertNotIn("RP-1", list(at.dataframe[1].value["Issue"]))
        self.assert_no_writes()


if __name__ == "__main__":
    unittest.main()
