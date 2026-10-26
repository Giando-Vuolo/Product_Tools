"""Iter 3: publish panel on pages 0 and 4 (fixtures only, no network, backups in a tempdir)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import release_publish as rpub  # noqa: E402

PAGES = ROOT / "tools" / "release_plan"
FIX = ROOT / "tests" / "fixtures"
PARENT = "7177194568"
SANDBOX_ID = "7570725597"
ENV = {
    "JIRA_SERVER": "https://jira.example.com/jira", "JIRA_API_TOKEN": "x",
    "CONFLUENCE_SERVER": "https://conf.example.com", "CONFLUENCE_API_TOKEN": "x",
    "RELEASE_PLAN_PARENT_PAGE": PARENT,
}
SANDBOX_ENV = dict(ENV, RELEASE_PLAN_SANDBOX_MAP="999.0.0:35.0.0")
FILES = {"rr0": "0_Overview.py", "rr4": "4_Critical_Changes.py"}
KIND = {"rr0": "readiness", "rr4": "critical"}


def load(rel):
    return json.loads((FIX / rel).read_text(encoding="utf-8"))


class PublishPagesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.updates = []
        self.gets = []
        self.stored = load("release_publish/page_999_target.json")
        self.children_id = SANDBOX_ID
        self.children_title = "Release Plan 999.0.0"

    def start(self, env):
        def fake_jira(server, token, auth, email, jql, page_size=50, fields=None):
            return load("release_readiness/issues.json")

        def fake_children(*a, **k):
            self.gets.append("children")
            return {"results": [{"id": self.children_id, "title": self.children_title, "url": ""}]}

        def fake_get(server, token, auth, email, pid):
            self.gets.append(pid)
            return dict(self.stored)

        def fake_update(server, token, auth, email, pid, title, ver, storage):
            self.updates.append((pid, title, ver, storage))
            self.stored = dict(self.stored, version=ver, storage=storage)
            return {"ok": True}

        for p in (
            patch.dict(os.environ, env, clear=True),
            patch("dotenv.load_dotenv", lambda *a, **k: False),
            patch("utils.jira_helpers.fetch_release_issues_with_comments", fake_jira),
            patch("utils.confluence_helpers.list_child_pages", fake_children),
            patch("utils.confluence_helpers.get_confluence_page", fake_get),
            patch("utils.confluence_helpers.update_confluence_page", fake_update),
            patch.object(rpub, "BACKUP_DIR", Path(self.tmp.name)),
            patch("requests.sessions.Session.request", side_effect=AssertionError("real network")),
        ):
            p.start()
            self.addCleanup(p.stop)

    def page(self, prefix, version, env):
        self.start(env)
        at = AppTest.from_file(str(PAGES / FILES[prefix]), default_timeout=20).run()
        at.text_input(key=f"{prefix}_version").set_value(version).run()
        at.button(key=f"{prefix}_refresh").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at


class PublishPagesTests(PublishPagesCase):
    def test_load_and_refresh_never_update(self):  # AC10
        for prefix in FILES:
            with self.subTest(prefix):
                self.updates.clear()
                at = self.page(prefix, "999.0.0", SANDBOX_ENV)
                self.assertEqual(self.updates, [])
                self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
                self.assertIn(f"{prefix}_pub_{KIND[prefix]}_preview",
                              [b.key for b in at.button])

    def test_non_sandbox_disabled_no_publish_gets(self):  # AC19
        for prefix in FILES:
            with self.subTest(prefix):
                self.start(ENV)
                at = AppTest.from_file(str(PAGES / FILES[prefix]), default_timeout=20).run()
                at.text_input(key=f"{prefix}_version").set_value("35.0.0").run()
                at.button(key=f"{prefix}_refresh").click().run()
                gets_after_refresh = list(self.gets)
                btn = at.button(key=f"{prefix}_pub_disabled_{KIND[prefix]}")
                self.assertTrue(btn.disabled)
                self.assertTrue(any("only enabled for the sandbox release (page 7570725597)" in c.value
                                    for c in at.caption))
                self.assertEqual(self.gets, gets_after_refresh)
                self.assertEqual(self.updates, [])

    def test_sandbox_preview_confirm_updates_once(self):
        for prefix in FILES:
            with self.subTest(prefix):
                self.updates.clear()
                self.stored = load("release_publish/page_999_target.json")
                at = self.page(prefix, "999.0.0", SANDBOX_ENV)
                kind = KIND[prefix]
                self.assertTrue(at.button(key=f"{prefix}_pub_{kind}_confirm").disabled)
                at.button(key=f"{prefix}_pub_{kind}_preview").click().run()
                self.assertFalse(at.exception)
                self.assertEqual(self.updates, [])
                self.assertEqual(at.session_state[f"{prefix}_pub_{kind}"]["page_id"], SANDBOX_ID)
                confirm = at.button(key=f"{prefix}_pub_{kind}_confirm")
                self.assertFalse(confirm.disabled)
                confirm.click().run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                self.assertEqual([u[0] for u in self.updates], [SANDBOX_ID])
                self.assertEqual(len(at.success), 1)
                self.assertEqual(len(list(Path(self.tmp.name).glob(f"*_{kind}_*.xml"))), 1)

    def test_non_sandbox_page_id_never_reaches_update(self):
        # direct attempt on a real page id
        real = load("release_publish/page_real_id.json")
        res = rpub.publish_splice(
            page_id=real["id"], kind="readiness", new_fragment="<p>x</p>", expected_version=1,
            get_page=lambda pid: real, update_page=lambda *a: self.updates.append(a) or {"ok": True},
            version="999.0.0", source_version="35.0.0", label="HUB", parent_id=PARENT,
            backup_dir=self.tmp.name)
        self.assertEqual(res["status"], "refused")
        # via the page: title resolves to a non-sandbox id
        self.children_id = real["id"]
        at = self.page("rr4", "999.0.0", SANDBOX_ENV)
        at.button(key="rr4_pub_critical_preview").click().run()
        self.assertEqual(len(at.error), 1)
        self.assertNotIn(real["id"], self.gets)  # refused before get_confluence_page
        self.assertEqual(self.updates, [])


if __name__ == "__main__":
    unittest.main()
