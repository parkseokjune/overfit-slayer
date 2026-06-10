"""실험 하네스 — 전략×레버리지×스탑 조합을 백테스트+walk-forward로 평가.

결과는 results/experiments.csv에 누적. 채택 기준(LOOP.md):
OOS Sharpe > 0 이면서 B&H(1x) Sharpe 초과, 청산 없음.
"""
import itertools
from dataclasses import asdict

import pandas as pd

from .backtest import (RESULTS_DIR, buy_and_hold_metrics, compute_metrics,
                       run_backtest, walk_forward)
from .data import load_config, load_data
from .risk import StopWrapped
from .strategies import build_strategies

EXPERIMENTS_CSV = RESULTS_DIR / "experiments.csv"


def evaluate(df, strategy, tf, fee, slip, leverage, allow_short, funding,
             wf_cfg) -> dict:
    kw = {"leverage": leverage, "allow_short": allow_short,
          "funding_rate_8h": funding}
    sig = strategy.generate_signals(df)
    res = run_backtest(df, sig, tf, fee, slip, **kw)
    m = compute_metrics(res, tf)
    wf = walk_forward(df, strategy, tf, fee, slip,
                      wf_cfg["train_months"], wf_cfg["test_months"], **kw)
    return {"strategy": strategy.name, "timeframe": tf, "leverage": leverage,
            "params": str(strategy.params),
            "liquidated": res.attrs.get("liquidated", False),
            **asdict(m), **wf}


def append_results(rows: list, experiment: str, date: str):
    df = pd.DataFrame(rows)
    df.insert(0, "date", date)
    df.insert(1, "experiment", experiment)
    RESULTS_DIR.mkdir(exist_ok=True)
    if EXPERIMENTS_CSV.exists():
        old = pd.read_csv(EXPERIMENTS_CSV)
        df = pd.concat([old, df], ignore_index=True)
    df.to_csv(EXPERIMENTS_CSV, index=False)


def sweep_leverage_and_stops(date: str, timeframes=("4h", "1d"),
                             leverages=(1, 2, 3), stops=(None, 0.02, 0.05),
                             trailing=(None, 0.08)):
    """레버리지·손절·트레일링 그리드 스윕. 1h는 베이스라인에서 전멸이라 제외."""
    cfg = load_config()
    fee = cfg["backtest"]["fee_pct"]
    slip = cfg["backtest"]["slippage_pct"]
    fut = cfg["futures"]
    wf_cfg = cfg["walk_forward"]

    rows = []
    for tf in timeframes:
        df = load_data(cfg["market"]["symbol"], tf)
        for base, lev, sl, tr in itertools.product(
                build_strategies(cfg), leverages, stops, trailing):
            strat = StopWrapped(base, sl, tr) if (sl or tr) else base
            r = evaluate(df, strat, tf, fee, slip, lev,
                         fut["allow_short"], fut["funding_rate_8h"], wf_cfg)
            r["stop_loss"] = sl
            r["trailing"] = tr
            rows.append(r)
    append_results(rows, "leverage_stop_sweep", date)
    return pd.DataFrame(rows)


def main():
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    out = sweep_leverage_and_stops(date)
    # 채택 후보: 청산 없고 OOS Sharpe 양수, 정렬해서 상위 출력
    ok = out[(~out["liquidated"]) & (out["oos_sharpe"] > 0)]
    cols = ["strategy", "timeframe", "leverage", "stop_loss", "trailing",
            "total_return_pct", "sharpe", "mdd_pct", "oos_sharpe", "oos_return_pct"]
    print(f"전체 {len(out)}개 조합 중 OOS Sharpe>0 & 청산없음: {len(ok)}개")
    if len(ok):
        print(ok.sort_values("oos_sharpe", ascending=False)[cols].head(15).to_string(index=False))
    else:
        print("통과 조합 없음 — 상위 5개(OOS 기준):")
        print(out.sort_values("oos_sharpe", ascending=False)[cols].head(5).to_string(index=False))


if __name__ == "__main__":
    main()
