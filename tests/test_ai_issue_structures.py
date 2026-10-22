import unittest
from unittest.mock import patch, MagicMock
import os
import json
import tempfile

from utils.ai_helpers import (
    load_issue_structures,
    generate_issue_with_ollama,
    DEFAULT_ISSUE_STRUCTURES,
    LEGACY_ISSUE_SYSTEM_PROMPT,
)


class TestAIIssueStructures(unittest.TestCase):
    def test_load_issue_structures_from_real_file(self):
        structures = load_issue_structures()
        self.assertIsInstance(structures, dict)
        self.assertIn("default_preset_by_type", structures)
        self.assertIn("presets", structures)
        self.assertIn("extra_sections", structures)
        self.assertIn("User Story", structures["default_preset_by_type"])
        self.assertIn("Standard Agile (BDD / Gherkin)", structures["presets"])
        self.assertIsNone(getattr(structures, "warning", None))

    def test_load_issue_structures_missing_file_fallback(self):
        structures, warning = load_issue_structures("non_existent_file.json", return_warning=True)
        self.assertIsInstance(structures, dict)
        self.assertIn("presets", structures)
        self.assertIsNotNone(warning)
        self.assertIn("not found", warning)
        self.assertEqual(structures["presets"], DEFAULT_ISSUE_STRUCTURES["presets"])

    def test_load_issue_structures_invalid_json_fallback(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
            f.write("{ invalid json ,,, ")
            temp_path = f.name
        try:
            structures, warning = load_issue_structures(temp_path, return_warning=True)
            self.assertIsInstance(structures, dict)
            self.assertIn("presets", structures)
            self.assertIsNotNone(warning)
            self.assertIn("Using fallback defaults", warning)
            self.assertEqual(structures["presets"], DEFAULT_ISSUE_STRUCTURES["presets"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("requests.post")
    def test_generate_issue_legacy_fallback(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"content": "Legacy output"}}
        mock_post.return_value = mock_response

        # Backward compatibility with positional args
        res = generate_issue_with_ollama("llama3", "User Story", "My idea")
        self.assertEqual(res, "Legacy output")

        call_args = mock_post.call_args[1]
        payload = call_args["json"]
        system_content = payload["messages"][0]["content"]
        self.assertEqual(system_content, LEGACY_ISSUE_SYSTEM_PROMPT)

    @patch("requests.post")
    def test_generate_issue_api_compat_keywords(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"content": "API output"}}
        mock_post.return_value = mock_response

        # Backward compatibility with api.py keyword args
        res = generate_issue_with_ollama(
            model_name="llama3",
            issue_type="Task",
            input_text="My task details",
            base_url="http://localhost:11434"
        )
        self.assertEqual(res, "API output")

    @patch("requests.post")
    def test_generate_issue_with_dynamic_sections(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"content": "Dynamic output"}}
        mock_post.return_value = mock_response

        sections = [
            "User Story (As a / I want / So that)",
            "Acceptance Criteria (Given / When / Then)",
            "Implementation Checklist"
        ]
        res = generate_issue_with_ollama(
            model="mistral",
            issue_type="User Story",
            prompt_input="Shopping Cart",
            sections=sections,
            preset_name="Standard Agile (BDD / Gherkin)",
            custom_instructions="Write in Spanish"
        )
        self.assertEqual(res, "Dynamic output")

        payload = mock_post.call_args[1]["json"]
        system_content = payload["messages"][0]["content"]

        # Heading order preserved
        self.assertIn("1. ### User Story (As a / I want / So that)", system_content)
        self.assertIn("2. ### Acceptance Criteria (Given / When / Then)", system_content)
        self.assertIn("3. ### Implementation Checklist", system_content)

        # Smart section rules included
        self.assertIn("BDD / Acceptance Criteria", system_content)
        self.assertIn("Agile User Story Narrative", system_content)
        self.assertIn("Checklist Format", system_content)

        # Custom instructions appended
        self.assertIn("Write in Spanish", system_content)
        self.assertIn("Standard Agile (BDD / Gherkin)", system_content)

    @patch("requests.post")
    def test_generate_issue_with_custom_freeform(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"content": "Freeform output"}}
        mock_post.return_value = mock_response

        res = generate_issue_with_ollama(
            model="llama3",
            issue_type="Bug",
            prompt_input="Crash on logout",
            sections=[],
            custom_instructions="Use an incident response table with timestamp, service, and impact columns."
        )
        self.assertEqual(res, "Freeform output")

        payload = mock_post.call_args[1]["json"]
        system_content = payload["messages"][0]["content"]
        self.assertIn("Use an incident response table", system_content)


if __name__ == "__main__":
    unittest.main()

