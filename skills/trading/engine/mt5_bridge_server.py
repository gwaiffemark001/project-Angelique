from skills.trading_skill.wine_server import *
from skills.trading_skill.wine_server import main
from skills.trading_skill.demo import synthesize_pattern_candles


def synthesize_demo_candles(symbol, pattern="unknown_pattern", length=60, seed=None, timeframe="H1"):
    return synthesize_pattern_candles(pattern, symbol, length, seed, timeframe)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
