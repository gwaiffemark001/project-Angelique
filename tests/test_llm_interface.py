import unittest

from brain.llm_interface import extract_json_from_text


class LLMInterfaceTests(unittest.TestCase):
    def test_extract_json_from_text_parses_json_object(self):
        text = '{"tool": "open_app", "args": {"app_name": "Firefox"}}'
        parsed = extract_json_from_text(text)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed.get("tool"), "open_app")
        self.assertEqual(parsed.get("args", {}).get("app_name"), "Firefox")

    def test_extract_json_from_text_parses_markdown_wrapped_json(self):
        text = "```json\n{\"tool\": \"open_app\", \"args\": {\"app_name\": \"Firefox\"}}\n```"
        parsed = extract_json_from_text(text)
        self.assertEqual(parsed.get("tool"), "open_app")

    def test_extract_json_from_text_returns_empty_dict_for_invalid_json(self):
        parsed = extract_json_from_text("This is not JSON")
        self.assertEqual(parsed, {})


if __name__ == "__main__":
    unittest.main()
