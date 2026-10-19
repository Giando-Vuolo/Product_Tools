"""RF13-RF15: page order (no Jira before page/guard) and executed UI tests (AppTest, no real HTTP)."""
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

from utils import release_plan_helpers as rp  # noqa: E402

PAGE = str(ROOT / "tools" / "7_Release_Plan.py")
FIX = ROOT / "tests" / "fixtures" / "release_plan"
PARENT = "7177194568"
ENV = {
    "JIRA_SERVER": "https://jira.example.com/jira",
    "JIRA_API_TOKEN": "x",
    "CONFLUENCE_SERVER": "https://conf.example.com",
    "CONFLUENCE_API_TOKEN": "x",
    "RELEASE_PLAN_PARENT_PAGE": PARENT,
}
MISSING_400 = ("Jira API returned 400: {\"errorMessages\":[\"The value 'DIGITAL:HUB 999.0.0' does not exist "
               "for the field 'fixVersion'.\"],\"errors\":{}}")
ISSUE = {"key": "RECALLTWO-1", "fields": {"description": "POST-ACTION: restart batch",
                                          "reporter": {"displayName": "Alice"}}}
TITLE_35 = "Release Plan 35.0.0"
ID_35 = "8307795718"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class PageCase(unittest.TestCase):
    def run_page(self, version="", click=True, children=None, jira=None, page=None):
        calls = {"jira": 0}

        def fake_jira(*a, **k):
            calls["jira"] += 1
            return jira if jira is not None else {"issues": []}

        page = page if page is not None else load("confluence_page_35.json")
        self.calls = calls
        patches = [
            patch.dict(os.environ, ENV, clear=True),
            patch("dotenv.load_dotenv", lambda *a, **k: False),  # never read .env
            patch("utils.confluence_helpers.list_child_pages",
                  lambda *a, **k: {"results": children if children is not None else []}),
            patch("utils.confluence_helpers.get_confluence_page", lambda *a, **k: page),
            patch("utils.confluence_helpers.update_confluence_page",
                  side_effect=AssertionError("write attempted")),
            patch("utils.jira_helpers.fetch_release_issues_with_comments", fake_jira),
            patch("requests.sessions.Session.request", side_effect=AssertionError("real network attempted")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        at = AppTest.from_file(PAGE, default_timeout=20).run()
        if version:
            at.text_input(key="rp_version").set_value(version).run()
        if click:
            at.button(key="rp_preview_btn").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    @staticmethod
    def errors(at):
        return [e.value for e in at.error]

    @staticmethod
    def texts(at):
        return [m.value for m in at.markdown]


class PageUiTests(PageCase):
    def test_prefix_field_disabled_and_shows_label_version_ac8(self):
        at = self.run_page("35.0.0", click=False)
        field = [t for t in at.text_input if t.label == "fixVersion prefix"][0]
        self.assertTrue(field.disabled)
        self.assertEqual(field.value, "DIGITAL:HUB 35.0.0")

    def test_click_outside_caption_visible_ac9(self):
        at = self.run_page(click=False)
        self.assertIn("Once you finish typing, click outside the field (or press Enter) to update the fixVersion.",
                      [c.value for c in at.caption])

    def test_page_not_found_no_jira_call_rf13(self):
        at = self.run_page("98.0.0", children=[{"id": "1", "title": TITLE_35, "url": ""}])
        self.assertEqual(self.errors(at), [f"Release Plan 98.0.0 not found under parent page {PARENT}."])
        self.assertEqual(self.calls["jira"], 0)

    def test_ambiguous_lists_title_and_id_rf13(self):
        kids = [{"id": "11", "title": TITLE_35, "url": ""}, {"id": "22", "title": TITLE_35, "url": ""}]
        at = self.run_page("35.0.0", children=kids)
        err = self.errors(at)[0]
        self.assertIn(f"'{TITLE_35}' (ID 11)", err)
        self.assertIn(f"'{TITLE_35}' (ID 22)", err)
        self.assertEqual(self.calls["jira"], 0)

    def test_guard_failure_no_jira_call_rf13(self):
        # page fixture holds fixVersion 35.0.0, a matching title for 36.0.0 must fail the guard
        kids = [{"id": ID_35, "title": "Release Plan 36.0.0", "url": ""}]
        at = self.run_page("36.0.0", children=kids)
        self.assertTrue(any("fixVersion mismatch" in e for e in self.errors(at)), self.errors(at))
        self.assertEqual(self.calls["jira"], 0)

    def test_nonexistent_version_message_rf14(self):
        page = load("confluence_page_35.json")
        page["storage"] = page["storage"].replace("35.0.0", "999.0.0")
        page["title"] = "Release Plan 999.0.0"
        kids = [{"id": page["id"], "title": page["title"], "url": "https://conf.example.com/p"}]
        at = self.run_page("999.0.0", children=kids, jira={"error": MISSING_400}, page=page)
        self.assertEqual(self.errors(at), ["Version DIGITAL:HUB 999.0.0 does not exist in Jira. Nothing to extract."])
        self.assertEqual(self.calls["jira"], 1)
        self.assertEqual([b for b in at.button if b.key == "rp_publish_btn"], [])  # publish not offered

    def test_other_jira_error_unchanged(self):
        kids = [{"id": ID_35, "title": TITLE_35, "url": ""}]
        at = self.run_page("35.0.0", children=kids, jira={"error": "Jira API returned 500: boom"})
        self.assertEqual(self.errors(at), ["Jira API returned 500: boom"])

    def test_happy_path_preview_shows_title_id_link_ac10_ac12(self):
        kids = [{"id": ID_35, "title": TITLE_35, "url": "https://conf.example.com/p/35"}]
        at = self.run_page("35.0.0", children=kids, jira={"issues": [ISSUE]})
        self.assertEqual(self.errors(at), [])
        texts = self.texts(at)
        self.assertIn(f"Target page: **{TITLE_35}** (ID {ID_35}) - [open page](https://conf.example.com/p/35)", texts)
        self.assertEqual(sum(t.startswith("Target page:") for t in texts), 1)
        self.assertTrue(any("restart batch" in t for t in texts))
        self.assertEqual(self.calls["jira"], 1)


class MissingVersionDetectionTests(unittest.TestCase):
    def test_detection_rf14(self):
        self.assertTrue(rp.is_missing_fix_version_error(MISSING_400))
        self.assertFalse(rp.is_missing_fix_version_error("Jira API returned 500: boom"))
        self.assertFalse(rp.is_missing_fix_version_error(""))


if __name__ == "__main__":
    unittest.main()
