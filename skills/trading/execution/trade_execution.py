from skills.trading.engine.mt5_bridge import bridge
import json

def execute_market_order(symbol: str, order_type: str, volume: float, sl: float, tp: float, comment: str = "Angelique AI") -> str:
    """Sends the execution command to the Wine Bridge."""
    payload = {
        "action": "place_order",
        "symbol": symbol,
        "type": order_type, # "BUY" or "SELL"
        "volume": volume,
        "sl": sl,
        "tp": tp,
        "comment": comment
    }
    
    response = bridge.send_command("place_order", payload)
    if response.get("success"):
        return f"✅ Order Executed! Ticket: {response.get('ticket')}, Price: {response.get('price')}"
    else:
        return f"❌ Execution Failed: {response.get('error')}"
