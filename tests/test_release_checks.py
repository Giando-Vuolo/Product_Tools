import ast
import json
import unittest
from datetime import date
from pathlib import Path

from utils import release_checks as rc
from utils.release_checks import ERROR, INFO, WARN, DOC_ROWS, Issue

FIX = Path(__file__).parent / "fixtures" / "release_readiness"
PLAN_FIX = Path(__file__).parent / "fixtures" / "release_plan"
TODAY = date(2026, 10, 22)
FV = "DIGITAL:HUB 35.0.0"
MON = "Production Monitoring (How to monitor success in PROD)"


def table(**over):
    vals = {r: "No" for r in DOC_ROWS}
    vals.update({"Tested in PRE": "Yes", "Critical modification": "No", "Schema Changes": "N/A",
                 "Data Regularization Details": "N/A", "Special Deployment Steps": "N/A",
                 "Rollback Method": "Revert", MON: "Dash"})
    vals.update(over)
    return "||Field||Information||\n" + "\n".join(f"|{k}|{v}|" for k, v in vals.items())


def mk(key="K-1", **kw):
    base = dict(summary="s", issuetype="Story", status="In Progress", assignee="Ann", fix_versions=(FV,),
                approval=None, doc_table_raw="", comment_count=0)
    base.update(kw)
    return Issue(key, **base)


class PurityTests(unittest.TestCase):
    def test_no_forbidden_imports_ac1(self):
        tree = ast.parse(Path(rc.__file__).read_text(encoding="utf-8"))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add((n.module or "").split(".")[0])
        self.assertFalse(mods & {"streamlit", "requests", "urllib", "http", "socket", "os", "utils"}, mods)


class ConversionTests(unittest.TestCase):
    def _issues(self):
        raw = json.loads((FIX / "issues.json").read_text())["issues"]
        return [rc.issue_from_jira(r) for r in raw]

    def test_fixture_conversion(self):
        issues = self._issues()
        self.assertEqual(issues[0].approval, "Ready to release")
        self.assertIsNone(issues[4].assignee)
        self.assertEqual(issues[0].fix_versions, (FV,))
        self.assertEqual(len(rc.select_in_scope(issues)), 4)  # excludes sub-task + not relevant

    def test_run_all_on_fixture(self):
        res = rc.run_all(self._issues(), date(2026, 10, 1), TODAY)
        self.assertEqual({f.issue_key for f in res[rc.RULE_PRE]}, {"RP-2"})
        self.assertEqual([f.issue_key for f in res[rc.RULE_SCOPE]], ["RP-4"])
        s = rc.summarize(res)
        self.assertEqual(s["semaphore"], "RED")
        self.assertIn(rc.UNASSIGNED_OWNER, s["per_owner"])
        self.assertNotIn(rc.RULE_UNASSIGNED, rc.notification_texts(res))  # only a Closed issue is unassigned


class ScopeTests(unittest.TestCase):
    def test_scope_ac5(self):
        ok = [mk(issuetype=t) for t in rc.CHECKED_ISSUE_TYPES]
        self.assertEqual(len(rc.select_in_scope(ok + [mk(issuetype="Sub-task"), mk(issuetype="Epic")])), 4)
        self.assertEqual(rc.select_in_scope([mk(fix_versions=("Other 1.0.0",)), mk(fix_versions=())]), [])

    def test_not_relevant_excluded_ac6(self):
        nr = mk(fix_versions=(rc.NOT_RELEVANT_FIX_VERSION,))
        self.assertEqual(rc.select_in_scope([nr]), [])
        self.assertEqual(rc.check_scope([nr]), [])
        self.assertEqual(rc.check_approval([nr], None, TODAY), [])
        nr2 = mk(fix_versions=(rc.NOT_RELEVANT_FIX_VERSION,), assignee=None)
        self.assertEqual(rc.check_unassigned([nr2]), [])

    def test_not_relevant_misclassified_ac6(self):
        nrv = (rc.NOT_RELEVANT_FIX_VERSION,)
        a = mk("A", fix_versions=nrv, approval="Ready to release")
        b = mk("B", fix_versions=nrv, doc_table_raw=table())
        out = rc.check_scope([a, b])
        self.assertEqual([(f.issue_key, f.severity) for f in out], [("A", WARN), ("B", WARN)])
        c = mk("C", fix_versions=nrv, doc_table_raw="||F||I||\n|Tested in PRE|Lorem ipsum|")
        self.assertEqual(rc.check_scope([c]), [])


class FreezeTests(unittest.TestCase):
    def test_extract_from_999_fixture_ac12(self):
        storage = json.loads((PLAN_FIX / "confluence_page_999_v22.json").read_text(encoding="utf-8"))["storage"]
        self.assertEqual(rc.extract_freeze_date(storage), date(2026, 10, 23))

    def test_extract_text_and_case_ac12(self):
        s = "<table><tr><td>FREEZE DATE</td><td>2026-11-02</td></tr></table>"
        self.assertEqual(rc.extract_freeze_date(s), date(2026, 11, 2))
        self.assertEqual(rc.parse_freeze_date("02/11/2026"), date(2026, 11, 2))
        self.assertIsNone(rc.parse_freeze_date("soon"))

    def test_absent_ac13(self):
        self.assertIsNone(rc.extract_freeze_date("<p>Date</p>"))
        self.assertIsNone(rc.freeze_passed(None, TODAY))

    def test_freeze_day_itself_not_passed(self):
        self.assertFalse(rc.freeze_passed(TODAY, TODAY))
        self.assertTrue(rc.freeze_passed(date(2026, 10, 21), TODAY))


