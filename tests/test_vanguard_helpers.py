import os
import unittest
from unittest.mock import Mock, patch

import requests

from utils.vanguard_helpers import (fetch_platform_findings, fetch_platform_findings_summary, format_platform_breakdown,
                                    vanguard_configured)


PROJECT = "11111111-1111-4111-8111-111111111111"
CONFIG = {
    "VANGUARD_PROJECT_ID": PROJECT,
    "VANGUARD_CLIENT_ID": "test-client",
    "VANGUARD_CLIENT_SECRET": "test-secret",
}


def response(payload, status=200):
    return Mock(status_code=status, json=Mock(return_value=payload))


PROJECT_URL = f"https://api.your-company.com/projects/{PROJECT}"
ACCOUNTS = {"accounts": [{"id": "acc-pro", "name": "recall2-PROD"}, {"id": "acc-pre", "name": "recall2-PRELIVE"},
                         {"id": "acc-dev", "name": "recall2-DEV"}]}


def finding(identifier, account="acc-pro", **fields):
    return {"id": identifier, "state": "open", "reference": {"account_guid": account}, **fields}


class VanguardTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {**CONFIG, "VANGUARD_AUTH_URL": "", "VANGUARD_API_URL": ""})
        self.post = patch("utils.vanguard_helpers.requests.post", return_value=response({"access_token": "test-token"}))
        self.get = patch("utils.vanguard_helpers.requests.get")
        self.env.start()
        self.auth = self.post.start()
        self.read = self.get.start()
        self.addCleanup(patch.stopall)
        # The project query (account names) answers with ACCOUNTS; findings queries take self.pages in order
        self.project, self.pages = response(ACCOUNTS), []
        self.read.side_effect = lambda url, **kwargs: (
            self.project if url.rstrip("/").endswith(PROJECT) else self.pages.pop(0))

    def findings_calls(self):
        return [call for call in self.read.call_args_list if call.args[0].endswith("/findings")]

    def test_all_pages_unique_findings_and_read_only_endpoints(self):
        self.pages = [
            response({"findings": [finding("a"), finding("b")], "last_key": "page2"}),
            response({"findings": [finding("b"), finding("c")]}),
        ]
        self.assertEqual(fetch_platform_findings(), 3)
        self.auth.assert_called_once_with(
            "https://auth.api.your-company.com/oauth2/token",
            data={"grant_type": "client_credentials", "client_id": "test-client", "client_secret": "test-secret"},
            timeout=30, allow_redirects=False,
        )
        self.assertEqual(self.read.call_args_list[0].args, (PROJECT_URL,))
        calls = self.findings_calls()
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(call.args, (f"{PROJECT_URL}/findings",))
            self.assertEqual(call.kwargs["params"]["state"], "open")
            self.assertEqual(call.kwargs["params"]["preview"], "false")
            self.assertEqual(call.kwargs["params"]["page_size"], 100)
            self.assertFalse(call.kwargs["allow_redirects"])
        self.assertNotIn("last_key", calls[0].kwargs["params"])
        self.assertEqual(calls[1].kwargs["params"]["last_key"], "page2")

    def test_endpoints_come_from_configuration(self):
        urls = {"VANGUARD_AUTH_URL": "https://auth.example.test/oauth2/token", "VANGUARD_API_URL": "https://api.example.test/"}
        self.pages = [response({"findings": []})]
        with patch.dict(os.environ, urls):
            fetch_platform_findings()
        self.assertEqual(self.auth.call_args.args, ("https://auth.example.test/oauth2/token",))
        self.assertEqual(self.read.call_args_list[0].args, (f"https://api.example.test/projects/{PROJECT}",))
        self.assertEqual(self.read.call_args.args, (f"https://api.example.test/projects/{PROJECT}/findings",))

    def test_empty_list_is_zero(self):
        self.pages = [response({"findings": []})]
        self.assertEqual(fetch_platform_findings(), 0)

    def test_incomplete_or_malformed_results_never_become_a_count(self):
        for second_page in (
            response({"findings": [], "last_key": "page2"}),
            response({"unexpected": []}),
            response({"findings": [{"state": "open"}]}),
            response({"findings": [{"id": "a", "state": "snoozed"}]}),
            response({"findings": [], "last_key": 123}),
            response({"error": "test-secret"}, 403),
        ):
            with self.subTest(second_page=second_page):
                self.pages = [response({"findings": [finding("a")], "last_key": "page2"}), second_page]
                with self.assertRaises(ValueError) as error:
                    fetch_platform_findings()
                self.assertNotIn("test-secret", str(error.exception))

    def test_authentication_errors_and_redirects_do_not_expose_secrets(self):
        for status in (401, 403, 302, 500):
            self.auth.return_value = response({"error": "test-secret"}, status)
            with self.assertRaisesRegex(ValueError, f"HTTP {status}") as error:
                fetch_platform_findings()
            self.assertNotIn("test-secret", str(error.exception))
        self.read.assert_not_called()

    def test_missing_token_invalid_json_and_network_errors(self):
        self.auth.return_value = response({})
        with self.assertRaisesRegex(ValueError, "no access token"):
            fetch_platform_findings()
        self.auth.return_value.json.side_effect = ValueError("test-secret")
        with self.assertRaisesRegex(ValueError, "invalid JSON") as error:
            fetch_platform_findings()
        self.assertNotIn("test-secret", str(error.exception))
        self.auth.side_effect = requests.Timeout("test-secret")
        with self.assertRaisesRegex(ValueError, "could not be reached") as error:
            fetch_platform_findings()
        self.assertNotIn("test-secret", str(error.exception))
        self.read.assert_not_called()

    def test_configuration_is_validated_before_sending_credentials(self):
        with patch.dict(os.environ, {"VANGUARD_PROJECT_ID": "https://untrusted.invalid"}):
            with self.assertRaisesRegex(ValueError, "project UUID"):
                fetch_platform_findings()
        with patch.dict(os.environ, {"VANGUARD_CLIENT_SECRET": " "}):
            self.assertFalse(vanguard_configured())
            with self.assertRaisesRegex(ValueError, "Configure"):
                fetch_platform_findings()
        self.auth.assert_not_called()
        self.read.assert_not_called()

    def test_only_pro_and_prelive_findings_counted_per_account(self):
        must = {"classification": {"severity": "must", "urgency": "critical"}}
        self.pages = [
            response({"findings": [finding("a", **must, evaluation="overdue"), finding("b", **must, evaluation="ok"),
                                   finding("c", classification={"severity": "should"}, evaluation="in-escalation")],
                      "last_key": "page2"}),
            response({"findings": [finding("d", account="acc-pre", **must, evaluation="in-escalation"),
                                   finding("e", account="acc-dev", **must, evaluation="overdue"),
                                   finding("f", account=None)]}),
        ]
        summary = fetch_platform_findings_summary()
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["accounts"], {
            "PROD": {"total": 3, "must": 2, "overdue": 1, "in-escalation": 1},
            "PRELIVE": {"total": 1, "must": 1, "overdue": 0, "in-escalation": 1},
        })
        self.assertEqual(format_platform_breakdown(summary),
                         "PROD: Must 2 · Overdue 1 · In escalation 1  \nPRELIVE: Must 1 · Overdue 0 · In escalation 1")

    def test_account_tag_and_configured_scope(self):
        self.pages = [response({"findings": [
            {"id": "a", "state": "open", "reference": {"tags": [{"key": "account_guid", "value": "acc-dev"}]}}]})]
        with patch.dict(os.environ, {"VANGUARD_ACCOUNTS": "dev"}):
            self.assertEqual(fetch_platform_findings_summary()["accounts"]["dev"]["total"], 1)

    def test_label_must_be_a_whole_word_of_the_account_name(self):
        self.project = response({"accounts": [{"id": "acc-x", "name": "PROJECT-PRELIVE-2"}]})
        self.pages = [response({"findings": [finding("a", account="acc-x")]})]
        accounts = fetch_platform_findings_summary()["accounts"]
        self.assertEqual((accounts["PROD"]["total"], accounts["PRELIVE"]["total"]), (0, 1))

    def test_no_count_without_matching_accounts(self):
        for project in (response({"accounts": [{"id": "acc-dev", "name": "recall2-DEV"}]}), response({}, 403)):
            with self.subTest(project=project):
                self.project = project
                with self.assertRaisesRegex(ValueError, "No count was saved|HTTP 403"):
                    fetch_platform_findings()
                self.assertEqual(self.findings_calls(), [])


if __name__ == "__main__":
    unittest.main()
