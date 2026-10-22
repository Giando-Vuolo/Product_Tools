import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from utils import release_plan_helpers as rp

FIX = Path(__file__).parent / "fixtures" / "release_plan"
JIRA = "https://jira.example.com/jira"
PARENT = "7177194568"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class SandboxConfigTests(unittest.TestCase):
    def test_load_and_resolve(self):
        cfg = rp.load_sandbox_config({"RELEASE_PLAN_SANDBOX_MAP": "999.0.0:35.0.0"})
        self.assertEqual(rp.resolve_source_version("999.0.0", cfg), ("35.0.0", True))
        self.assertEqual(rp.resolve_source_version("35.0.0", cfg), ("35.0.0", False))

    def test_empty_and_invalid(self):
        self.assertEqual(rp.load_sandbox_config({}).mapping, ())
        self.assertEqual(rp.resolve_source_version("1.0.0", rp.load_sandbox_config({})), ("1.0.0", False))
        for bad in ("999.0.0", "a:b", "999.0.0:35"):
            with self.assertRaises(ValueError):
                rp.load_sandbox_config({"RELEASE_PLAN_SANDBOX_MAP": bad})


class WriteAllowListTests(unittest.TestCase):
    def test_sandbox_allows_only_999_page(self):
        rp.check_write_allowed("7570725597", is_sandbox=True)
        for pid in ("8307791929", "8307795718", "1", ""):
            with self.assertRaises(PermissionError):
                rp.check_write_allowed(pid, is_sandbox=True)

    def test_template_always_blocked(self):
        with self.assertRaises(PermissionError):
            rp.check_write_allowed("8307791929", is_sandbox=False)

    def test_jira_blocked_in_sandbox(self):
        with self.assertRaises(PermissionError):
            rp.check_write_allowed("", is_sandbox=True, target="jira")
        with self.assertRaises(PermissionError):
            rp.check_write_allowed("", is_sandbox=False, target="other")

    def test_non_sandbox_regular_page_allowed(self):
        rp.check_write_allowed("8307795718", is_sandbox=False)


class PublishSandboxTests(unittest.TestCase):
    ACT = rp.PostAction("K-1", "One", "Ann", "description")

    def _publish(self, page, **kw):
        update = Mock(return_value={"ok": True})
        res = rp.publish(lambda: page, update, [self.ACT], kw.pop("version", "999.0.0"),
                         rp.DEFAULT_FIX_VERSION_LABEL, JIRA, PARENT, **kw)
        return res, update

    def test_explicit_sandbox_writes_999_page(self):
        with patch.dict(os.environ, {"RELEASE_PLAN_SANDBOX_MAP": "999.0.0:35.0.0"}):
            res, update = self._publish(load("confluence_page_999_v22.json"), is_sandbox=True)
        self.assertTrue(res["ok"], res)
        self.assertEqual(update.call_args.args[0], "7570725597")
        self.assertEqual(update.call_args.args[2], 23)

    def test_auto_sandbox_from_env_map(self):
        with patch.dict(os.environ, {"RELEASE_PLAN_SANDBOX_MAP": "999.0.0:35.0.0"}):
            res, update = self._publish(load("confluence_page_999_v22.json"))
        self.assertTrue(res["ok"], res)
        update.assert_called_once()

    def test_sandbox_blocks_other_page(self):
        page = dict(load("confluence_page_35.json"))
        with patch.dict(os.environ, {"RELEASE_PLAN_SANDBOX_MAP": "35.0.0:35.0.0"}):
            res, update = self._publish(page, version="35.0.0", is_sandbox=True)
        self.assertFalse(res["ok"])
        self.assertIn("Sandbox", res["error"])
        update.assert_not_called()

    def test_template_blocked_even_if_guard_bypassed(self):
        with patch.object(rp, "check_target_guard", return_value=rp.GuardResult(True, [], "8307791929", "T")):
            res, update = self._publish(load("confluence_page_35.json"), version="35.0.0", is_sandbox=False)
        self.assertFalse(res["ok"])
        update.assert_not_called()

    def test_non_sandbox_unchanged(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RELEASE_PLAN_SANDBOX_MAP", None)
            res, update = self._publish(load("confluence_page_35.json"), version="35.0.0")
        self.assertTrue(res["ok"])
        update.assert_called_once()

    def test_999_page_rejected_without_sandbox(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RELEASE_PLAN_SANDBOX_MAP", None)
            res, update = self._publish(load("confluence_page_999_v22.json"))
        self.assertFalse(res["ok"])
        update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
