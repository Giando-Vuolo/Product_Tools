import os
import unittest
from unittest.mock import Mock, patch

import requests

from utils.vanguard_helpers import fetch_platform_findings, vanguard_configured


PROJECT = "11111111-1111-4111-8111-111111111111"
CONFIG = {
    "VANGUARD_PROJECT_ID": PROJECT,
    "VANGUARD_CLIENT_ID": "test-client",
    "VANGUARD_CLIENT_SECRET": "test-secret",
}


def response(payload, status=200):
    return Mock(status_code=status, json=Mock(return_value=payload))


def finding(identifier):
    return {"id": identifier, "state": "open"}


class VanguardTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, CONFIG)
        self.post = patch("utils.vanguard_helpers.requests.post", return_value=response({"access_token": "test-token"}))
        self.get = patch("utils.vanguard_helpers.requests.get")
        self.env.start()
        self.auth = self.post.start()
        self.read = self.get.start()
        self.addCleanup(patch.stopall)

    def test_all_pages_unique_findings_and_read_only_endpoints(self):
        self.read.side_effect = [
            response({"findings": [finding("a"), finding("b")], "last_key": "page2"}),
            response({"findings": [finding("b"), finding("c")]}),
        ]
        self.assertEqual(fetch_platform_findings(), 3)
        self.auth.assert_called_once_with(
            "https://auth.api.vwapps.cloud/oauth2/token",
            data={"grant_type": "client_credentials", "client_id": "test-client", "client_secret": "test-secret"},
            timeout=30, allow_redirects=False,
        )
        self.assertEqual(self.read.call_count, 2)
        for call in self.read.call_args_list:
            self.assertEqual(call.args, (f"https://api.vwapps.cloud/projects/{PROJECT}/findings",))
            self.assertEqual(call.kwargs["params"]["state"], "open")
            self.assertEqual(call.kwargs["params"]["preview"], "false")
            self.assertEqual(call.kwargs["params"]["page_size"], 100)
            self.assertFalse(call.kwargs["allow_redirects"])
        self.assertNotIn("last_key", self.read.call_args_list[0].kwargs["params"])
        self.assertEqual(self.read.call_args_list[1].kwargs["params"]["last_key"], "page2")

    def test_empty_list_is_zero(self):
        self.read.return_value = response({"findings": []})
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
                self.read.side_effect = [response({"findings": [finding("a")], "last_key": "page2"}), second_page]
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


if __name__ == "__main__":
    unittest.main()
