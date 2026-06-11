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
    """현재 채택 전략의 백테스트 일일수익률 — config.yaml books에서 동적 구성.

    (외부 리뷰 지적 반영: 하드코딩 시 자가학습이 config를 바꾸면 드리프트 기준
    분포가 실운용 전략과 어긋남 — 단일 진실 원천 = books)
    """
    from .data import load_config
    books = load_config().get("books", {})
    d1 = load_data("BTC/USDT", "1d")
    realized = d1["close"].pct_change().rolling(30).std() * np.sqrt(365)

    parts = []
    for b in books.values():
        if b["strategy"] == "sma_cross":
            strat = SmaCross(b["fast"], b["slow"])
        elif b["strategy"] == "supertrend":
            strat = Supertrend(b["period"], b["multiplier"])
        else:
            from .strategies import BbBreakout
            strat = BbBreakout(b["period"], b["std"])
        scale = ((b.get("vol_target", 0.40) / realized).clip(upper=1.0).fillna(0.0)
                 / 0.25).round() * 0.25
        raw = strat.generate_signals(d1)
        if b.get("long_only"):
            raw = raw.clip(lower=0)
        sig = apply_stops(d1, raw, b["stop_loss"], b["trailing"]) * scale
        r = run_backtest(d1, sig, b["timeframe"], 0.0005, 0.0005,
                         leverage=b["leverage"], allow_short=True,
                         funding_rate_8h=0.0001)["strategy_returns"]
        parts.append(b["weight"] * r)
    return sum(parts).dropna()


def live_daily_returns() -> tuple:
    """equity_history 스냅샷 → 현재 epoch의 일일수익률 + (사용/제외 표본수).

    epoch 경계는 paper_state.json의 epoch_start(장부 리셋 시 명시 기록)로 판정.
    점프 크기 추론을 쓰지 않으므로 실제 폭락일이 오인 제외될 수 없다 (외부 리뷰 반영).
    """
    if not EQUITY_CSV.exists():
        return pd.Series(dtype=float), 0
    eq = pd.read_csv(EQUITY_CSV)
    total = len(eq)
    epoch = 0
    state_file = RESULTS_DIR / "paper_state.json"
    try:
        epoch = json.loads(state_file.read_text()).get("epoch_start", 0)
    except Exception:
        pass
    eq = eq[eq["ts"] >= epoch]
    excluded = total - len(eq)
    eq["dt"] = pd.to_datetime(eq["ts"], unit="s", utc=True)
    daily = eq.set_index("dt")["equity"].resample("1D").last().dropna()
    return daily.pct_change().dropna(), excluded


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
    live, excluded = live_daily_returns()
    status = {"live_days": len(live), "excluded_snapshots": excluded}
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
    # 이력 누적 — 월간 점검("최근 30일 CRITICAL 반복")의 근거 데이터
    import time as _t
    hist = RESULTS_DIR / "drift_history.csv"
    line = f"{int(_t.time())},{status.get('live_days',0)},{status.get('backtest_percentile','')},{status.get('state','')}\n"
    if not hist.exists():
        hist.write_text("ts,live_days,percentile,state\n" + line)
    else:
        with open(hist, "a") as f:
            f.write(line)
    return status


if __name__ == "__main__":
    print(json.dumps(drift_check(), ensure_ascii=False, indent=2))
