from __future__ import annotations

import math
import random
from datetime import datetime, timedelta


def synthesize_pattern_candles(pattern="unknown_pattern", symbol="EURUSD", length=60, seed=None, timeframe="H1"):
    rng = random.Random(seed)
    interval = timedelta(hours=1)
    now = datetime.utcfromtimestamp(int(seed)) if seed is not None else datetime.utcnow()
    base = 100.0 if not str(symbol).upper().endswith("USD") else 1.2
    candles = []
    for index in range(max(1, int(length))):
        phase = index / max(1, length - 1)
        if pattern == "double_top":
            close = base + 0.01 * (math.exp(-((phase - .25) ** 2) * 90) + math.exp(-((phase - .75) ** 2) * 90))
            open_price = close
        elif pattern == "double_bottom":
            close = base - 0.01 * (math.exp(-((phase - .25) ** 2) * 90) + math.exp(-((phase - .75) ** 2) * 90))
            open_price = close
        else:
            open_price = base + rng.uniform(-.005, .005)
            close = open_price + rng.uniform(-.001, .001)
        candles.append({"time": (now - interval * (length - index - 1)).isoformat() + "Z", "open": open_price, "high": max(open_price, close) + rng.uniform(.0001, .0008), "low": min(open_price, close) - rng.uniform(.0001, .0008), "close": close, "tick_volume": rng.randint(10, 500)})
    return candles
