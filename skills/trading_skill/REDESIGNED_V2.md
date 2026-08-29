# Angelique Trading Skill v2

This package is a drop-in replacement for the existing `skills/trading_skill` package.

## What changed
- Correct MT5 demo/real/contest account-mode detection.
- Continuous market-event tracking for candle changes and setup progression.
- Scanner now evaluates the full eligible universe instead of stopping at the first result.
- Scanner exposes per-symbol failure stages, setup progress, missing evidence, and confluence scores.
- Lower-timeframe trend ambiguity no longer blocks the entire analysis before SMC evidence is evaluated.
- MT5 bridge requests retry briefly after transient WebSocket failures.
- Execution performs a fresh broker quote and `order_check` before `order_send` and respects broker filling flags where available.
- Added recent account-deal retrieval for diagnostics.
- Existing approval/revalidation safety gate remains in place. Scanning does not execute trades.

## Compatibility
Existing public modules and function names are retained wherever possible. Replace the existing `skills/trading_skill` directory with this directory; keep your existing `core` package and configuration.

Test on a demo account first. No strategy change can guarantee profitable trading.
