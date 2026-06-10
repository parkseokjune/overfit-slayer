"""백테스트 엔진 정확성 테스트 — 손계산 값과 대조."""
import numpy as np
import pandas as pd
import pytest

from src.backtest import compute_metrics, run_backtest


def make_df(closes):
    closes = pd.Series(closes, dtype=float)
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": 1.0,
    })


def test_no_lookahead_next_candle_execution():
    """t에 시그널 → t+1 수익률부터 반영. 마지막 캔들 시그널은 수익에 영향 없음."""
    df = make_df([100, 100, 100, 200])  # 마지막 캔들 +100%
    sig = pd.Series([0, 0, 0, 1])       # 마지막 캔들에서야 진입 시그널
    res = run_backtest(df, sig, "1d", fee_pct=0, slippage_pct=0)
    assert res["equity"].iloc[-1] == pytest.approx(1.0)  # 체결 기회 없음 → 수익 0


def test_full_long_equals_market_return():
    """수수료 0, 항상 롱이면 시장 수익률과 같아야 한다(첫 캔들 제외)."""
    df = make_df([100, 110, 121, 133.1])
    sig = pd.Series([1, 1, 1, 1])
    res = run_backtest(df, sig, "1d", fee_pct=0, slippage_pct=0)
    # t=0 종가 시그널 → t=1 시초가(≈t=0 종가 100)에 체결 → 100→133.1 전체 획득
    assert res["equity"].iloc[-1] == pytest.approx(133.1 / 100)


def test_costs_charged_on_position_change():
    """진입 1회 + 청산 1회 = 비용 2회 차감."""
    df = make_df([100] * 6)  # 가격 변동 없음 → 비용만 남음
    sig = pd.Series([0, 1, 1, 0, 0, 0])
    fee, slip = 0.001, 0.0005
    res = run_backtest(df, sig, "1d", fee_pct=fee, slippage_pct=slip)
    expected = (1 - (fee + slip)) ** 2
    assert res["equity"].iloc[-1] == pytest.approx(expected)


def test_short_signals_ignored_for_spot():
    """현물 모드: -1 시그널은 0으로 취급."""
    df = make_df([100, 90, 80, 70])
    sig = pd.Series([-1, -1, -1, -1])
    res = run_backtest(df, sig, "1d", fee_pct=0, slippage_pct=0)
    assert res["equity"].iloc[-1] == pytest.approx(1.0)


def test_mdd_calculation():
    """100→200→100 자산곡선의 MDD는 -50%."""
    df = make_df([100, 200, 100])
    sig = pd.Series([1, 1, 1])
    res = run_backtest(df, sig, "1d", fee_pct=0, slippage_pct=0)
    m = compute_metrics(res, "1d")
    assert m.mdd_pct == pytest.approx(-50.0)


def test_win_rate_and_trades():
    """승 1, 패 1 → 승률 50%, 트레이드 2회."""
    df = make_df([100, 100, 110, 110, 110, 100, 100])
    sig = pd.Series([1, 1, 0, 1, 1, 0, 0])
    # 트레이드1: 100→110 진입~청산 = +10% / 트레이드2: 110→100 = -9.1%
    res = run_backtest(df, sig, "1d", fee_pct=0, slippage_pct=0)
    m = compute_metrics(res, "1d")
    assert m.n_trades == 2
    assert m.win_rate_pct == pytest.approx(50.0)


# ---------- 선물 모드 (레버리지/숏/펀딩/청산) ----------

def test_leverage_multiplies_returns():
    """2x 레버리지, 항상 롱, 비용 0 → 캔들 수익률이 2배 복리."""
    df = make_df([100, 110, 121])
    sig = pd.Series([1, 1, 1])
    res = run_backtest(df, sig, "1d", fee_pct=0, slippage_pct=0, leverage=2)
    assert res["equity"].iloc[-1] == pytest.approx(1.2 * 1.2)


def test_short_profits_in_downtrend():
    """allow_short=True에서 숏은 하락장에 수익."""
    df = make_df([100, 90, 81])
    sig = pd.Series([-1, -1, -1])
    res = run_backtest(df, sig, "1d", fee_pct=0, slippage_pct=0,
                       leverage=1, allow_short=True)
    assert res["equity"].iloc[-1] == pytest.approx(1.1 * 1.1)


def test_liquidation_wipes_account():
    """10x 레버리지에서 -10% 하락 → 청산, 자산 0, 이후 거래 중단."""
    closes = pd.Series([100.0, 100.0, 89.0, 120.0, 150.0])
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes,
                       "close": closes, "volume": 1.0})
    sig = pd.Series([1, 1, 1, 1, 1])
    res = run_backtest(df, sig, "1d", fee_pct=0, slippage_pct=0, leverage=10)
    assert res.attrs["liquidated"] is True
    assert res["equity"].iloc[-1] == pytest.approx(0.0)  # 반등해도 복구 불가
    assert (res["position"].iloc[3:] == 0).all()


def test_intracandle_low_triggers_liquidation():
    """종가는 멀쩡해도 저가가 청산가를 건드리면 청산."""
    df = pd.DataFrame({
        "open":  [100.0, 100.0, 100.0],
        "high":  [100.0, 101.0, 101.0],
        "low":   [100.0, 89.0, 100.0],   # 두 번째 캔들 저가 -11%
        "close": [100.0, 100.0, 101.0],
        "volume": 1.0,
    })
    sig = pd.Series([1, 1, 1])
    res = run_backtest(df, sig, "1d", fee_pct=0, slippage_pct=0, leverage=10)
    assert res.attrs["liquidated"] is True


def test_funding_cost_applied_while_holding():
    """포지션 보유 중 펀딩비 차감 (1d 캔들 = 8h×3 = 펀딩 3회분)."""
    df = make_df([100] * 4)
    sig = pd.Series([1, 1, 1, 1])
    res = run_backtest(df, sig, "1d", fee_pct=0, slippage_pct=0,
                       leverage=1, funding_rate_8h=0.0001)
    per_candle = 0.0001 * 3
    assert res["equity"].iloc[-1] == pytest.approx((1 - per_candle) ** 3)


def test_long_short_flip_costs_double_turnover():
    """롱(+1)→숏(-1) 전환은 턴오버 2 → 비용 2배."""
    df = make_df([100] * 4)
    fee = 0.001
    sig = pd.Series([1, -1, -1, -1])
    res = run_backtest(df, sig, "1d", fee_pct=fee, slippage_pct=0,
                       leverage=1, allow_short=True)
    # 진입(턴오버1) + 플립(턴오버2) = 비용 3단위
    assert res["equity"].iloc[-1] == pytest.approx((1 - fee) * (1 - 2 * fee))
