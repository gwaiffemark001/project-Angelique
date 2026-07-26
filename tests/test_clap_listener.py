import unittest

from skills.voice.clap_listener import is_double_clap_interval


class ClapListenerTests(unittest.TestCase):
    def test_accepts_claps_within_the_expected_window(self):
        self.assertTrue(is_double_clap_interval(0.12))

    def test_rejects_claps_that_are_too_fast(self):
        self.assertFalse(is_double_clap_interval(0.03))

    def test_accepts_claps_that_are_slightly_slower(self):
        self.assertTrue(is_double_clap_interval(0.45))

    def test_rejects_claps_that_are_too_slow(self):
        self.assertFalse(is_double_clap_interval(0.6))


if __name__ == "__main__":
    unittest.main()
