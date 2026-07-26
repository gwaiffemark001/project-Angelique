import json
import os
from datetime import datetime

JOURNAL_PATH = "data/trading_journal.json"

def log_trade(trade_data: dict):
    """Logs a trade to the local JSON journal for future AI analysis."""
    os.makedirs("data", exist_ok=True)
    trade_data["timestamp"] = datetime.now().isoformat()
    
    journal = []
    if os.path.exists(JOURNAL_PATH):
        with open(JOURNAL_PATH, 'r') as f:
            journal = json.load(f)
            
    journal.append(trade_data)
    with open(JOURNAL_PATH, 'w') as f:
        json.dump(journal, f, indent=4)
    print(f"📓 Trade logged to journal.")
