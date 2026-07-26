def generate_trade_brief(analysis: dict, validation: dict, lot_size: float) -> str:
    """Formats the raw data into the human-readable Angelique Trade Recommendation."""
    if not validation["approved"]:
        return f"🚫 Trade Rejected. Reasons: {' '.join(validation['reasons'])}"
        
    brief = f"""
📊 **ANGELIQUE TRADE RECOMMENDATION**
-----------------------------------
**Direction:** {analysis.get('direction', 'N/A')} {analysis.get('symbol', '')}
**Entry:** {analysis.get('current_price', 'N/A')}
**Stop Loss:** {analysis.get('sl_price', 'N/A')} ({analysis.get('sl_pips', 0)} pips)
**Take Profit:** {analysis.get('tp_price', 'N/A')} ({analysis.get('tp_pips', 0)} pips)
**Lot Size:** {lot_size} lots (Risk: {analysis.get('risk_percent', 1)}%)
**Reward/Risk:** 1:{analysis.get('rr_ratio', 0)}
**Confidence:** {validation['confidence']['total_score']}%

🧠 **Reasoning:**
{analysis.get('reasoning_text', 'Setup meets all criteria.')}

⚠️ **Shall I execute this trade?**
"""
    return brief