class ApprovalTests(unittest.TestCase):
    def test_future_warn_ac7(self):
        f = rc.check_approval([mk()], date(2026, 11, 1), TODAY)
        self.assertEqual([(x.severity, x.issue_key) for x in f], [(WARN, "K-1")])

    def test_passed_error_ac8(self):
        f = rc.check_approval([mk()], date(2026, 10, 1), TODAY)
        self.assertEqual(f[0].severity, ERROR)
        self.assertIn("needs freeze exception", f[0].reason)

    def test_no_date_warn_ac9(self):
        self.assertEqual(rc.check_approval([mk()], None, TODAY)[0].severity, WARN)

    def test_approved_incomplete_error_ac10(self):
        for raw in ("", "||F||I||\n|Tested in PRE|Lorem ipsum|", table(**{"Rollback Method": ""})):
            f = rc.check_approval([mk(approval="Ready to release", doc_table_raw=raw)], None, TODAY)
            self.assertEqual([x.severity for x in f], [ERROR], raw)

    def test_approved_complete_ok(self):
        ok = mk(approval="Ready to release", doc_table_raw=table())
        self.assertEqual(rc.check_approval([ok], None, TODAY), [])

    def test_never_filtered_ac11(self):
        issues = [mk(f"K-{n}", status=s) for n, s in enumerate(("Closed", "Open", "Done", "Acceptance Test"))]
        self.assertEqual(len(rc.check_approval(issues, None, TODAY)), 4)


class DocTableTests(unittest.TestCase):
    def test_parse_messy_ac14(self):
        t = rc.parse_doc_table((FIX / "doc_table_messy.txt").read_text())
        self.assertTrue(t.present)
        self.assertEqual(t.rows["Tested in PRE"], "No - flaky env")
        self.assertEqual(t.rows["E2E Coverage"], "Yes")
        self.assertEqual(t.rows["Rollback Method"], "revert release")
        self.assertIn(MON, t.rows)
        self.assertEqual(len(t.missing_rows), 12)

    def test_parse_full_16_ac14(self):
        t = rc.parse_doc_table(table())
        self.assertEqual((len(t.rows), t.missing_rows), (16, ()))
        self.assertFalse(rc.parse_doc_table("").present)
        self.assertFalse(rc.parse_doc_table("random text").present)

    def test_parse_crlf_and_whitespace(self):
        t = rc.parse_doc_table(table().replace("\n", "\r\n").replace("|No|", "|  No  |"))
        self.assertEqual(t.rows["Downtime required"], "No")

    def test_placeholders(self):
        for v in ("", "Lorem ipsum dolor", "Yes-No-N/A", "tbd", "  TBD "):
            self.assertTrue(rc.is_placeholder(v), v)
        self.assertFalse(rc.is_placeholder("N/A"))

    def test_severity_by_status_ac15(self):
        for status, sev in (("Acceptance Test", ERROR), ("Closed", ERROR), ("In Progress", WARN), ("Weird", WARN)):
            f = rc.check_doc_table([mk(status=status)])
            self.assertEqual([x.severity for x in f], [sev], status)
        raw = table(**{"E2E Coverage": "TBD", "Rollback Method": "Lorem ipsum"})
        f = rc.check_doc_table([mk(status="Done", doc_table_raw=raw)])
        self.assertTrue(f and all(x.severity == ERROR for x in f))
        f = rc.check_doc_table([mk(doc_table_raw="||F||I||\n|Tested in PRE|Yes|")])
        self.assertIn("Missing rows", f[0].reason)

    def test_dependencies_ac16(self):
        f = rc.check_doc_table([mk(doc_table_raw=table(**{"Schema Changes": "Add column", "Rollback Method": "N/A"}))])
        self.assertEqual([x.severity for x in f], [WARN])
        raw = table(**{"Critical modification": "Yes", "Rollback Method": "", MON: ""})
        f = rc.check_doc_table([mk(doc_table_raw=raw)])
        self.assertTrue(all(x.severity == WARN for x in f))
        self.assertGreaterEqual(len(f), 2)
        self.assertEqual(rc.check_doc_table([mk(doc_table_raw=table())]), [])


