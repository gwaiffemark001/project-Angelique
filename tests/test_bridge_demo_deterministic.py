import unittest
from skills.trading.engine import mt5_bridge_server


class TestBridgeDemoDeterministic(unittest.TestCase):
    def test_seed_reproducible(self):
        a = mt5_bridge_server.synthesize_demo_candles("EURUSD", "head_and_shoulders", length=30, seed=1234)
        b = mt5_bridge_server.synthesize_demo_candles("EURUSD", "head_and_shoulders", length=30, seed=1234)
        self.assertEqual(a, b)

    def test_different_seeds_vary(self):
        a = mt5_bridge_server.synthesize_demo_candles("EURUSD", "double_top", length=25, seed=1)
        b = mt5_bridge_server.synthesize_demo_candles("EURUSD", "double_top", length=25, seed=2)
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
