"""자가학습 — 새 데이터를 반영해 전략 파라미터를 자동 재보정.

실행 시점: 러너가 매월 1일 또는 ALERT.txt 존재 시 자동 호출.

과적합 가드레일 (이 세션에서 비싸게 배운 규칙들의 코드화):
1. 탐색은 검증된 전략 패밀리 안에서만 (sma_cross 느린추세 / supertrend)
2. 채택 기준은 단일 최고값이 아니라 **고원**: 후보의 이웃 셀 중앙값 OOS > 0
3. 현재 파라미터 대비 OOS Sharpe **+0.15 이상 개선**일 때만 교체 (관성 편향)
4. 한 번의 학습에서 북당 최대 1개 파라미터셋 변경
5. 레버리지/스탑/볼타겟은 학습 대상에서 제외 (별도 고원 검증 완료된 고정값)
6. 모든 결정은 results/self_learn_history.csv에 기록 (변경 없음도 기록)
"""
import time
from pathlib import Path

import pandas as pd
import yaml

from .backtest import RESULTS_DIR, walk_forward
from .data import ROOT, fetch_data, load_config
from .risk import StopWrapped
from .strategies import SmaCross, Supertrend

HISTORY_CSV = RESULTS_DIR / "self_learn_history.csv"
IMPROVE_MARGIN = 0.15  # 현재 대비 OOS Sharpe 최소 개선폭
MARGIN_WHEN_CRITICAL = 0.05  # 드리프트 CRITICAL 시 — 열화 확인된 상태선 더 기꺼이 교체


def _current_margin() -> float:
    """드리프트 상태에 따라 교체 마진 조정 (외부 리뷰: 라이브 신호를 학습에 연결)."""
    import json
    drift_file = RESULTS_DIR / "drift_status.json"
    try:
        if json.loads(drift_file.read_text()).get("state") == "CRITICAL":
            return MARGIN_WHEN_CRITICAL
    except Exception:
        pass
    return IMPROVE_MARGIN

# 패밀리별 탐색 그리드 (검증된 영역 주변만)
GRIDS = {
    "sma_cross": [{"fast": f, "slow": s} for f in (10, 20, 30) for s in (150, 200, 250, 300)],
    "supertrend": [{"period": p, "multiplier": m} for p in (7, 10, 14, 20) for m in (1.25, 1.5, 2.0)],
}


def _build(family: str, params: dict, stop_loss: float, trailing: float):
    cls = {"sma_cross": SmaCross, "supertrend": Supertrend}[family]
    return StopWrapped(cls(**params), stop_loss, trailing)


def _neighbors(grid_results: list, target_params: dict) -> list:
    """파라미터 공간의 진짜 이웃 — 정확히 한 축에서 한 그리드 스텝 차이 (맨해튼 거리 1).

    (외부 리뷰 반영: 1차원 인덱스 근사는 2D 그리드의 기하를 반영 못함)
    """
    keys = list(target_params.keys())
    # 축별 정렬된 유니크 값으로 "한 스텝"을 정의
    axes = {k: sorted({r["params"][k] for r in grid_results}) for k in keys}

    def is_step_neighbor(p: dict) -> bool:
        diff_axes = [k for k in keys if p[k] != target_params[k]]
        if len(diff_axes) != 1:
            return False
        k = diff_axes[0]
        vals = axes[k]
        i, j = vals.index(target_params[k]), vals.index(p[k])
        return abs(i - j) == 1

    return [r for r in grid_results if is_step_neighbor(r["params"])]


def evaluate_family(df, family: str, book_cfg: dict, fee: float, slip: float,
                    wf_cfg: dict) -> list:
    """패밀리 그리드 전체의 walk-forward OOS 평가."""
    rows = []
    for params in GRIDS[family]:
        strat = _build(family, params, book_cfg["stop_loss"], book_cfg["trailing"])
        wf = walk_forward(df, strat, book_cfg["timeframe"], fee, slip,
                          wf_cfg["train_months"], wf_cfg["test_months"],
                          leverage=book_cfg["leverage"], allow_short=True,
                          funding_rate_8h=0.0001)
        rows.append({"params": params, "oos_sharpe": wf.get("oos_sharpe", float("nan"))})
    return rows


def decide(grid_results: list, current_params: dict) -> dict:
    """가드레일 적용 의사결정. 반환: {action, chosen, reason}."""
    res = sorted(grid_results, key=lambda r: r["oos_sharpe"], reverse=True)
    current = next((r for r in grid_results
                    if all(r["params"].get(k) == v for k, v in current_params.items())), None)
    cur_oos = current["oos_sharpe"] if current else float("-inf")
    best = res[0]

    if best["params"] == current_params:
        return {"action": "유지", "chosen": current_params,
                "reason": f"현재가 최적 (OOS {cur_oos:.2f})"}

    # 고원 검사: 파라미터 축 기준 이웃(맨해튼 1)의 OOS 중앙값 > 0
    nb = [r["oos_sharpe"] for r in _neighbors(grid_results, best["params"])]
    plateau_ok = len(nb) > 0 and pd.Series(nb).median() > 0

    if not plateau_ok:
        return {"action": "유지", "chosen": current_params,
                "reason": f"베스트 {best['params']}(OOS {best['oos_sharpe']:.2f})는 고립 스파이크 — 고원 검사 실패"}
    margin = _current_margin()
    if best["oos_sharpe"] < cur_oos + margin:
        return {"action": "유지", "chosen": current_params,
                "reason": f"개선폭 부족 ({best['oos_sharpe']:.2f} vs 현재 {cur_oos:.2f}, 마진 {margin})"}
    return {"action": "교체", "chosen": best["params"],
            "reason": f"OOS {cur_oos:.2f}→{best['oos_sharpe']:.2f}, 고원 통과"}


def self_learn() -> list:
    """전체 자가학습 1회 실행. 변경 시 config.yaml books 갱신."""
    cfg = load_config()
    fee, slip = cfg["backtest"]["fee_pct"], cfg["backtest"]["slippage_pct"]
    wf_cfg = cfg["walk_forward"]
    decisions = []
    changed = False

    for name, book in cfg.get("books", {}).items():
        family = book["strategy"]
        if family not in GRIDS:
            continue
        df = fetch_data(cfg["market"]["symbol"], book["timeframe"], history_days=3300)
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("datetime")
        param_keys = list(GRIDS[family][0].keys())
        current_params = {k: book[k] for k in param_keys}
        grid = evaluate_family(df, family, book, fee, slip, wf_cfg)
        d = decide(grid, current_params)
        d.update(book=name, date=time.strftime("%Y-%m-%d"))
        decisions.append(d)
        if d["action"] == "교체":
            book.update(d["chosen"])
            changed = True

    if changed:
        with open(ROOT / "config.yaml", "w") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)

    RESULTS_DIR.mkdir(exist_ok=True)
    hist = pd.DataFrame([{**d, "chosen": str(d["chosen"])} for d in decisions])
    if HISTORY_CSV.exists():
        hist = pd.concat([pd.read_csv(HISTORY_CSV), hist], ignore_index=True)
    hist.to_csv(HISTORY_CSV, index=False)
    return decisions


if __name__ == "__main__":
    for d in self_learn():
        print(d)
