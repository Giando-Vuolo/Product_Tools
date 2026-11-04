import copy
import json
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from utils import release_checks as rc
from utils import release_plan_helpers as rp
from utils import release_publish as rpub

FIX = Path(__file__).parent / "fixtures" / "release_publish"
PARENT = "7177194568"
KW = dict(version="999.0.0", source_version="35.0.0", label="DIGITAL:HUB", parent_id=PARENT)
NOW = datetime(2026, 10, 26, 12, 30, 5)
PID = rp.SANDBOX_WRITE_PAGE_ID


def load(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def summ(sem="GREEN", e=0, w=0, i=0):
    return {"semaphore": sem, "counts": {"ERROR": e, "WARN": w, "INFO": i}, "per_owner": {}}


ROW = rc.CriticalRow("RECALLTWO-1", 'Fix <b> & "x"', None, ("Critical modification = Yes", "a<b"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backup_dir = Path(self.tmp.name)
        p = patch("utils.confluence_helpers.requests")
        self.requests = p.start()
        self.addCleanup(p.stop)

    def run_publish(self, page, kind, fragment, expected=None, reread=None, update=None, get=None, page_id=PID):
        after = reread
        if after is None:
            after = copy.deepcopy(page)
        get = get or Mock(side_effect=[page, after])
        update = update or Mock(return_value={"ok": True})
        res = rpub.publish_splice(
            page_id=page_id, kind=kind, new_fragment=fragment,
            expected_version=page["version"] if expected is None else expected,
            get_page=get, update_page=update, backup_dir=self.backup_dir, now=NOW, **KW)
        return res, get, update


class TestAllowlist(Base):
    def test_refused_ids(self):
        for pid in ("8307791929", "123", "", None, "1234567890"):
            get, update = Mock(), Mock()
            res = rpub.publish_splice(
                page_id=pid, kind="readiness", new_fragment="<p>x</p>", expected_version=22,
                get_page=get, update_page=update, backup_dir=self.backup_dir, **KW)
            self.assertFalse(res["ok"], pid)
            get.assert_not_called()
            update.assert_not_called()
            self.requests.put.assert_not_called()
            self.requests.get.assert_not_called()
            with self.assertRaises(rpub.PublishRefused):
                rpub.assert_publish_allowed(pid)

    def test_allowed(self):
        rpub.assert_publish_allowed(PID)

    def test_plan_splice_refuses_other_pages(self):
        for n in ("page_other_id", "page_real_id"):
            with self.assertRaises(rpub.PublishRefused):
                rpub.plan_splice(load(n), "readiness", "<p>x</p>", **KW)
        self.assertEqual(list(self.backup_dir.iterdir()), [])


class TestLocators(unittest.TestCase):
    def test_critical_span(self):
        s = load("page_999_target")["storage"]
        a, b = rpub.find_critical_span(s)
        self.assertEqual(s[a:b], "<p>TBD</p>")

    def test_critical_span_next_higher_heading(self):
        s = load("page_999_target")["storage"].replace("<h3>Risks</h3><p>r</p>", "")
        a, b = rpub.find_critical_span(s)
        self.assertEqual(s[a:b], "<p>TBD</p>")

    def test_readiness_forms(self):
        s = load("page_999_target")["storage"]
        a, b = rpub.find_readiness_span(s)
        self.assertEqual(s[a:b], "<p>🚦 <strong>Release readiness:</strong> not checked yet</p>")
        plain = json.loads((Path(__file__).parent / "fixtures/release_plan/confluence_page_999_v22.json").read_text(encoding="utf-8"))["storage"]
        a, b = rpub.find_readiness_span(plain)
        self.assertEqual(plain[a:b], "<p>Release readiness: not checked yet</p>")

    def test_missing_and_duplicates(self):
        with self.assertRaises(rpub.PublishRefused):
            rpub.find_critical_span(load("page_999_no_critical")["storage"])
        with self.assertRaises(rpub.PublishRefused):
            rpub.find_critical_span(load("page_999_dup_critical")["storage"])
        with self.assertRaises(rpub.PublishRefused):
            rpub.find_readiness_span(load("page_999_dup_readiness")["storage"])
        with self.assertRaises(rpub.PublishRefused):
            rpub.find_readiness_span("<p>nothing</p>")


class TestRendering(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(rpub.render_critical_table([], "https://j"), rpub.NONE_PARAGRAPH)

    def test_table_escaping_and_links(self):
        out = rpub.render_critical_table([ROW], "https://jira.example/")
        rp.assert_well_formed(out)
        self.assertIn('<a href="https://jira.example/browse/RECALLTWO-1">RECALLTWO-1</a>', out)
        self.assertIn("Fix &lt;b&gt; &amp; &quot;x&quot;", out)
        self.assertIn("<td>Unassigned</td>", out)
        self.assertIn("Critical modification = Yes; a&lt;b", out)
        self.assertNotIn("<b>", out)

    def test_readiness_strings(self):
        self.assertEqual(
            rpub.render_readiness_line(summ("RED", 2, 3, 4), "2026-10-26 12:30:05"),
            "<p>🚦 <strong>Release readiness:</strong> 🔴 RED — 2 errors · 3 warnings · 4 info — checked 2026-10-26 12:30</p>")
        self.assertIn("🟠 AMBER — 0 errors · 1 warnings · 0 info", rpub.render_readiness_line(summ("AMBER", 0, 1, 0), "2026-10-26 12:30:05"))
        self.assertIn("🟢 GREEN — 0 errors", rpub.render_readiness_line(summ(), "2026-10-26 12:30:05"))


class TestSplice(unittest.TestCase):
    def test_span_only_critical(self):
        page = load("page_999_target")
        frag = rpub.render_critical_table([ROW], "https://j")
        plan = rpub.plan_splice(page, "critical", frag, **KW)
        old = page["storage"]
        self.assertTrue(plan.changed)
        self.assertEqual(plan.new_storage, old[:plan.start] + frag + old[plan.end:])
        self.assertEqual(re.findall(r"<h[1-6].*?</h[1-6]>", old), re.findall(r"<h[1-6].*?</h[1-6]>", plan.new_storage))
        self.assertIn('data-nh-numbering="2.1.2"', plan.new_storage)
        pa = lambda s: s[s.index("<h3>3.3"):s.index("<h3>3.4")]
        self.assertEqual(pa(old), pa(plan.new_storage))

    def test_span_only_readiness(self):
        page = load("page_999_target")
        frag = rpub.render_readiness_line(summ(), "2026-10-26 12:30:05")
        plan = rpub.plan_splice(page, "readiness", frag, **KW)
        self.assertEqual(plan.old_fragment, "<p>🚦 <strong>Release readiness:</strong> not checked yet</p>")
        self.assertEqual(plan.new_storage.replace(frag, plan.old_fragment), page["storage"])

    def test_guard_failure(self):
        with self.assertRaises(rpub.PublishRefused):
            rpub.plan_splice(load("page_999_target"), "readiness", "<p>x</p>", **{**KW, "version": "40.0.0", "source_version": "40.0.0"})

    def test_malformed_fragment_refused(self):
        with self.assertRaises(rpub.PublishRefused):
            rpub.plan_splice(load("page_999_target"), "readiness", "<p>x", **KW)

    def test_heading_injection_refused(self):
        with self.assertRaises(rpub.PublishRefused):
            rpub.plan_splice(load("page_999_target"), "critical", "<h2>evil</h2>", **KW)


class TestPublish(Base):
    def test_write_path(self):
        page = load("page_999_target")
        frag = rpub.render_critical_table([ROW], "https://j")
        plan = rpub.plan_splice(page, "critical", frag, **KW)
        after = {**page, "version": 23, "storage": plan.new_storage}
        seen = {}

        def upd(pid, title, ver, storage):
            seen["backups"] = list(self.backup_dir.iterdir())
            seen["content"] = seen["backups"][0].read_text(encoding="utf-8")
            return {"ok": True}

        update = Mock(side_effect=upd)
        res, get, _ = self.run_publish(page, "critical", frag, reread=after, update=update)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["status"], "published")
        self.assertEqual(len(seen["backups"]), 1)
        self.assertEqual(seen["content"], page["storage"])
        self.assertEqual(update.call_args.args, (PID, page["title"], 23, plan.new_storage))
        self.assertEqual(res["backup"], str(seen["backups"][0]))
        self.assertTrue(seen["backups"][0].name.startswith(f"{PID}_v22_critical_20261026-123005"))
        self.requests.put.assert_not_called()

    def test_tampered_reread(self):
        page = load("page_999_target")
        frag = rpub.render_readiness_line(summ(), "2026-10-26 12:30")
        plan = rpub.plan_splice(page, "readiness", frag, **KW)
        for bad in (
            {**page, "version": 23, "storage": plan.new_storage + "<p>extra</p>"},
            {**page, "version": 22, "storage": plan.new_storage},
            {**page, "version": 23, "title": "Other", "storage": plan.new_storage},
            {**page, "version": 23, "storage": plan.new_storage.replace("<h2>3.", "<h2>X3.")},
        ):
            res, _, update = self.run_publish(page, "readiness", frag, reread=bad)
            self.assertFalse(res["ok"])
            self.assertIn("Verification failed", res["error"])
            self.assertTrue(Path(res["backup"]).exists())
            update.assert_called_once()

    def test_update_error_keeps_backup(self):
        page = load("page_999_target")
        res, _, _ = self.run_publish(page, "readiness", rpub.render_readiness_line(summ(), "2026-10-26 12:30"),
                                     update=Mock(return_value={"error": "boom"}))
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "boom")
        self.assertTrue(Path(res["backup"]).exists())

    def test_idempotent(self):
        page = load("page_999_target")
        frag = rpub.render_readiness_line(summ(), "2026-10-26 12:30")
        plan = rpub.plan_splice(page, "readiness", frag, **KW)
        again = {**page, "version": 23, "storage": plan.new_storage}
        update = Mock()
        res = rpub.publish_splice(page_id=PID, kind="readiness", new_fragment=frag, expected_version=23,
                                  get_page=Mock(return_value=again), update_page=update,
                                  backup_dir=self.backup_dir, now=NOW, **KW)
        self.assertEqual((res["ok"], res["status"], res["backup"]), (True, "unchanged", None))
        update.assert_not_called()
        self.assertEqual(list(self.backup_dir.iterdir()), [])

    def test_stale_preview(self):
        page = load("page_999_target")
        res, _, update = self.run_publish(page, "readiness", "<p>x</p>", expected=21)
        self.assertFalse(res["ok"])
        self.assertIn("changed since preview", res["error"])
        update.assert_not_called()
        self.assertEqual(list(self.backup_dir.iterdir()), [])

    def test_anchor_problems_zero_puts(self):
        for name, kind in (("page_999_no_critical", "critical"), ("page_999_dup_critical", "critical"),
                           ("page_999_dup_readiness", "readiness")):
            res, _, update = self.run_publish(load(name), kind, "<p>x</p>")
            self.assertFalse(res["ok"], name)
            update.assert_not_called()
        self.assertEqual(list(self.backup_dir.iterdir()), [])

    def test_guard_failure_no_put(self):
        page = load("page_999_target")
        page["parent_id"] = "1"
        page["ancestor_ids"] = ["1"]
        res, _, update = self.run_publish(page, "readiness", "<p>x</p>")
        self.assertFalse(res["ok"])
        update.assert_not_called()

    def test_result_keys(self):
        res, _, _ = self.run_publish(load("page_999_target"), "readiness", "<p>x</p>", expected=1)
        for k in ("ok", "status", "error", "backup"):
            self.assertIn(k, res)


if __name__ == "__main__":
    unittest.main()
