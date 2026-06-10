"""AI 분석 레이어 테스트 — API 호출 없이 규칙/필터 로직 검증."""
import numpy as np
import pandas as pd

from src.ai_analyst import (classify_regime, filter_signals, regime_series,
                            rule_based_regime, summarize_market)


def make_ohlcv(closes):
    closes = pd.Series(closes, dtype=float)
    return pd.DataFrame({
        "open": closes, "high": closes * 1.005, "low": closes * 0.995,
        "close": closes, "volume": 1.0,
    })


def test_classify_regime_without_key_returns_unknown(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    df = make_ohlcv(np.linspace(100, 120, 120))
    assert classify_regime(df) == "unknown"


def test_rule_based_uptrend():
    df = make_ohlcv(np.linspace(100, 150, 120))
    assert rule_based_regime(df) == "uptrend"


def test_rule_based_downtrend():
    df = make_ohlcv(np.linspace(150, 100, 120))
    assert rule_based_regime(df) == "downtrend"


def test_rule_based_ranging():
    rng = np.random.default_rng(7)
    closes = 100 + np.sin(np.linspace(0, 12 * np.pi, 120)) + rng.normal(0, 0.1, 120)
    assert rule_based_regime(make_ohlcv(closes)) == "ranging"


def test_filter_blocks_longs_in_downtrend():
    sig = pd.Series([1, 1, -1, 0, 1])
    out = filter_signals(sig, "downtrend")
    assert (out[sig > 0] == 0).all()
    assert (out[sig < 0] == -1).all()


def test_filter_unknown_passes_through():
    sig = pd.Series([1, -1, 0])
    assert filter_signals(sig, "unknown").tolist() == [1, -1, 0]


def test_regime_series_no_lookahead():
    """시점 i의 레짐은 i 이전 데이터만 사용 — 미래 급등을 미리 알 수 없다."""
    closes = [100.0] * 150 + [200.0] * 5  # 150번째에 갑자기 급등
    regs = regime_series(make_ohlcv(closes), lookback=100)
    assert regs.iloc[150] != "uptrend"  # 급등 직후 시점엔 아직 모름


def test_summarize_contains_key_stats():
    s = summarize_market(make_ohlcv(np.linspace(100, 120, 120)))
    assert "기간 수익률" in s and "SMA20" in s
