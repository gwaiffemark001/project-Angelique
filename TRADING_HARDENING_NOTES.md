# Angelique Trading Hub Hardening

This package contains the refactored Trading Hub source tree.

## Implemented

- AMD is a first-class strategy candidate and is no longer only supporting evidence.
- All supported trading modes target 1.00% of current equity per trade.
- Broker-volume normalization is always followed by an actual SL-risk recalculation; normalized planned risk may not exceed 1.00%.
- Broker minimum-volume constraints reject trades that would exceed the 1% ceiling.
- Technical analysis uses completed candles; MT5 current/forming bar is excluded from analysis data.
- Indicator and market-data readiness now requires sufficient history.
- Structural SL/TP selection uses the existing validated swing structure and identifies a relevant invalidation swing plus the next valid structural target.
- Structural RR is calculated after SL/TP selection; insufficient RR blocks the trade rather than distorting the levels.
- MT5 broker-calculated P/L is used for monetary risk where available.
- MT5 spread is represented in points internally; conventional FX pips are derived for display; metals are displayed in MT5 points rather than a fabricated universal pip unit.
- Shared-currency exposure and conservative correlation controls are present.
- Existing positions with unknown SL risk are not treated as zero risk.
- Position monitoring pauses technical management on stale/unavailable market data.
- Break-even/trailing changes are verified after broker modification.
- Position termination uses verification/pending states and does not treat a placed close request as a confirmed close.
- Kill-switch/consecutive-loss accounting uses completed exit deals.
- Account-mode verification has explicit states and stale-generation protection.
- News-related manual approval can be announced by Angelique for Gold and other supported instruments.
- Confirmed execution and execution-verification-pending states can be announced through the existing Angelique voice interface.
- Trading Hub UI uses backend risk/strategy/SL/TP/spread state rather than recalculating its own values.
- Existing scalping runtime logic was not reintroduced.

## Validation performed

- `pytest -q`: 29 passed, 8 warnings.
- `xvfb-run -a python scripts/validate_skills.py`: 21/21 passed.
- `xvfb-run -a python scripts/validate_skill_groups.py`: 101/101 passed.
- `python -m compileall -q brain core gui skills scripts tests`: passed.

The exhaustive validation script in `scripts/validate_all_skills_exhaustive.py` completed its checks successfully under Xvfb, but its process returned a non-zero status after the check stream; no individual check was reported as failed in the output. Optional local services such as Ollama, sentence-transformers, chromadb, and DDGS were unavailable in this validation environment and were handled by the project's fallback paths.

## Package safety

The archive intentionally excludes `.env` and runtime-generated account/database/log/cache state. Provide your local `.env` separately when running the project.
