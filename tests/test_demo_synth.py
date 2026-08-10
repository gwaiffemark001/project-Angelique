import unittest
from skills.trading.demo_synth import synthesize_pattern_candles


class TestDemoSynth(unittest.TestCase):
    def test_head_and_shoulders_shape(self):
        candles = synthesize_pattern_candles("head_and_shoulders", "EURUSD", length=30, seed=42)
        self.assertEqual(len(candles), 30)
        # Ensure OHLC keys exist
        for c in candles:
            self.assertIn("open", c)
            self.assertIn("high", c)
            self.assertIn("low", c)
            self.assertIn("close", c)

    def test_double_top_symmetry(self):
        candles = synthesize_pattern_candles("double_top", "EURUSD", length=40, seed=1)
        self.assertEqual(len(candles), 40)
        closes = [c["close"] for c in candles]
        # Peak positions roughly symmetric: value at 10 and 30 should be similar
        self.assertAlmostEqual(closes[9], closes[29], places=3)

    def test_fallback_pattern(self):
        candles = synthesize_pattern_candles("unknown_pattern", "GBPUSD", length=20, seed=7)
        self.assertEqual(len(candles), 20)


if __name__ == "__main__":
    unittest.main()
