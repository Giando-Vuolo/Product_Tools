"""SBOM Inventory findings per severity (utils/sbom_helpers)."""
import os
import unittest
from unittest import mock

from utils import sbom_helpers as sh

PAYLOAD = {"apps": [
    {"guid": "other", "cve_rating": {"critical": 9}},
    {"guid": "a1", "cve_rating": {"low": 82, "none": 0, "critical": 280, "medium": 812, "info": 0, "high": 886}},
]}
ENV = {"SBOM_SERVER": "https://sbom.test", "SBOM_API_KEY": "k", "SBOM_API_SECRET": "s",
       "SBOM_NAMESPACE_ID": "ns", "SBOM_APP_ID": "a1"}


class FindingsBySeverityTests(unittest.TestCase):
    def test_orders_from_most_to_least_severe(self):
        self.assertEqual(sh.findings_by_severity(PAYLOAD, "a1"),
                         {"critical": 280, "high": 886, "medium": 812, "low": 82, "info": 0, "none": 0})

    def test_missing_categories_are_zero_and_unknown_ones_kept_last(self):
        payload = {"apps": [{"guid": "a1", "cve_rating": {"high": 3, "unrated": 2}}]}
        by_severity = sh.findings_by_severity(payload, "a1")
        self.assertEqual(by_severity["critical"], 0)
        self.assertEqual(list(by_severity)[-1], "unrated")
        self.assertEqual(sum(by_severity.values()), sh.count_findings(payload, "a1"))

    def test_breakdown_skips_empty_categories(self):
        self.assertEqual(sh.format_severity_breakdown(sh.findings_by_severity(PAYLOAD, "a1")),
                         "Critical 280 · High 886 · Medium 812 · Low 82")

    def test_fetch_total_matches_sum_of_categories(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = PAYLOAD
        with mock.patch.dict(os.environ, ENV), mock.patch.object(sh.requests, "get", return_value=resp):
            self.assertEqual(sh.fetch_dependency_findings_by_severity()["critical"], 280)
            self.assertEqual(sh.fetch_dependency_findings(), 2060)


def cves_response(data, next_cursor=None):
    resp = mock.Mock(status_code=200)
    resp.json.return_value = {"data": data, "next": next_cursor}
    return resp


def cve(severity, *stages):
    return {"cve_id": "CVE-1", "severity": severity, "component_ref": "backend", "stages": list(stages)}


class FindingsByStageTests(unittest.TestCase):
    def test_counts_per_stage_and_severity_across_pages(self):
        pages = [
            cves_response([cve("CRITICAL", "prod", "prelive"), cve("HIGH", "prod"), cve("LOW", "dev")], "page2"),
            cves_response([cve("HIGH", {"name": "recall2-PRELIVE", "status": "ACTIVE", "is_prod_stage": False})]),
        ]
        with mock.patch.dict(os.environ, ENV), mock.patch.object(sh.requests, "get", side_effect=pages) as get:
            by_stage = sh.fetch_findings_by_stage()
        self.assertEqual(get.call_args_list[0].args, ("https://sbom.test/ns/ns/apps/a1/cves",))
        self.assertEqual(get.call_args_list[1].kwargs["params"], {"next": "page2"})
        self.assertEqual(by_stage["stages"], {
            "PROD": {"critical": 1, "high": 1, "medium": 0, "low": 0},
            "PRELIVE": {"critical": 1, "high": 1, "medium": 0, "low": 0},
        })
        self.assertEqual(sh.format_stage_breakdown(by_stage),
                         "PROD: Critical 1 · High 1 · Medium 0 · Low 0  \nPRELIVE: Critical 1 · High 1 · Medium 0 · Low 0")

    def test_missing_stage_lists_the_stages_found(self):
        with mock.patch.dict(os.environ, ENV), \
                mock.patch.object(sh.requests, "get", return_value=cves_response([cve("HIGH", "production")])):
            text = sh.format_stage_breakdown(sh.fetch_findings_by_stage())
        self.assertIn("PROD: stage not found", text)
        self.assertTrue(text.endswith("Stages in SBOM: production"))

    def test_configured_stages_and_errors(self):
        with mock.patch.dict(os.environ, {**ENV, "SBOM_STAGES": "production"}), \
                mock.patch.object(sh.requests, "get", return_value=cves_response([cve("MEDIUM", "production")])):
            self.assertEqual(sh.fetch_findings_by_stage()["stages"]["production"]["medium"], 1)
        with mock.patch.dict(os.environ, ENV), mock.patch.object(sh.requests, "get", return_value=mock.Mock(status_code=403)):
            with self.assertRaisesRegex(Exception, "HTTP 403"):
                sh.fetch_findings_by_stage()


if __name__ == "__main__":
    unittest.main()
