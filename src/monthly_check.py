"""월간 운영 체크리스트 자동 점검 (docs/OPERATIONS.md §월간).

원칙: "매달 바꾸는 시스템이 아니라 매달 확인하는 시스템" — 점검 목적은 교체가 아니라
교체해도 되는지 확인. 매월 1일 러너가 자가학습 직전에 실행, 보고서를 results/에 남긴다.
사용: python -m src.monthly_check
"""
import json
import time

import pandas as pd

from .backtest import RESULTS_DIR


def _load(name, default=None):
    p = RESULTS_DIR / name
    try:
        return json.loads(p.read_text()) if name.endswith(".json") else pd.read_csv(p)
    except Exception:
        return default


def check() -> dict:
    now = time.time()
    state = _load("paper_state.json", {}) or {}
    drift = _load("drift_status.json", {}) or {}
    eq = _load("equity_history.csv", pd.DataFrame())
    dh = _load("drift_history.csv", pd.DataFrame())
    out = {}

    # 1. 데이터 무결성
    recent = eq[eq["ts"] >= now - 30*86400] if len(eq) else pd.DataFrame()
    max_gap_h = (recent["ts"].diff().max() / 3600) if len(recent) > 1 else None
    out["1.데이터 무결성"] = {
        "30일 곡선 결측 없음(최대 공백<48h)": bool(max_gap_h is not None and max_gap_h < 48),
        "핵심 파일 누적": all((RESULTS_DIR / f).exists() for f in
                         ("equity_history.csv", "drift_status.json", "paper_state.json")),
        "epoch/이벤트 기록": "epoch_start" in state,
        "_최대공백(시간)": round(max_gap_h, 1) if max_gap_h else None,
    }
    # 2. 체결 품질
    out["2.체결 품질"] = {
        "포지션 정합": not state.get("recon_block", False),
        "잔고 정상": state.get("recon") != "EMPTY_BALANCE",
        "중단 아님": not state.get("halted", False),
        "_maker비중/슬리피지": "미계측 (체결 누적 후 측정 — 백로그)",
    }
    # 3. 성과 상태
    crit_30d = 0
    if len(dh):
        crit_30d = int((dh[dh["ts"] >= now - 30*86400]["state"] == "CRITICAL").sum())
    out["3.성과 상태"] = {
        "PSR>0.5 (30일+부터)": (drift.get("psr_vs_zero") or 0) > 0.5 if drift.get("psr_vs_zero") is not None else "데이터 부족",
        "드리프트 분위≥25%": (drift.get("backtest_percentile") or 0) >= 25 if drift.get("backtest_percentile") is not None else "데이터 부족",
        "30일 내 CRITICAL 없음": crit_30d == 0,
    }
    # 4. 포트폴리오 구조
    if len(eq):
        peak = eq["equity"].cummax()
        live_mdd = float(((eq["equity"] / peak) - 1).min())
    else:
        live_mdd = 0.0
    books = state.get("books", {})
    out["4.포트폴리오 구조"] = {
        "라이브 MDD>-40%": live_mdd > -0.40,
        "_라이브MDD%": round(live_mdd*100, 1),
        "_북 잔고": {k: round(v.get("balance", 0)) for k, v in books.items()},
    }
    # 5. 자가학습 판단 (정책 상태 — 실제 차단은 self_learn._policy_block이 수행)
    live_days = (now - state.get("epoch_start", now)) / 86400
    out["5.자가학습 판단"] = {
        "라이브일수": round(live_days, 1),
        "현재 단계": ("관측 모드 (90일 미만 — 교체 금지)" if live_days < 90
                   else "B규칙 (드리프트 WARNING 이상에서만 교체 검토)"),
        "드리프트": drift.get("state", "?"),
    }

    hard = [v for sec in ("1.데이터 무결성", "2.체결 품질") for k, v in out[sec].items()
            if isinstance(v, bool)]
    out["판정"] = "✅ 생존 점검 통과" if all(hard) else "⛔ 운영 이상 — 복구 우선 (학습 보류)"
    return out


def save_report() -> str:
    r = check()
    name = f"monthly_report_{time.strftime('%Y-%m')}.json"
    (RESULTS_DIR / name).write_text(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    return r["판정"]


if __name__ == "__main__":
    print(json.dumps(check(), ensure_ascii=False, indent=2, default=str))
