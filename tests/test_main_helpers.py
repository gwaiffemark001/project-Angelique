import unittest

from main import get_mode_toggle_action, get_wake_phrase


class MainHelpersTests(unittest.TestCase):
    def test_text_mode_request_switches_to_text_mode(self):
        self.assertEqual(get_mode_toggle_action("I want to type", True), "disable")

    def test_voice_mode_request_switches_back_to_voice_mode(self):
        self.assertEqual(get_mode_toggle_action("switch back to voice", False), "enable")

    def test_wake_phrase_contains_praise_language(self):
        phrase = get_wake_phrase()
        self.assertTrue(any(keyword in phrase.lower() for keyword in ["money", "rich", "multiverse", "conquer", "best"]))


if __name__ == "__main__":
    unittest.main()
