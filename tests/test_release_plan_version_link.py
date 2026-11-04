"""Release Plan version panel: Jira version link -> X.Y.Z in an editable, shared field."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

PAGE = Path(__file__).resolve().parent.parent / "tools" / "release_plan" / "8_Notifications.py"
ENV = {
    "JIRA_SERVER": "https://jira.example.com/jira", "JIRA_API_TOKEN": "x",
    "CONFLUENCE_SERVER": "https://conf.example.com", "CONFLUENCE_API_TOKEN": "x",
    "RELEASE_PLAN_PARENT_PAGE": "7177194568",
    "JIRA_VERSION_LINK_BASE": "https://jira.example.com/projects/P/versions/",
}


class VersionLinkPanelTests(unittest.TestCase):
    def start(self, fetch):
        for p in (patch.dict(os.environ, ENV, clear=True),
                  patch("dotenv.load_dotenv", lambda *a, **k: False),
                  patch("utils.release_readiness_page._fetch_jira_version", fetch)):
            p.start()
            self.addCleanup(p.stop)
        return AppTest.from_file(str(PAGE), default_timeout=20).run()

    def test_link_prefilled_with_base_and_version_extracted_and_editable(self):
        at = self.start(lambda vid: (200, {"name": "DIGITAL:HUB 35.0.0"}))
        self.assertEqual(at.text_input(key="rr8_version_link").value, ENV["JIRA_VERSION_LINK_BASE"])
        at.text_input(key="rr8_version_link").set_value(ENV["JIRA_VERSION_LINK_BASE"] + "543216").run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(at.text_input(key="rr8_version").value, "35.0.0")
        self.assertEqual(at.session_state["release_plan_version"], "35.0.0")
        # the extracted value can be corrected by hand
        at.text_input(key="rr8_version").set_value("35.1.0").run()
        self.assertEqual(at.session_state["release_plan_version"], "35.1.0")

    def test_bad_link_shows_error_and_keeps_manual_entry(self):
        at = self.start(lambda vid: (404, {}))
        at.text_input(key="rr8_version_link").set_value("https://x/versions/9").run()
        self.assertTrue(any("HTTP 404" in e.value for e in at.error))
        at.text_input(key="rr8_version").set_value("35.0.0").run()
        self.assertEqual(at.session_state["release_plan_version"], "35.0.0")


if __name__ == "__main__":
    unittest.main()

