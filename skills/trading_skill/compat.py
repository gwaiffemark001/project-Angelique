from .workflow import TradingWorkflow
from .bridge import WineBridgeClient
from .mt5_adapter import WineMT5Adapter


def build_default_workflow(risk_percent=1.0, minimum_rr=2.0):
    return TradingWorkflow(WineMT5Adapter(WineBridgeClient()), risk_percent=risk_percent, minimum_rr=minimum_rr)
