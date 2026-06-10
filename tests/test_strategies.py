"""전략 단위 테스트 — 합성 데이터로 시그널 로직 검증."""
import numpy as np
import pandas as pd
import pytest

from src.strategies import ALL_STRATEGIES, BbBreakout, RsiMeanRevert, SmaCross


def make_ohlcv(closes):
    closes = pd.Series(closes, dtype=float)
    return pd.DataFrame({
        "open": closes, "high": closes * 1.01, "low": closes * 0.99,
        "close": closes, "volume": 1.0,
    })


def test_signals_only_valid_values():
    """모든 전략의 시그널은 {-1, 0, 1} 안에 있어야 한다."""
    rng = np.random.default_rng(42)
    df = make_ohlcv(100 + np.cumsum(rng.normal(0, 1, 500)))
    for cls in ALL_STRATEGIES.values():
        sig = cls().generate_signals(df)
        assert len(sig) == len(df)
        assert set(sig.unique()) <= {-1, 0, 1}, cls.name


def test_sma_cross_uptrend_goes_long():
    """일관된 상승 추세에선 후반부에 롱이어야 한다."""
    df = make_ohlcv(np.linspace(100, 200, 300))
    sig = SmaCross(fast=10, slow=30).generate_signals(df)
    assert sig.iloc[-1] == 1
    assert sig.iloc[:29].eq(0).all()  # 워밍업 구간(slow-1 캔들)은 현금


def test_sma_cross_invalid_params():
    with pytest.raises(ValueError):
        SmaCross(fast=60, slow=20)


def test_rsi_buys_after_crash_exits_on_recovery():
    """급락(과매도) 후 진입, 반등(RSI>=50) 후 청산."""
    closes = list(np.linspace(100, 100, 50)) + list(np.linspace(100, 60, 30)) \
             + list(np.linspace(60, 95, 40))
    sig = RsiMeanRevert(period=14, oversold=30).generate_signals(make_ohlcv(closes))
    assert (sig == 1).any()          # 급락 구간에서 롱 진입했고
    assert sig.iloc[-1] != 1         # 회복 후 롱은 청산됨 (강한 랠리 끝 과매수 숏은 허용)
    entry = sig.idxmax()
    assert entry >= 50               # 진입은 급락 시작 이후


def test_bb_breakout_enters_on_spike():
    """횡보 후 급등하면 상단 돌파로 진입해야 한다."""
    closes = [100 + 0.1 * (i % 5) for i in range(60)] + list(np.linspace(101, 130, 20))
    sig = BbBreakout(period=20, std=2.0).generate_signals(make_ohlcv(closes))
    assert sig.iloc[-1] == 1
    assert sig.iloc[:60].eq(0).all()


def test_warmup_period_is_flat():
    """지표 워밍업(NaN) 구간에선 포지션이 없어야 한다."""
    rng = np.random.default_rng(0)
    df = make_ohlcv(100 + np.cumsum(rng.normal(0, 1, 200)))
    assert SmaCross(fast=20, slow=60).generate_signals(df).iloc[:59].eq(0).all()
    assert BbBreakout(period=20).generate_signals(df).iloc[:19].eq(0).all()
