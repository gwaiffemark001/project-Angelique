from .workflow import TradingWorkflow
from .bridge import WineBridgeClient
from .mt5_adapter import WineMT5Adapter


def build_default_workflow(risk_percent=None, minimum_rr=None, trading_mode="DAY_TRADING"):
    from .profiles import get_trading_profile

    profile = get_trading_profile(trading_mode)
    return TradingWorkflow(
        WineMT5Adapter(WineBridgeClient()),
        risk_percent=risk_percent,
        minimum_rr=profile.minimum_rr if minimum_rr is None else minimum_rr,
        trading_mode=profile.mode,
    )
