"""90일 관측 종료 체크리스트 자동 평가 (운영 규칙서 docs/OPERATIONS.md §체크리스트).

사용: python -m src.gate_check → 5개 부문 합격/불합격 리포트.
전 부문 통과 시에만 자가학습 제한적 교체(B규칙) 단계로 진입할 자격이 생긴다.
"""
import json
import time

import pandas as pd

from .backtest import RESULTS_DIR


def check() -> dict:
    out = {}
    state = json.loads((RESULTS_DIR / "paper_state.json").read_text()) if (RESULTS_DIR / "paper_state.json").exists() else {}
    drift = json.loads((RESULTS_DIR / "drift_status.json").read_text()) if (RESULTS_DIR / "drift_status.json").exists() else {}
    eq = pd.read_csv(RESULTS_DIR / "equity_history.csv") if (RESULTS_DIR / "equity_history.csv").exists() else pd.DataFrame()

    live_days = (time.time() - state.get("epoch_start", time.time())) / 86400
    out["1.데이터 충분성"] = {
        "라이브 90일+": live_days >= 90,
        "일별 곡선 확보": drift.get("live_days", 0) >= 80,
        "드리프트 30일+ 연속": drift.get("live_days", 0) >= 30,
        "_라이브일수": round(live_days, 1),
    }
    out["2.체결 정합성"] = {
        "포지션 불일치 없음": not state.get("recon_block", False),
        "잔고 정상": state.get("recon") not in ("EMPTY_BALANCE",),
        "중단 상태 아님": not state.get("halted", False),
    }
    psr = drift.get("psr_vs_zero")
    pct = drift.get("backtest_percentile")
    out["3.성과 신뢰성"] = {
        "PSR > 0.5": (psr or 0) > 0.5,
        "드리프트 분위 ≥ 25%": (pct or 0) >= 25,
        "CRITICAL 아님": drift.get("state") != "CRITICAL",
        "_PSR": psr, "_분위": pct,
    }
    trades = pd.read_csv(RESULTS_DIR / "paper_trades.csv") if (RESULTS_DIR / "paper_trades.csv").exists() else pd.DataFrame()
    if len(eq):
        peak = eq["equity"].cummax()
        mdd = float(((eq["equity"] / peak) - 1).min())
    else:
        mdd = 0.0
    out["4.포트폴리오 건전성"] = {
        "라이브 MDD > -40%": mdd > -0.40,
        "_라이브MDD%": round(mdd * 100, 1),
        "_체결수": len(trades),
    }
    sl_hist = RESULTS_DIR / "self_learn_history.csv"
    out["5.운영 안정성"] = {
        "핵심 파일 생성됨": all((RESULTS_DIR / f).exists() for f in
                          ("paper_state.json", "equity_history.csv", "drift_status.json")),
        "자가학습 기록 정상": sl_hist.exists(),
    }

    all_pass = all(v for sec in out.values() for k, v in sec.items() if not k.startswith("_"))
    out["판정"] = "✅ 게이트 통과 — B규칙(제한적 교체) 자격" if all_pass else "⛔ 미통과 — 관측/보수 유지"
    return out


if __name__ == "__main__":
    print(json.dumps(check(), ensure_ascii=False, indent=2, default=str))
