import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

module_path = ROOT / 'skills' / 'trading' / 'engine' / 'mt5_bridge_server.py'
spec = importlib.util.spec_from_file_location('mt5_bridge_server', module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_initialize_mt5_without_mt5_module_returns_error_payload():
    module.mt5 = None
    result = module.initialize_mt5()
    assert result['error'].startswith('MetaTrader5 module is not available')