class PreTests(unittest.TestCase):
    def _run(self, value, comments=0):
        return rc.check_pre_testing([mk(doc_table_raw=table(**{"Tested in PRE": value}), comment_count=comments)])

    def test_bare_no_error_ac17(self):
        self.assertEqual([f.severity for f in self._run("No")], [ERROR])

    def test_explained_in_cell_ac18(self):
        self.assertEqual([f.severity for f in self._run("No - no PRE env for this service")], [INFO])

    def test_explained_in_comments_ac19(self):
        self.assertEqual([f.severity for f in self._run("No - explained in comments", 0)], [ERROR])
        self.assertEqual([f.severity for f in self._run("No - explained in comments", 2)], [INFO])

    def test_comment_flag_both_branches(self):
        self.assertEqual([f.severity for f in self._run("No", 1)], [INFO])
        old = rc.PRE_COMMENT_COUNTS_AS_EXPLANATION
        rc.PRE_COMMENT_COUNTS_AS_EXPLANATION = False
        try:
            self.assertEqual([f.severity for f in self._run("No", 1)], [ERROR])
        finally:
            rc.PRE_COMMENT_COUNTS_AS_EXPLANATION = old

    def test_yes_na_missing_not_listed(self):
        self.assertEqual(self._run("Yes"), [])
        self.assertEqual(self._run("N/A"), [])
        self.assertEqual(rc.check_pre_testing([mk()]), [])


class UnassignedTests(unittest.TestCase):
    def test_ac20(self):
        f = rc.check_unassigned([mk("A", assignee=None), mk("B", assignee=None, status="Closed"), mk("C")])
        self.assertEqual([(x.issue_key, x.severity) for x in f], [("A", ERROR), ("B", INFO)])
        self.assertEqual(rc.check_unassigned([mk(assignee=None, status="Closed (old)")])[0].severity, ERROR)


class CriticalTests(unittest.TestCase):
    def _crit(self, **over):
        return rc.find_critical_changes([mk(doc_table_raw=table(**over))])

    def test_each_trigger_ac21(self):
        cases = {
            "Critical modification": "Yes", "Downtime required": "Yes", "Schema Changes": "Add column",
            "Data Regularization Details": "Script X", "Special Deployment Steps": "Run Y",
            "Config Server Modifications": "Yes", "Tested in PRE": "No",
        }
        for k, v in cases.items():
            self.assertEqual(len(self._crit(**{k: v})), 1, k)

    def test_load_test_only_with_critical_ac21(self):
        self.assertEqual(self._crit(**{"Load test completed": "No"}), [])
        rows = self._crit(**{"Load test completed": "No", "Critical modification": "Yes"})
        self.assertEqual(len(rows[0].reasons), 2)

    def test_multi_reason_ac22(self):
        rows = self._crit(**{"Downtime required": "Yes", "Config Server Modifications": "Yes", "Schema Changes": "DDL"})
        self.assertEqual(len(rows[0].reasons), 3)

    def test_non_matching_and_placeholders_ac24(self):
        self.assertEqual(self._crit(), [])
        self.assertEqual(self._crit(**{"Critical modification": "Lorem ipsum", "Downtime required": "Yes-No-N/A",
                                       "Schema Changes": "TBD", "Special Deployment Steps": ""}), [])
        self.assertEqual(rc.find_critical_changes([mk()]), [])
        nr = mk(fix_versions=(rc.NOT_RELEVANT_FIX_VERSION,), doc_table_raw=table(**{"Downtime required": "Yes"}))
        self.assertEqual(rc.find_critical_changes([nr]), [])


class SummaryTests(unittest.TestCase):
    def test_semaphore_and_texts(self):
        res = rc.run_all([mk(assignee=None)], None, TODAY)
        s = rc.summarize(res)
        self.assertEqual(s["semaphore"], "RED")
        self.assertEqual(s["per_owner"][rc.UNASSIGNED_OWNER][ERROR], 1)
        text = rc.notification_texts(res)[rc.RULE_UNASSIGNED]
        for m in ("[~UGN44UN]", "[~FC0KEWC]", "[~APMKRYI]"):
            self.assertIn(m, text)
        self.assertEqual(rc.summarize({})["semaphore"], "GREEN")

    def test_status_order(self):
        self.assertTrue(rc.is_late_status("Acceptance Test"))
        self.assertTrue(rc.is_late_status("Closed"))
        self.assertFalse(rc.is_late_status("In Progress"))
        self.assertFalse(rc.is_late_status("???"))


class FieldsParamTests(unittest.TestCase):
    def test_default_and_override_fields(self):
        from unittest.mock import Mock, patch
        from utils.jira_helpers import RELEASE_READINESS_FIELDS, fetch_release_issues_with_comments
        r = Mock(status_code=200)
        r.json.return_value = {"issues": [], "total": 0}
        with patch("utils.jira_helpers.requests.get", return_value=r) as get:
            fetch_release_issues_with_comments("https://j", "t", "x", "", "jql")
            fetch_release_issues_with_comments("https://j", "t", "x", "", "jql", fields=RELEASE_READINESS_FIELDS)
        self.assertEqual(get.call_args_list[0].kwargs["params"]["fields"],
                         "summary,description,reporter,comment,status,issuetype")
        self.assertIn("customfield_25263", get.call_args_list[1].kwargs["params"]["fields"])


if __name__ == "__main__":
    unittest.main()
