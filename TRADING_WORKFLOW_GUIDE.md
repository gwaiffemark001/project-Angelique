# ANGELIQUE TRADING WORKFLOW - COMPLETE IMPLEMENTATION GUIDE

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    USER INTERFACE (GUI)                 │
│              (gui/angelique_desktop.py)                 │
└──────────────────────┬──────────────────────────────────┘
                       │
         ┌─────────────┴──────────────┐
         │                            │
    ANALYSIS                    EXECUTION
    REQUEST                     REQUEST
         │                            │
         ▼                            ▼
┌──────────────────────┐  ┌────────────────────────┐
│  SymbolManager       │  │  TradePlanBuilder      │
│ (symbol resolution)  │  │ (plan generation)      │
└──────────┬───────────┘  └──────────┬─────────────┘
           │                         │
           ├─────────────┬───────────┤
           │             │           │
           ▼             ▼           ▼
    ┌──────────────────────────────────────┐
    │       Market Data & Analysis         │
    │  (market_data.py, trend.py, etc)     │
    └──────────────┬───────────────────────┘
                   │
    ┌──────────────┴────────────────────┐
    │                                   │
    ▼                                   ▼
┌─────────────────┐           ┌──────────────────┐
│  RiskManager    │           │   Account Info   │
│ (validation)    │           │  (account.py)    │
└────────┬────────┘           └────────┬─────────┘
         │                             │
         ├─────────────┬───────────────┤
         │             │               │
         ▼             ▼               ▼
┌──────────────────────────────────────────────────┐
│         Trade Plan Object (TradePlan)            │
│  • Symbol                                        │
│  • Direction (BUY/SELL)                          │
│  • Entry/SL/TP                                   │
│  • Lot size                                      │
│  • Risk/Reward                                   │
│  • Status: PENDING_APPROVAL → APPROVED → ... │
└──────────────────┬───────────────────────────────┘
                   │
         USER APPROVAL REQUIRED
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│         MT5 Bridge                               │
│  (connection_manager.py, mt5_bridge.py)         │
│  ✓ Execute order                                │
│  ✓ Verify execution                             │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│      Trade Journal (journal.py)                  │
│  ✓ Record execution                             │
│  ✓ Track P&L                                    │
│  ✓ Analyze performance                          │
└──────────────────────────────────────────────────┘
```

---

## Complete Workflow: Step by Step

### USER INITIATES REQUEST

```
User: "Analyze EURUSD for a BUY setup"
                        │
                        ▼
              GUI calls SymbolManager
              resolve_symbol("EURUSD")
                        │
                        ▼
          SymbolManager queries MT5
          Gets actual symbol name
          (e.g., "EURUSDm" not "EURUSD")
                        │
                        ▼
            Symbol resolved ✓
```

**Code:**
```python
from skills.trading.engine.symbol_manager import symbol_manager

symbol = symbol_manager.resolve_symbol("EURUSD")
# Returns: "EURUSDm" (or whatever MT5 actually exposes)

specs = symbol_manager.get_symbol_specs(symbol)
# Returns: {
#   "symbol": "EURUSDm",
#   "bid": 1.16520,
#   "ask": 1.16530,
#   "point": 0.00001,
#   "digits": 5,
#   "volume_min": 0.01,
#   "volume_max": 100.0,
#   "volume_step": 0.01
# }
```

---

### CHECK MARKET CONDITIONS

```
Market conditions validated:
✓ Market is open
✓ Spread acceptable (< 5.0 pips)
✓ Account logged in
✓ Sufficient margin
                        │
                        ▼
          Ready for analysis ✓
```

**Code:**
```python
from skills.trading.engine.account import get_account_summary

account = get_account_summary(account_mode="demo")

if account.get("error") or not account.get("login"):
    # Show: Balance 0.0, Equity 0.0, etc.
    # NOT logged in - cannot trade
    return {"error": "Not logged in to MT5"}

balance = account["balance"]  # e.g., 100000.0
# But if there's an error or no login, account["balance"] = 0
```

---

### MULTI-TIMEFRAME ANALYSIS

```
                    User request
                         │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
       H4           H1 Trend          M15 Setup
    Structure       Detection         Detection
         │                ▼                │
         │         What is trend?          ▼
         │         • Bullish            Is there a
         │         • Bearish            reversal setup?
         │         • Sideways
         │                               ▼
         │         ✓ Bullish           ✓ Yes
         │                              │
         └────────────────┬─────────────┘
                          │
                          ▼
            Setup Quality Assessment
         • Trend: Bullish ✓
         • Structure: Higher Highs ✓
         • Pullback: Into support ✓
         • Confirmation: Bullish candle ✓
         • EMA: Price above 20 EMA ✓
         • Risk/Reward: 1:3 ✓
         
         Overall: HIGH QUALITY SETUP
