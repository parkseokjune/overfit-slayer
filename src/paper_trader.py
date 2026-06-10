"""페이퍼 트레이딩 — Binance USDT-M 선물 테스트넷 (키 없으면 dry-run 시뮬레이션).

가드레일: set_sandbox_mode(True) 강제. 실거래소 엔드포인트로는 절대 주문하지 않는다.

사이클(run_once):
1. 최신 캔들 갱신 → 채택 전략 시그널 계산 (레짐 필터 + 스탑 적용)
2. 목표 포지션과 현재 포지션 비교 → 차이만큼 주문 (시장가)
3. 상태/거래 기록 저장 (results/paper_state.json, results/paper_trades.csv)
"""
import csv
import json
import os
import time
from pathlib import Path

import ccxt
import pandas as pd
from dotenv import load_dotenv

from .ai_analyst import apply_regime_filter
from .backtest import RESULTS_DIR
from .data import ROOT, fetch_data, load_config
from .risk import apply_stops
from .strategies import RsiMeanRevert, SmaCross, Supertrend

load_dotenv(ROOT / ".env")

STATE_FILE = RESULTS_DIR / "paper_state.json"
TRADES_CSV = RESULTS_DIR / "paper_trades.csv"

# 채택: 9년 풀히스토리 생존자 듀얼 (STATE.md, 2026-06-11 교체)
# 직전 채택(sma20/150+rsi)은 2024-26 과적합으로 판명(9y -27%) → 전 레짐 생존자로 교체
# 9y: +153%, CAGR 11.1%, Sharpe 0.47, MDD -51%, 9년 중 8년 양수 (상관 0.09)
BOOKS = {
    "sma_slow": {"weight": 0.5, "timeframe": "1d", "leverage": 2,
                 "strategy": "sma_cross", "fast": 10, "slow": 200,
                 "stop_loss": 0.04, "trailing": 0.08, "regime_filter": False,
                 "vol_target": 0.40},  # 스탑고원 재검증: (4%,8%)이 Sharpe 0.92/MDD -30%
    "supertrend": {"weight": 0.5, "timeframe": "1d", "leverage": 2,
                   "strategy": "supertrend", "period": 14, "multiplier": 1.5,
                   "stop_loss": 0.04, "trailing": 0.08, "regime_filter": False,
                   "vol_target": 0.40},  # mult 1.5 열이 전 period 견고 (OOS 0.56~0.70)
}
VOL_STEP = 0.25  # 분수 포지션 계단화 (리밸런스 churn 축소)
INITIAL_BALANCE = 10_000.0
KILL_SWITCH_DD = 0.15  # 자산 고점 대비 -15% → 전 포지션 청산 후 거래 중단 (수동 해제)
EQUITY_CSV = RESULTS_DIR / "equity_history.csv"


def make_testnet_exchange():
    """테스트넷 키가 있으면 sandbox 선물 거래소, 없으면 None (dry-run)."""
    key = os.environ.get("BINANCE_TESTNET_KEY")
    secret = os.environ.get("BINANCE_TESTNET_SECRET")
    if not key or not secret:
        return None
    ex = ccxt.binanceusdm({"apiKey": key, "secret": secret,
                           "enableRateLimit": True})
    # 가드레일: 데모 트레이딩 강제 (구 선물 테스트넷은 ccxt에서 폐기됨)
    ex.enable_demo_trading(True)
    return ex


def _fresh_book(weight: float) -> dict:
    return {"balance": INITIAL_BALANCE * weight, "position": 0,
            "entry_price": None, "qty": 0.0}


def load_state() -> dict:
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        if "books" in state:
            return state
    # 신규 또는 구버전(단일 북) → 듀얼 북으로 초기화
    return {"mode": None, "cycles": 0,
            "books": {name: _fresh_book(b["weight"]) for name, b in BOOKS.items()}}


