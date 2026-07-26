def calculate_lot_size(balance: float, risk_percent: float, sl_pips: float, pip_value: float) -> float:
    """Calculates exact lot size based on risk percentage."""
    risk_amount = balance * (risk_percent / 100)
    if sl_pips <= 0 or pip_value <= 0: return 0.01
    lot_size = risk_amount / (sl_pips * pip_value)
    return round(max(0.01, lot_size), 2)
