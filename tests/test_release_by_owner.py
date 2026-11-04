"""Iter 1: by-owner grouping (pure) using hand-built findings and the readiness fixtures."""
import dataclasses
import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import release_checks as rc  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "release_readiness"


def F(rule, sev, key, reason, who, summary=""):
    return rc.Finding(rule, sev, key, reason, who, summary or f"S {key}")


def I(key, status="In Progress"):
    return rc.Issue(key=key, status=status)


class GroupTests(unittest.TestCase):
    def setUp(self):
        self.results = {
            "Approval": [F("Approval", rc.WARN, "A-2", "no approval", "Bob"),
                         F("Approval", rc.ERROR, "A-1", "late", "Bob"),
                         F("Approval", rc.INFO, "A-3", "fyi", "ann")],
            "Documentation table": [F("Documentation table", rc.INFO, "A-2", "minor", "Bob"),
                                    F("Documentation table", rc.ERROR, "A-1", "rows missing", "Bob"),
                                    F("Documentation table", rc.ERROR, "A-1", "rows missing", "Bob")],
            "Unassigned": [F("Unassigned", rc.ERROR, "U-1", "No assignee", None)],
            "Critical changes": [rc.CriticalRow("A-1", "x", "Bob", ("r",))],
        }
        self.issues = [I("A-1", "Done"), I("A-2"), I("A-3"), I("U-1", "Open")]

    def test_one_row_per_issue_with_max_severity_and_status(self):
        g = {x.owner: x for x in rc.group_by_owner(self.results, self.issues)}
        bob = g["Bob"]
        self.assertEqual([i.key for i in bob.issues], ["A-1", "A-2"])
        self.assertEqual([i.max_severity for i in bob.issues], ["ERROR", "WARN"])
        self.assertEqual(bob.issues[0].status, "Done")
        self.assertEqual(bob.issues[0].problems, (("Approval", "late"), ("Documentation table", "rows missing")))
        self.assertEqual(bob.counts, {"ERROR": 1, "WARN": 1, "INFO": 0})

    def test_info_hidden_and_shown(self):
        shown = rc.group_by_owner(self.results, self.issues, include_info=True)
        hidden = rc.group_by_owner(self.results, self.issues, include_info=False)
        bob_s = [x for x in shown if x.owner == "Bob"][0]
        bob_h = [x for x in hidden if x.owner == "Bob"][0]
        self.assertIn(("Documentation table", "minor"), bob_s.issues[1].problems)
        self.assertEqual(bob_h.issues[1].problems, (("Approval", "no approval"),))

    def test_info_only_issue_hidden_by_default_flag(self):
        self.assertIn("ann", rc.owner_names(rc.group_by_owner(self.results, self.issues)))
        self.assertNotIn("ann", rc.owner_names(rc.group_by_owner(self.results, self.issues, include_info=False)))

    def test_unassigned_and_sort_orders(self):
        names = rc.owner_names(rc.group_by_owner(self.results, self.issues))
        self.assertEqual(names, ["ann", "Bob", "Unassigned"])
        r = {"x": [F("R", rc.WARN, "K-2", "a", "Z"), F("R", rc.ERROR, "K-9", "a", "Z"),
                   F("R", rc.ERROR, "K-1", "a", "Z")]}
        self.assertEqual([i.key for i in rc.group_by_owner(r, [])[0].issues], ["K-1", "K-9", "K-2"])
        self.assertEqual(rc.group_by_owner(r, [])[0].issues[0].status, "")

    def test_empty(self):
        self.assertEqual(rc.group_by_owner({}, []), [])
        self.assertEqual(rc.group_by_owner({"Critical changes": []}, [], include_info=False), [])

    def test_messages_exact(self):
        groups = {x.owner: x for x in rc.group_by_owner(self.results, self.issues)}
        self.assertEqual(
            rc.owner_message(groups["Bob"], "35.0.0"),
            "Hi Bob, for release 35.0.0 you have 2 issues to review:\n"
            "- A-1 (ERROR): Approval: late; Documentation table: rows missing\n"
            "- A-2 (WARN): Approval: no approval; Documentation table: minor")
        self.assertEqual(
            rc.owner_message(groups["Unassigned"], "35.0.0"),
            "Hi [~UGN44UN] [~FC0KEWC] [~APMKRYI], for release 35.0.0 you have 1 unassigned issues to review:\n"
            "- U-1 (ERROR): Unassigned: No assignee")
        self.assertEqual(rc.owner_message(rc.OwnerGroup("x", (), {}), "1.0.0"), "")

    def test_summary_has_no_mentions(self):
        groups = rc.group_by_owner(self.results, self.issues)
        s = rc.owners_summary(groups, "35.0.0")
        self.assertEqual(s, "Release 35.0.0 - issues to review per owner:\n"
                            "ann: 1 issues (0 ERROR, 0 WARN, 1 INFO)\n"
                            "Bob: 2 issues (1 ERROR, 1 WARN, 0 INFO)\n"
                            "Unassigned: 1 issues (1 ERROR, 0 WARN, 0 INFO)")
        self.assertNotIn("[~", s)
        for g in groups:
            self.assertEqual("[~" in rc.owner_message(g, "1"), g.owner == rc.UNASSIGNED_OWNER)

    def test_fixture_end_to_end(self):
        raw = json.loads((FIX / "issues.json").read_text())["issues"]
        issues = [rc.issue_from_jira(r) for r in raw]
        results = rc.run_all(issues, date(2000, 1, 1), date(2030, 1, 1))
        groups = rc.group_by_owner(results, issues)
        total = {f.issue_key for v in results.values() for f in v if isinstance(f, rc.Finding)}
        self.assertEqual(sum(len(g.issues) for g in groups), len(total))
        for g in groups:
            self.assertEqual(sum(g.counts.values()), len(g.issues))

    def test_purity(self):
        before = json.dumps({k: [dataclasses.asdict(f) for f in v if isinstance(f, rc.Finding)]
                             for k, v in self.results.items()})
        groups = rc.group_by_owner(self.results, self.issues)
        after = json.dumps({k: [dataclasses.asdict(f) for f in v if isinstance(f, rc.Finding)]
                            for k, v in self.results.items()})
        self.assertEqual(before, after)
        self.assertEqual(groups, rc.group_by_owner(self.results, self.issues))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            groups[0].owner = "x"
        self.assertIsInstance(groups[0].issues, tuple)
        self.assertIsInstance(groups[0].issues[0].problems, tuple)


if __name__ == "__main__":
    unittest.main()
