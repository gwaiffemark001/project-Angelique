import pytest


def test_jarvis_adapter_time_or_skip():
    try:
        from core.adapters import jarvis_adapter as ja
    except Exception as e:
        pytest.skip(f"Adapter import failed: {e}")

    try:
        t = ja.time()
    except ImportError:
        pytest.skip("No Jarvis package found under base projects")
    except AttributeError as e:
        pytest.skip(f"Jarvis does not expose time functionality: {e}")

    assert isinstance(t, str)


def test_jarvis_adapter_system_info_or_skip():
    try:
        from core.adapters import jarvis_adapter as ja
    except Exception as e:
        pytest.skip(f"Adapter import failed: {e}")

    try:
        s = ja.system_info()
    except ImportError:
        pytest.skip("No Jarvis package found under base projects")
    except AttributeError as e:
        pytest.skip(f"Jarvis does not expose system_info functionality: {e}")

    assert isinstance(s, str)