def save_state(state: dict):
    RESULTS_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def record_trade(row: dict):
    RESULTS_DIR.mkdir(exist_ok=True)
    exists = TRADES_CSV.exists()
    with open(TRADES_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not exists:
            w.writeheader()
        w.writerow(row)


def compute_target_signal(symbol: str, book_name: str) -> dict:
    """최신 데이터로 해당 북 전략의 목표 포지션(-1/0/1) 계산."""
    b = BOOKS[book_name]
    df = fetch_data(symbol, b["timeframe"])
    if b["strategy"] == "sma_cross":
        raw = SmaCross(fast=b["fast"], slow=b["slow"]).generate_signals(df)
    elif b["strategy"] == "supertrend":
        raw = Supertrend(period=b["period"],
                         multiplier=b["multiplier"]).generate_signals(df)
    else:
        raw = RsiMeanRevert(period=b["period"], oversold=b["oversold"],
                            overbought=b["overbought"]).generate_signals(df)
    if b["regime_filter"]:
        raw = apply_regime_filter(df, raw, 100)
    sig = apply_stops(df, raw, b["stop_loss"], b["trailing"])
    target = float(sig.iloc[-1])
    if b.get("long_only") and target < 0:
        target = 0.0
    if b.get("vol_target"):
        import numpy as np
        ppy = {"1h": 24 * 365, "4h": 6 * 365, "1d": 365}[b["timeframe"]]
        realized = float(df["close"].pct_change().rolling(30).std().iloc[-1]) * np.sqrt(ppy)
        scale = min(1.0, b["vol_target"] / realized) if realized > 0 else 0.0
        target = round(target * scale / VOL_STEP) * VOL_STEP
    last_close = float(df["close"].iloc[-1])
    return {"target": target, "price": last_close,
            "candle_ts": int(df["timestamp"].iloc[-1])}


def mark_to_market(state: dict, price: float) -> float:
    """현재 포지션 평가손익 반영한 자산."""
    if state["position"] == 0 or not state["entry_price"]:
        return state["balance"]
    direction = 1 if state["position"] > 0 else -1  # qty에 분수 반영됨, 부호만
    pnl = state["qty"] * (price - state["entry_price"]) * direction
    return state["balance"] + pnl


def execute_dry_run(state: dict, target: int, price: float, leverage: int,
                    book: str = "") -> dict:
    """로컬 시뮬레이션 체결 — 종가 기준, 수수료 0.05%+슬리피지 0.05%."""
    cost_rate = 0.001
    if state["position"] != 0:  # 기존 포지션 청산
        direction = 1 if state["position"] > 0 else -1
        pnl = state["qty"] * (price - state["entry_price"]) * direction
        notional = state["qty"] * price
        state["balance"] += pnl - notional * cost_rate
        record_trade({"ts": int(time.time()), "mode": "dry_run", "book": book,
                      "side": "close", "position": state["position"], "price": price,
                      "qty": state["qty"], "pnl": round(pnl, 2),
                      "balance": round(state["balance"], 2)})
        state.update(position=0, entry_price=None, qty=0.0)
    if target != 0 and state["balance"] > 0:  # 신규 진입 (분수 포지션 = 명목 축소)
        notional = state["balance"] * leverage * abs(target)
        qty = notional / price
        state["balance"] -= notional * cost_rate
        state.update(position=target, entry_price=price, qty=qty)
        record_trade({"ts": int(time.time()), "mode": "dry_run", "book": book,
                      "side": "open", "position": target, "price": price,
                      "qty": round(qty, 6), "pnl": 0.0,
                      "balance": round(state["balance"], 2)})
    return state


FUTURES_SYMBOL = "BTC/USDT:USDT"  # binanceusdm 무기한 unified 심볼
MIN_NOTIONAL = 100  # Binance BTCUSDT 선물 최소 주문 명목가 (USDT)


def execute_testnet(ex, state: dict, target: float, symbol: str,
                    price: float, leverage: int, book: str = "") -> dict:
    """테스트넷 실주문 — 북별 가상 잔고 비례 수량을 시장가로 체결.

    심볼이 하나라 거래소 계정에는 북들의 순노출이 합산되어 잡힌다.
    북별 회계는 로컬 state로 유지하고, 거래소엔 델타만 반영한다.
    """
    fsym = FUTURES_SYMBOL
    ex.load_markets()
    try:
        ex.set_leverage(leverage, fsym)
    except Exception:
        pass  # 이미 설정돼 있으면 거래소가 에러를 줄 수 있음 — 무해
    # 이 북의 현재 로컬 포지션 수량(부호 포함)과 목표 수량의 델타만 주문
    current_qty = state["qty"] * (1 if state["position"] > 0 else -1 if state["position"] < 0 else 0)
    target_qty = target * state["balance"] * leverage / price
    delta = target_qty - current_qty
    if abs(delta) * price < MIN_NOTIONAL:
        return state  # 최소 명목가 미만 — 스킵 (다음 사이클에 재시도)
    amount = float(ex.amount_to_precision(fsym, abs(delta)))
    if amount <= 0:
        return state
    side = "buy" if delta > 0 else "sell"
    order = ex.create_order(fsym, "market", side, amount)
    fill = float(order.get("average") or price)
    record_trade({"ts": int(time.time()), "mode": "testnet", "book": book,
                  "side": side, "position": target, "price": fill,
                  "qty": amount, "pnl": "",
                  "balance": round(state["balance"], 2)})
    state.update(position=target, entry_price=fill if target != 0 else None,
                 qty=abs(target_qty) if target != 0 else 0.0)
    return state


def run_once() -> dict:
    cfg = load_config()
    symbol = cfg["market"]["symbol"]
    state = load_state()
    ex = make_testnet_exchange()
    state["mode"] = "testnet" if ex else "dry_run"

    actions, price = {}, None
    halted = state.get("halted", False)
    for name, bcfg in BOOKS.items():
        book = state["books"][name]
        info = compute_target_signal(symbol, name)
        target, price = info["target"], info["price"]
        if halted:
            target = 0  # 킬스위치 발동 중: 청산만 허용
        if target != book["position"]:
            if ex:
                # 테스트넷: 북별 증거금 비례 수량으로 주문 (심볼 단일이라 순노출 합산됨)
                execute_testnet(ex, book, target, symbol, price,
                                bcfg["leverage"], book=name)
            else:
                execute_dry_run(book, target, price, bcfg["leverage"], book=name)
            actions[name] = f"→ {target}"
        else:
            actions[name] = f"유지({book['position']})"

    state["cycles"] += 1
    state["last_run"] = int(time.time())
    state["last_price"] = price
    state["equity"] = round(sum(mark_to_market(b, price)
                                for b in state["books"].values()), 2)

    # 킬스위치: 자산 고점 대비 -15%면 다음 사이클부터 전량 청산·중단 (수동 해제 필요)
    state["peak_equity"] = max(state.get("peak_equity", INITIAL_BALANCE), state["equity"])
    if not halted and state["equity"] < state["peak_equity"] * (1 - KILL_SWITCH_DD):
        state["halted"] = True
        actions["KILL_SWITCH"] = f"발동 (고점 {state['peak_equity']} 대비 -{KILL_SWITCH_DD*100:.0f}%)"

    # 자산 이력 기록 (백테스트 vs 실거래 드리프트 분석용)
    RESULTS_DIR.mkdir(exist_ok=True)
    header = not EQUITY_CSV.exists()
    with open(EQUITY_CSV, "a") as f:
        if header:
            f.write("ts,mode,price,equity,halted\n")
        f.write(f"{int(time.time())},{state['mode']},{price},{state['equity']},{state.get('halted', False)}\n")

    save_state(state)
    return {"mode": state["mode"], "actions": actions, "price": price,
            "equity": state["equity"], "halted": state.get("halted", False),
            "cycles": state["cycles"]}


if __name__ == "__main__":
    print(json.dumps(run_once(), ensure_ascii=False, indent=2))
