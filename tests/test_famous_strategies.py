"""유명 트레이더 전략 단위 테스트."""
import numpy as np
import pandas as pd

from src.strategies import Donchian, MacdMomentum, Supertrend, VolBreakout


def make_ohlcv(closes, spread=0.01):
    closes = pd.Series(closes, dtype=float)
    return pd.DataFrame({
        "open": closes.shift(1).fillna(closes.iloc[0]),
        "high": closes * (1 + spread), "low": closes * (1 - spread),
        "close": closes, "volume": 1.0,
    })


def test_all_emit_valid_signals():
    rng = np.random.default_rng(1)
    df = make_ohlcv(100 + np.cumsum(rng.normal(0, 1, 400)))
    for cls in (Donchian, VolBreakout, Supertrend, MacdMomentum):
        sig = cls().generate_signals(df)
        assert len(sig) == len(df)
        assert set(np.unique(sig)) <= {-1, 0, 1}, cls.name


def test_donchian_breaks_out_long():
    """횡보 후 신고가 돌파 → 롱."""
    closes = [100 + (i % 3) * 0.1 for i in range(40)] + list(np.linspace(102, 120, 10))
    sig = Donchian(entry_n=20, exit_n=10).generate_signals(make_ohlcv(closes, spread=0.001))
    assert sig.iloc[-1] == 1


def test_donchian_breaks_down_short():
    closes = [100 + (i % 3) * 0.1 for i in range(40)] + list(np.linspace(98, 80, 10))
    sig = Donchian(entry_n=20, exit_n=10).generate_signals(make_ohlcv(closes, spread=0.001))
    assert sig.iloc[-1] == -1


def test_vol_breakout_fires_on_surge():
    """전일 레인지 대비 큰 양봉 → 롱 시그널."""
    df = pd.DataFrame({
        "open":  [100, 100, 100.0],
        "high":  [101, 101, 110.0],
        "low":   [99, 99, 99.5],
        "close": [100, 100, 109.0],  # open 100 + 0.5*(101-99)=101 돌파
        "volume": 1.0,
    })
    sig = VolBreakout(k=0.5).generate_signals(df)
    assert sig.iloc[-1] == 1


def test_supertrend_follows_strong_trend():
    closes = list(np.linspace(100, 100, 30)) + list(np.linspace(100, 160, 40))
    sig = Supertrend(period=10, multiplier=3).generate_signals(make_ohlcv(closes, spread=0.002))
    assert sig.iloc[-1] == 1
    closes_dn = list(np.linspace(100, 100, 30)) + list(np.linspace(100, 60, 40))
    sig_dn = Supertrend(period=10, multiplier=3).generate_signals(make_ohlcv(closes_dn, spread=0.002))
    assert sig_dn.iloc[-1] == -1


def test_macd_long_in_uptrend():
    sig = MacdMomentum().generate_signals(make_ohlcv(np.linspace(100, 150, 100)))
    assert sig.iloc[-1] == 1
