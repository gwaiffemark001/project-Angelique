from datetime import datetime, timedelta, timezone

from skills.trading_skill.analysis import analyze_structure
from skills.trading_skill.data_quality import assess_candles
from skills.trading_skill.profiles import DAY_PROFILE


def candles(count, tf="M5", age_seconds=0):
    base = datetime.now(timezone.utc) - timedelta(minutes=5 * (count - 1) + age_seconds)
    out = []
    for i in range(count):
        t = base + timedelta(minutes=5 * i)
        out.append({"time": t.isoformat(), "open": 100+i*0.01, "high": 100.02+i*0.01, "low": 99.98+i*0.01, "close": 100.01+i*0.01, "closed": True})
    return out


def test_short_entry_history_is_not_forced_to_200():
    result = assess_candles(candles(60), "M5", minimum_candles=DAY_PROFILE.minimum_analysis_candles("M5"))
    assert result["status"] == "fresh"


def test_analysis_reports_insufficient_history_separately():
    tfs = {tf: candles(DAY_PROFILE.minimum_analysis_candles(tf), tf) for tf in DAY_PROFILE.analysis_required_timeframes}
    tfs["M5"] = candles(20, "M5")
    result = analyze_structure(tfs, profile=DAY_PROFILE)
    assert result["decision"] == "INSUFFICIENT_HISTORY"
    assert "M5" in result["data_quality"]


def test_analysis_reports_stale_data_separately():
    tfs = {tf: candles(DAY_PROFILE.minimum_analysis_candles(tf), tf) for tf in DAY_PROFILE.analysis_required_timeframes}
    old = candles(DAY_PROFILE.minimum_analysis_candles("M5"), "M5", age_seconds=7200)
    tfs["M5"] = old
    result = analyze_structure(tfs, profile=DAY_PROFILE)
    assert result["decision"] == "STALE_MARKET_DATA"
