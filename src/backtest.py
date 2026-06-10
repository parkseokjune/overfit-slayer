"""벡터화 백테스트 엔진.

체결 모델: 시그널은 캔들 t 종가로 계산 → 포지션은 t+1 캔들에 반영(shift(1)).
포지션 변경 시 수수료+슬리피지를 그 캔들 수익률에서 차감한다.
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .data import ROOT, TIMEFRAME_MS, load_config, load_data
from .strategies import build_strategies

RESULTS_DIR = ROOT / "results"

# 연환산 계수 (캔들 수/년)
PERIODS_PER_YEAR = {"1h": 24 * 365, "4h": 6 * 365, "1d": 365}


@dataclass
class Metrics:
    total_return_pct: float
    cagr_pct: float
    sharpe: float
    sortino: float
    mdd_pct: float
    win_rate_pct: float
    profit_factor: float
    n_trades: int
    exposure_pct: float


def run_backtest(df: pd.DataFrame, signals: pd.Series, timeframe: str,
                 fee_pct: float = 0.001, slippage_pct: float = 0.0005,
                 leverage: float = 1.0, allow_short: bool = False,
                 funding_rate_8h: float = 0.0) -> pd.DataFrame:
    """시그널 → 자산 곡선 (선물 모드 지원).

    - leverage: 명목 포지션 = 자본 × leverage. 수익률/비용/펀딩비 모두 레버리지 배율 적용
    - allow_short: False면 -1 시그널을 0으로 클립 (현물)
    - 청산 모델: 보유 중 누적 손실이 증거금의 99%에 도달하면(intra-candle 저가/고가 기준)
      해당 시점 자산을 0으로 처리하고 이후 거래 중단 (isolated, 전액 증거금 가정)
    """
    out = pd.DataFrame(index=df.index)
    close = df["close"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)

    pos = signals.shift(1).fillna(0)
    if not allow_short:
        pos = pos.clip(lower=0)
    pos = pos.to_numpy(dtype=float)

    funding_per_candle = funding_rate_8h * (TIMEFRAME_MS[timeframe] / 28_800_000)

    n = len(df)
    rets = np.zeros(n)
    liquidated = False
    entry_price = 0.0
    prev_p = 0.0
    for t in range(1, n):
        p = pos[t]
        if liquidated:
            pos[t] = 0.0
            prev_p = 0.0
            continue
        ret = close[t] / close[t - 1] - 1
        cost = (fee_pct + slippage_pct) * leverage * abs(p - prev_p)
        funding = funding_per_candle * leverage * abs(p)
        rets[t] = p * leverage * ret - cost - funding

        if p != 0:
            if prev_p == 0 or np.sign(p) != np.sign(prev_p):
                entry_price = close[t - 1]
            # intra-candle 최악가 기준 증거금 소진 체크
            worst = low[t] if p > 0 else high[t]
            worst_ret = (worst / entry_price - 1) * np.sign(p)
            if worst_ret * leverage <= -0.99:
                rets[t] = -1.0  # 증거금 전액 손실
                liquidated = True
                pos[t] = 0.0
        prev_p = pos[t]

    out["position"] = pos
    out["strategy_returns"] = rets
    out["equity"] = (1 + out["strategy_returns"]).cumprod()
    out.attrs["liquidated"] = liquidated
    return out


def _trade_pnls(result: pd.DataFrame) -> list:
    """포지션 보유 구간별 손익률 목록 (롱/숏 구분, 방향 전환 = 새 트레이드)."""
    pos = result["position"].to_numpy()
    rets = result["strategy_returns"].to_numpy()
    pnls, acc = [], 1.0
    prev_sign = 0
    for p, r in zip(pos, rets):
        sign = 0 if p == 0 else (1 if p > 0 else -1)
        if sign != 0 and sign != prev_sign and prev_sign != 0:
            pnls.append(acc - 1)  # 방향 전환: 이전 트레이드 마감
            acc = 1.0
        if sign != 0:
            acc *= (1 + r)
        elif prev_sign != 0:
            pnls.append(acc - 1)
            acc = 1.0
        prev_sign = sign
    if prev_sign != 0:
        pnls.append(acc - 1)
    return pnls


def compute_metrics(result: pd.DataFrame, timeframe: str) -> Metrics:
    rets = result["strategy_returns"]
    equity = result["equity"]
    n = PERIODS_PER_YEAR[timeframe]
    years = len(rets) / n

    total = equity.iloc[-1] - 1
    cagr = (equity.iloc[-1] ** (1 / years) - 1) if years > 0 and equity.iloc[-1] > 0 else -1.0
    std = rets.std()
    sharpe = (rets.mean() / std * np.sqrt(n)) if std > 0 else 0.0
    downside = rets[rets < 0].std()
    sortino = (rets.mean() / downside * np.sqrt(n)) if downside and downside > 0 else 0.0
    mdd = (equity / equity.cummax() - 1).min()
    pnls = _trade_pnls(result)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / len(pnls) * 100 if pnls else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)

    return Metrics(
        total_return_pct=round(total * 100, 2),
        cagr_pct=round(cagr * 100, 2),
        sharpe=round(float(sharpe), 3),
        sortino=round(float(sortino), 3),
        mdd_pct=round(float(mdd) * 100, 2),
        win_rate_pct=round(win_rate, 1),
        profit_factor=round(pf, 2) if pf != float("inf") else 999.0,
        n_trades=len(pnls),
        exposure_pct=round(float((result["position"] != 0).mean()) * 100, 1),
    )


def buy_and_hold_metrics(df: pd.DataFrame, timeframe: str,
                         fee_pct: float = 0.001, slippage_pct: float = 0.0005) -> Metrics:
    sig = pd.Series(1, index=df.index)
    return compute_metrics(run_backtest(df, sig, timeframe, fee_pct, slippage_pct), timeframe)


def walk_forward(df: pd.DataFrame, strategy, timeframe: str, fee_pct: float,
                 slippage_pct: float, train_months: int = 6, test_months: int = 1,
                 **bt_kwargs) -> dict:
    """롤링 out-of-sample 검증. 각 테스트 구간 수익률을 이어붙여 OOS 성과 계산.

    파라미터 최적화 없이 고정 파라미터로 OOS 구간 성과만 본다(보수적 검증).
    """
    idx = df.index
    start, end = idx[0], idx[-1]
    test_rets = []
    windows = 0
    t0 = start + pd.DateOffset(months=train_months)
    while t0 + pd.DateOffset(months=test_months) <= end:
        t1 = t0 + pd.DateOffset(months=test_months)
        # 워밍업을 위해 테스트 구간 앞 train 데이터 포함해 시그널 생성 후 테스트 구간만 평가
        chunk = df[(idx >= t0 - pd.DateOffset(months=train_months)) & (idx < t1)]
        sig = strategy.generate_signals(chunk)
        res = run_backtest(chunk, sig, timeframe, fee_pct, slippage_pct, **bt_kwargs)
        test_rets.append(res.loc[res.index >= t0, "strategy_returns"])
        windows += 1
        t0 = t1
    if not windows:
        return {"windows": 0}
    oos = pd.concat(test_rets)
    oos_result = pd.DataFrame({
        "strategy_returns": oos,
        "position": (oos != 0).astype(int),  # 근사 (지표 계산용)
        "equity": (1 + oos).cumprod(),
    })
    m = compute_metrics(oos_result, timeframe)
    return {"windows": windows, "oos_sharpe": m.sharpe, "oos_return_pct": m.total_return_pct,
            "oos_mdd_pct": m.mdd_pct}


def main():
    cfg = load_config()
    symbol = cfg["market"]["symbol"]
    fee = cfg["backtest"]["fee_pct"]
    slip = cfg["backtest"]["slippage_pct"]
    wf_cfg = cfg["walk_forward"]
    fut = cfg.get("futures", {})
    bt_kwargs = {
        "leverage": fut.get("leverage", 1),
        "allow_short": fut.get("allow_short", False),
        "funding_rate_8h": fut.get("funding_rate_8h", 0.0),
    }
    RESULTS_DIR.mkdir(exist_ok=True)

    rows = []
    for tf in cfg["market"]["timeframes"]:
        df = load_data(symbol, tf)
        bh = buy_and_hold_metrics(df, tf, fee, slip)  # 벤치마크는 1x 현물 홀딩
        rows.append({"strategy": "buy_and_hold", "timeframe": tf, **asdict(bh)})
        for strat in build_strategies(cfg):
            sig = strat.generate_signals(df)
            res = run_backtest(df, sig, tf, fee, slip, **bt_kwargs)
            m = compute_metrics(res, tf)
            wf = walk_forward(df, strat, tf, fee, slip,
                              wf_cfg["train_months"], wf_cfg["test_months"], **bt_kwargs)
            rows.append({"strategy": strat.name, "timeframe": tf,
                         "liquidated": res.attrs.get("liquidated", False),
                         **asdict(m), **wf})

    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_DIR / "backtest_summary.csv", index=False)
    with open(RESULTS_DIR / "backtest_summary.json", "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    cols = ["strategy", "timeframe", "total_return_pct", "sharpe", "mdd_pct",
            "win_rate_pct", "n_trades", "oos_sharpe", "oos_return_pct"]
    print(out[[c for c in cols if c in out.columns]].to_string(index=False))


if __name__ == "__main__":
    main()
