"""주간 자동 재검증 — 새 데이터 반영해 채택 전략의 OOS 건강도 추적.

runner.py가 매주 일요일 자동 실행. 결과는 results/revalidation.csv에 누적.
두 북 모두 OOS Sharpe < 0이면 results/ALERT.txt 생성 (운용 재검토 신호).
"""
import time
from pathlib import Path

import pandas as pd

from .backtest import RESULTS_DIR, walk_forward
from .data import fetch_data, load_config
from .risk import StopWrapped
from .strategies import SmaCross, Supertrend

REVAL_CSV = RESULTS_DIR / "revalidation.csv"
ALERT_FILE = RESULTS_DIR / "ALERT.txt"


def revalidate() -> dict:
    cfg = load_config()
    fee = cfg["backtest"]["fee_pct"]
    slip = cfg["backtest"]["slippage_pct"]

    # 데이터 증분 갱신 후 캐시 로드
    df = fetch_data(cfg["market"]["symbol"], "1d", history_days=3300)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("datetime")

    books = {
        "sma_slow": StopWrapped(SmaCross(10, 200), 0.04, 0.08),
        "supertrend": StopWrapped(Supertrend(14, 1.5), 0.04, 0.08),
    }
    row = {"date": time.strftime("%Y-%m-%d"), "last_candle": str(df.index[-1].date())}
    for name, strat in books.items():
        wf = walk_forward(df, strat, "1d", fee, slip, 6, 1,
                          leverage=2, allow_short=True, funding_rate_8h=0.0001)
        row[f"{name}_oos_sharpe"] = wf["oos_sharpe"]
        row[f"{name}_oos_return_pct"] = wf["oos_return_pct"]

    RESULTS_DIR.mkdir(exist_ok=True)
    out = pd.DataFrame([row])
    if REVAL_CSV.exists():
        out = pd.concat([pd.read_csv(REVAL_CSV), out], ignore_index=True)
    out.to_csv(REVAL_CSV, index=False)

    degraded = (row["sma_slow_oos_sharpe"] < 0 and row["supertrend_oos_sharpe"] < 0)
    if degraded:
        ALERT_FILE.write_text(
            f"[{row['date']}] 경고: 두 북 모두 OOS Sharpe 음수 — 전략 열화 가능.\n"
            f"sma_slow={row['sma_slow_oos_sharpe']}, supertrend={row['supertrend_oos_sharpe']}\n"
            "운용 재검토 필요. LOOP.md 학습 모드로 재실험 권장.\n")
    return row


if __name__ == "__main__":
    print(revalidate())