```

**Code:**
```python
from skills.trading.market.market_data import market
from skills.trading.analysis.trend import determine_trend

# Get 4-hour data
h4_data = market.get_candles_and_indicators("EURUSDm", "H4", count=100)
h4_trend = determine_trend(h4_data)
# Returns: "BULLISH" or "BEARISH"

# Get 1-hour data
h1_data = market.get_candles_and_indicators("EURUSDm", "H1", count=100)
h1_trend = determine_trend(h1_data)

# Get 15-minute data for setup
m15_data = market.get_candles_and_indicators("EURUSDm", "M15", count=100)
```

---

### BUILD TRADE PLAN

```
TradePlanBuilder workflow:
                        │
         ┌──────────────┼──────────────┐
         ▼              ▼              ▼
    Setup ID       Risk/Reward    Lot Calculation
         │          Determination      │
         │              │              │
    Direction:       Entry: 1.1630  Account balance: $100k
    BUY              SL: 1.1615     Risk per trade: 2%
    Entry: 1.1630    TP: 1.1675     Max risk: $2000
                                    Risk pips: 15
    Lot size         Ratio: 1:3     Lot size: 0.05
    calculation:
    $2000 ÷ (15 pips × 10) = 0.05
                        │
                        ▼
         ┌──────────────────────────┐
         │   TRADE PLAN CREATED     │
         │                          │
         │  Symbol: EURUSDm         │
         │  Direction: BUY          │
         │  Entry: 1.16300          │
         │  SL: 1.16150             │
         │  TP: 1.16750             │
         │  Lot: 0.05               │
         │  Risk: $50               │
         │  Reward: $150            │
         │  Ratio: 1:3              │
         │                          │
         │  Status:                 │
         │  PENDING_APPROVAL        │
         └──────────────────────────┘
```

**Code:**
```python
from skills.trading.engine.trade_plan import TradePlanBuilder
from skills.trading.engine.risk_manager import risk_manager

builder = TradePlanBuilder("EURUSDm", "BUY")
builder.add_reason("H4 bullish trend")
builder.add_reason("Higher High structure")
builder.add_reason("Pullback to support")
builder.add_reason("M15 bullish candle confirmation")
builder.set_confidence("HIGH")
builder.confirm_setup()

plan = builder.build_plan(
    entry_price=1.16300,
    entry_type="BUY_LIMIT",
    stop_loss=1.16150,
    take_profit=1.16750,
    lot_size=0.05,
    account_balance=100000.0,
)

# Display to user
print(plan.format_for_display())
```

---

### RISK VALIDATION (HARD BLOCKERS)

```
RiskManager checks:

┌─ Market conditions ─┐
│ ✓ Market open      │
│ ✓ Spread < 5 pips  │
└────────────────────┘

┌─ Account limits ────────┐
│ ✓ Daily loss < 3%       │
│ ✓ Trade risk < 2%       │
│ ✓ Open positions < 3    │
│ ✓ Margin sufficient     │
└────────────────────────┘

┌─ Position validity ─────┐
│ ✓ Lot size valid        │
│ ✓ SL below entry (BUY)  │
│ ✓ TP above entry (BUY)  │
│ ✓ SL/TP distance OK     │
└────────────────────────┘

All checks pass ✓

Status: PLAN VALID
Ready for user approval
```

**Code:**
```python
from skills.trading.engine.risk_manager import risk_manager

plan_dict = plan.to_dict()
plan_dict["market_data"] = {"market_open": True, "spread": 0.8}
plan_dict["margin_available"] = account["free_margin"]
plan_dict["point"] = 0.00001

is_valid, errors = risk_manager.validate_trade_plan(
    plan_dict,
    account_balance=100000.0
)

if not is_valid:
    for error in errors:
        print(f"❌ {error}")
    # DO NOT execute
else:
    print("✓ All risk checks passed")
```

---

### USER APPROVAL (CRITICAL GATE)

```
GUI shows:

╔═══════════════════════════════════════╗
║      TRADE PLAN AWAITING APPROVAL     ║
╚═══════════════════════════════════════╝

Symbol: EURUSDm
Direction: 🟢 BUY

Entry:       1.16300
Stop Loss:   1.16150
Take Profit: 1.16750

Lot Size: 0.05
Risk: 2.0% ($2,000)
Reward: 1:3 ratio

Confidence: HIGH

Reason:
 • H4 bullish trend
 • Higher High structure
 • Pullback to support
 • M15 bullish candle confirmation

