"""리스크 관리(손절/트레일링) 테스트."""
import pandas as pd
import pytest

from src.risk import StopWrapped, apply_stops
from src.strategies import SmaCross


def make_ohlcv(closes, lows=None, highs=None):
    closes = pd.Series(closes, dtype=float)
    return pd.DataFrame({
        "open": closes,
        "high": pd.Series(highs, dtype=float) if highs else closes,
        "low": pd.Series(lows, dtype=float) if lows else closes,
        "close": closes, "volume": 1.0,
    })


def test_stop_loss_cuts_position():
    """-2% 손절: 가격이 entry 대비 -3% 찍으면 그 캔들부터 플랫."""
    df = make_ohlcv([100, 99, 97, 96, 95])
    raw = pd.Series([1, 1, 1, 1, 1])
    out = apply_stops(df, raw, stop_loss_pct=0.02)
    assert out.iloc[0] == 1      # 진입 (entry=100)
    assert out.iloc[2] == 0      # 97 → -3% < -2% 손절
    assert (out.iloc[2:] == 0).all()  # 원시 시그널 유지 중 재진입 금지


def test_reentry_after_raw_signal_resets():
    """스탑 후 원시 시그널이 0으로 끊겼다 다시 켜지면 재진입 허용."""
    df = make_ohlcv([100, 95, 95, 95, 100, 101])
    raw = pd.Series([1, 1, 0, 1, 1, 1])
    out = apply_stops(df, raw, stop_loss_pct=0.02)
    assert out.iloc[1] == 0      # 손절
    assert out.iloc[3] == 1      # 새 엣지에서 재진입


def test_short_stop_loss():
    """숏 포지션: 가격이 +2% 이상 오르면 손절."""
    df = make_ohlcv([100, 101, 103, 104])
    raw = pd.Series([-1, -1, -1, -1])
    out = apply_stops(df, raw, stop_loss_pct=0.02)
    assert out.iloc[0] == -1
    assert (out.iloc[2:] == 0).all()  # 103 = +3% → 손절


def test_trailing_stop_locks_profit():
    """트레일링 5%: 고점 120 대비 -5%(114) 이탈 시 청산."""
    df = make_ohlcv([100, 110, 120, 113, 112])
    raw = pd.Series([1, 1, 1, 1, 1])
    out = apply_stops(df, raw, stop_loss_pct=None, trailing_pct=0.05)
    assert out.iloc[2] == 1
    assert out.iloc[3] == 0      # 113 < 120*0.95=114


def test_wrapper_preserves_interface():
    df = make_ohlcv(list(range(100, 200)))
    w = StopWrapped(SmaCross(fast=5, slow=10), stop_loss_pct=0.02)
    sig = w.generate_signals(df)
    assert len(sig) == len(df)
    assert w.name == "sma_cross+stop"
