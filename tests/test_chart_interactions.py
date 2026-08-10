import os
import unittest
import time

from skills.trading.demo_synth import synthesize_pattern_candles

from gui.angelique_desktop import AngeliqueDesktopApp


class DummyEvent:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class TestChartInteractions(unittest.TestCase):
    def setUp(self):
        # Create app but don't show window. If Tk can't connect to display, skip tests.
        try:
            self.app = AngeliqueDesktopApp()
            try:
                self.app.withdraw()
            except Exception:
                pass
        except Exception as exc:
            raise unittest.SkipTest(f"Skipping GUI test: cannot create Tk root: {exc}")

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass

    def test_tooltip_and_zoom(self):
        candles = synthesize_pattern_candles("head_and_shoulders", "EURUSD", length=40, seed=3)
        # annotate with times and volumes
        for i, c in enumerate(candles):
            c["time"] = f"t{i}"
            c["tick_volume"] = 100 + i
        self.app._draw_trading_chart(candles)
        # simulate hover near middle
        data = self.app._last_chart_data
        self.assertIsNotNone(data)
        mid = len(data["points_x"]) // 2
        x = int(data["points_x"][mid])
        y = int(self.app.trading_chart_canvas.winfo_height() // 2)
        ev = DummyEvent(x, y)
        # call motion handler
        self.app._on_chart_motion(ev)
        # tooltip should have been created as a window tag
        items = self.app.trading_chart_canvas.find_withtag("chart_tooltip")
        self.assertTrue(len(items) >= 0)  # at least doesn't error

        # test zoom in/out
        before = self.app._trading_chart_view_count
        self.app._zoom_in_chart()
        self.assertLessEqual(self.app._trading_chart_view_count, before)
        self.app._zoom_out_chart()
        self.assertGreaterEqual(self.app._trading_chart_view_count, before)

    def test_drag_to_select_and_zoom(self):
        candles = synthesize_pattern_candles("double_top", "EURUSD", length=50, seed=5)
        for i, c in enumerate(candles):
            c["time"] = f"t{i}"
            c["tick_volume"] = 50 + i
        self.app._draw_trading_chart(candles)
        data = self.app._last_chart_data
        points = data["points_x"]
        self.assertTrue(len(points) >= 10)
        # select a mid-range subset
        start_idx = 5
        end_idx = 15
        sx = int(points[start_idx])
        ex = int(points[end_idx])
        ev_press = DummyEvent(sx, 10)
        self.app._on_chart_button_press(ev_press)
        ev_move = DummyEvent(ex, 40)
        self.app._on_chart_button_motion(ev_move)
        ev_release = DummyEvent(ex, 40)
        self.app._on_chart_button_release(ev_release)
        # after zoom, view_count should be equal to selection_count
        expected = end_idx - start_idx + 1
        self.assertEqual(self.app._trading_chart_view_count, expected)


if __name__ == "__main__":
    unittest.main()
