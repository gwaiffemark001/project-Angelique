import os
import pytest
from core import tools


def _pyautogui_available():
    try:
        import pyautogui  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _pyautogui_available(), reason="pyautogui not available or headless")
def test_screenshot_to_pdf(tmp_path):
    out = tmp_path / "screen.pdf"
    res = tools.execute_tool('adapter.screen.capture_to_pdf', {'output_path': str(out), 'region': None})
    assert os.path.exists(str(out))
    assert str(out) == res
