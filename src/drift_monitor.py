"""라이브 드리프트 모니터 — 실거래 자산곡선이 백테스트 분포에서 이탈하면 경고.

방법: 백테스트 일일수익률에서 라이브 길이와 같은 블록 부트스트랩 경로 2,000개 생성
→ 라이브 누적수익률이 그 분포의 몇 분위인지 계산.
- 5분위 미만: WARNING (전략 열화 의심 — ALERT.txt 기록)
- 1분위 미만: CRITICAL (운용 중단 검토)
표본 30일 이상이면 PSR(라이브 Sharpe > 0 확률)도 함께 보고.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import RESULTS_DIR, run_backtest
from .data import load_data
from .risk import apply_stops
from .strategies import SmaCross, Supertrend

DRIFT_FILE = RESULTS_DIR / "drift_status.json"
ALERT_FILE = RESULTS_DIR / "ALERT.txt"
EQUITY_CSV = RESULTS_DIR / "equity_history.csv"


def backtest_daily_returns() -> pd.Series:
    """현재 채택 전략(생존자 듀얼 + 볼타겟)의 백테스트 일일수익률."""
    d1 = load_data("BTC/USDT", "1d")
    realized = d1["close"].pct_change().rolling(30).std() * np.sqrt(365)
    scale = ((0.40 / realized).clip(upper=1.0).fillna(0.0) / 0.25).round() * 0.25

    def book(strat):
        sig = apply_stops(d1, strat.generate_signals(d1), 0.04, 0.08) * scale
        return run_backtest(d1, sig, "1d", 0.0005, 0.0005, leverage=2,
                            allow_short=True, funding_rate_8h=0.0001)["strategy_returns"]

    return (0.5 * book(SmaCross(10, 200)) + 0.5 * book(Supertrend(14, 1.5))).dropna()


def live_daily_returns() -> pd.Series:
    """equity_history.csv(시간당 스냅샷) → 일별 마지막 자산 → 일일수익률."""
    if not EQUITY_CSV.exists():
        return pd.Series(dtype=float)
    eq = pd.read_csv(EQUITY_CSV)
    eq["dt"] = pd.to_datetime(eq["ts"], unit="s", utc=True)
    daily = eq.set_index("dt")["equity"].resample("1D").last().dropna()
    return daily.pct_change().dropna()


def bootstrap_percentile(bt_returns: np.ndarray, live_cum: float, n_days: int,
                         n_sims: int = 2000, block: int = 5, seed: int = 7) -> float:
    """라이브 누적수익률이 백테스트 부트스트랩 분포에서 차지하는 분위(0~100)."""
    rng = np.random.default_rng(seed)
    n = len(bt_returns)
    block = min(block, max(1, n_days))
    sims = np.empty(n_sims)
    for i in range(n_sims):
        idx = rng.integers(0, n - block, size=n_days // block + 1)
        path = np.concatenate([bt_returns[j:j + block] for j in idx])[:n_days]
        sims[i] = np.prod(1 + path) - 1
    return float((sims < live_cum).mean() * 100)


def drift_check() -> dict:
    live = live_daily_returns()
    status = {"live_days": len(live)}
    if len(live) < 3:
        status["state"] = "수집 중 (3일 미만 — 판정 보류)"
        DRIFT_FILE.parent.mkdir(exist_ok=True)
        DRIFT_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2))
        return status

    bt = backtest_daily_returns().to_numpy()
    live_cum = float((1 + live).prod() - 1)
    pct = bootstrap_percentile(bt, live_cum, len(live))
    status.update(live_cum_return_pct=round(live_cum * 100, 2),
                  backtest_percentile=round(pct, 1))

    if pct < 1:
        status["state"] = "CRITICAL"
    elif pct < 5:
        status["state"] = "WARNING"
    else:
        status["state"] = "정상"

    if len(live) >= 30:
        from .stats_validation import probabilistic_sharpe_ratio
        status["psr_vs_zero"] = round(probabilistic_sharpe_ratio(live, 0.0), 3)

    if status["state"] in ("WARNING", "CRITICAL"):
        ALERT_FILE.write_text(
            f"드리프트 경고 [{status['state']}]: 라이브 {len(live)}일 누적 "
            f"{status['live_cum_return_pct']}% = 백테스트 분포의 {pct:.1f}분위.\n"
            "전략 열화 또는 체결 괴리 의심 — 재학습/축소 검토.\n")

    DRIFT_FILE.parent.mkdir(exist_ok=True)
    DRIFT_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    print(json.dumps(drift_check(), ensure_ascii=False, indent=2))