[APPROVE]  [REJECT]
```

**User must explicitly confirm:**

```
User: "Confirm BUY EURUSDm, entry 1.16300, SL 1.16150, TP 1.16750, 0.05 lots."
```

Only then → EXECUTION

---

### EXECUTION

```
After user confirms:
                │
                ▼
      Send order to MT5
      via bridge
                │
                ▼
      ┌──────────────────┐
      │ Order validation │
      └────────┬─────────┘
               │
     ┌─────────┼─────────┐
     ▼                   ▼
   SUCCESS            REJECTED
     │
     ▼
Record ticket
Update plan status
Journal trade
     │
     ▼
POSITION OPEN ✓
```

**Code:**
```python
from skills.trading.engine.mt5_bridge import bridge
from skills.trading.learning.journal import trade_journal

result = bridge.send_command("execute_trade", {
    "symbol": plan.symbol,
    "volume": plan.lot_size,
    "action": "TRADE_ACTION_DEAL",
    "type": 1,  # BUY
    "price": plan.entry_price,
    "sl": plan.stop_loss,
    "tp": plan.take_profit,
    "comment": "Angelique BUY setup"
})

if "error" not in result:
    plan.status = "EXECUTED"
    plan.ticket = result["ticket"]
    trade_journal.record_trade(plan)
    print(f"✓ Order executed. Ticket: {result['ticket']}")
else:
    plan.status = "REJECTED"
    print(f"❌ Order rejected: {result['error']}")
```

---

## Key Points for Your Implementation

### 1. Symbol Resolution is CRITICAL

```python
# ❌ WRONG - Hard-coded symbol names
symbol = "EURUSD"  # What if broker uses "EURUSDm"?

# ✓ CORRECT - Query MT5
symbol = symbol_manager.resolve_symbol("EURUSD")
# Returns actual symbol from broker: "EURUSDm"
```

### 2. Account Shows 0 When Not Logged In

```python
# Fixed in gui/angelique_desktop.py:

# OLD (buggy):
# if not account or not account.get("login") or (account.get("error") and account.get("mode_match", True) is True):

# NEW (correct):
if not account or not account.get("login") or account.get("error"):
    show_balance = 0  # ✓ Shows 0 when not logged in
```

### 3. Charts Render When Symbol is Available

```python
# Market data retrieval must use resolved symbol:
market_data = market.get_candles_and_indicators(
    symbol,  # This is "EURUSDm", not "EURUSD"
    timeframe="M1",
    count=100,
    account_mode="demo"
)

if market_data and market_data.get("candles"):
    # Chart can render
    gui.draw_chart(market_data["candles"])
else:
    # Symbol not available - show placeholder
    gui.draw_placeholder("Market chart unavailable")
```

### 4. Risk Manager is the Final Blocker

```python
# Even if everything looks good, RiskManager can STOP the trade:

if daily_loss < -3% of account:
    ❌ BLOCKED - Daily loss limit reached

if trade_risk > 2% of account:
    ❌ BLOCKED - Risk too high

if not market_open:
    ❌ BLOCKED - Market closed

if spread > 5 pips:
    ❌ BLOCKED - Spread too wide
```

---

## Testing the Workflow

### Test 1: Symbol Resolution
```
python3 -c "
from skills.trading.engine.symbol_manager import symbol_manager
symbol = symbol_manager.resolve_symbol('EURUSD')
print(f'Resolved symbol: {symbol}')
specs = symbol_manager.get_symbol_specs(symbol)
print(f'Contract specs: {specs}')
"
```

### Test 2: Account Display (Shows 0 when not logged in)
```
python3 -c "
from skills.trading.engine.account import get_account_summary
account = get_account_summary(account_mode='demo')
print(f'Balance: {account.get(\"balance\")}')
print(f'Login: {account.get(\"login\")}')
print(f'Error: {account.get(\"error\")}')
"
```

### Test 3: Market Data Retrieval
```
python3 -c "
from skills.trading.market.market_data import market
data = market.get_candles_and_indicators('EURUSDm', 'M1', count=10)
print(f'Candles: {len(data.get(\"candles\", []))}')
if data.get('candles'):
    print('✓ Chart can render')
else:
    print('✗ No data for chart')
"
```

---

## Files You'll Work With

| File | Purpose |
|------|---------|
| `skills/trading/engine/symbol_manager.py` | ✓ NEW - Symbol resolution |
| `skills/trading/engine/trade_plan.py` | ✓ NEW - Trade plan building |
| `skills/trading/engine/risk_manager.py` | ✓ NEW - Risk validation |
| `skills/trading/market/market_data.py` | Fetch candles (use resolved symbol) |
| `skills/trading/engine/account.py` | Account info (already correct logic) |
| `gui/angelique_desktop.py` | ✓ FIXED - Account display (shows 0 when error) |
| `skills/trading/learning/journal.py` | Trade journal |

---

This is your complete trading workflow. All the pieces are now in place.
