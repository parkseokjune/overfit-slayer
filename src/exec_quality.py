"""체결 품질 집계 (DESIGN_NEXT #1) — paper_trades.csv의 원장 컬럼을 30일 윈도우로 요약."""
import time

import pandas as pd

from .backtest import RESULTS_DIR

TRADES_CSV = RESULTS_DIR / "paper_trades.csv"
SLIP_LIMIT_BPS = 10.0   # 백테스트 가정(5bps)의 2배
MAKER_MIN_RATE = 0.5


def summary(days: int = 30) -> dict:
    if not TRADES_CSV.exists():
        return {"n": 0, "status": "미계측 (체결 0건)"}
    t = pd.read_csv(TRADES_CSV)
    t = t[t["ts"] >= time.time() - days * 86400]
    live = t[t.get("order_type", pd.Series(dtype=str)).notna()] if "order_type" in t else pd.DataFrame()
    if len(live) < 1:
        return {"n": 0, "status": f"미계측 (최근 {days}일 체결 0건)"}
    slip = pd.to_numeric(live.get("slippage_bps"), errors="coerce").dropna()
    types = live["order_type"].astype(str)
    maker_rate = float((types == "maker").mean())
    out = {
        "n": int(len(live)),
        "avg_slippage_bps": round(float(slip.mean()), 2) if len(slip) else None,
        "worst_slippage_bps": round(float(slip.max()), 2) if len(slip) else None,
        "maker_rate": round(maker_rate, 2),
        "fallback_rate": round(float((types == "market_fallback").mean()), 2),
    }
    ok = ((out["avg_slippage_bps"] is None or out["avg_slippage_bps"] < SLIP_LIMIT_BPS)
          and (len(live) < 10 or maker_rate > MAKER_MIN_RATE))
    out["status"] = "✅ 기준 내" if ok else "⚠ 기준 위반 (슬리피지/maker율 점검)"
    return out
