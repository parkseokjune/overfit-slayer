"""집행 엔진 — Binance 데모 트레이딩 (키 없으면 dry-run 시뮬레이션).

가드레일: enable_demo_trading(True) 강제 — 실거래소로는 절대 주문하지 않는다.

run_once(15분): 캔들 갱신 → 시그널/일봉 스탑 평가 → maker 지정가 주문 → 기록
fast_risk_check(60초): 비상밴드(2×손절 폭주)·킬스위치 전용 (일상 스탑은 일봉 종가 평가)
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

# 운용 북은 config.yaml의 books 섹션에서 로드 — 자가학습(self_learn)이 자동 갱신
def get_books() -> dict:
    return load_config().get("books", {})


BOOKS = get_books()  # 모듈 로드 시점 스냅샷 (run_once는 매번 재로드)
VOL_STEP = 0.25  # 분수 포지션 계단화 (리밸런스 churn 축소)
INITIAL_BALANCE = 5_000.0  # 데모 계좌 실잔고에 맞춤 (2026-06-11)
KILL_SWITCH_DD = 0.40  # 재난 백스톱: 고점 -40% → 전량 청산·중단 (수동 해제)
# 주의: -15%였던 구버전은 백테스트 기대 MDD(-30%)와 모순 — 9y 시뮬레이션 결과 영구정지로
# CAGR 1.1%가 됨(모순 입증). -40%는 9y 무발동, 역사 밖 시나리오 전용 보험 (2026-06-11 재설계)
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
            "entry_price": None, "qty": 0.0,
            "extreme": None,        # 보유 중 최고가(롱)/최저가(숏) — 트레일링용
            "blocked_sign": 0}      # 고속루프 스탑아웃 후 재진입 금지 방향


def load_state() -> dict:
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        if "books" in state:
            return state
    # 신규 또는 구버전 → 현재 books 구성으로 초기화 (epoch_start = 드리프트 측정 시작점)
    return {"mode": None, "cycles": 0, "epoch_start": int(time.time()),
            "books": {name: _fresh_book(b["weight"]) for name, b in get_books().items()}}


def save_state(state: dict):
    """원자적 저장 — 쓰다 죽어도 기존 파일은 온전 (temp 후 rename)."""
    RESULTS_DIR.mkdir(exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, STATE_FILE)


def reconcile(ex, state: dict, price: float) -> dict:
    """장부 vs 거래소 실포지션 대조 — 불일치 시 신규 진입 차단 + 경고.

    부분체결/재시작 중 체결/수동 개입으로 로컬 장부가 어긋난 채 거래하는 것을 방지.
    """
    if ex is None:
        state["recon"] = "dry_run"
        return state
    local_qty = sum(
        b["qty"] * (1 if b["position"] > 0 else -1 if b["position"] < 0 else 0)
        for b in state["books"].values())
    exch_qty = 0.0
    for p in ex.fetch_positions([FUTURES_SYMBOL]):
        if p.get("contracts"):
            exch_qty += float(p["contracts"]) * (1 if p["side"] == "long" else -1)
    # 잔고 0 감지: 인증은 되는데 증거금이 비어있으면 주문이 전부 실패 — 진입 차단
    usdt = fetch_futures_usdt(ex)
    if usdt <= 0:
        state["recon"] = "EMPTY_BALANCE"
        state["recon_block"] = True
        (RESULTS_DIR / "ALERT.txt").write_text(
            "데모 선물 지갑 USDT 잔고 0 — 데모 리셋/지갑 이체 필요. 신규 진입 차단됨.\n")
        return state

    diff_notional = abs(local_qty - exch_qty) * price
    if diff_notional > MIN_NOTIONAL:  # 최소주문 단위 이상 어긋나면 진짜 불일치
        state["recon"] = f"MISMATCH local={local_qty:.4f} exch={exch_qty:.4f}"
        state["recon_block"] = True  # 신규 진입 차단 (청산은 허용)
        (RESULTS_DIR / "ALERT.txt").write_text(
            f"포지션 불일치: 장부 {local_qty:.4f} vs 거래소 {exch_qty:.4f} BTC "
            f"(명목 ${diff_notional:,.0f}) — 수동 확인 필요. 신규 진입 차단됨.\n")
    else:
        state["recon"] = "ok"
        state["recon_block"] = False
    return state


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
    b = get_books()[book_name]
    df = fetch_data(symbol, b["timeframe"])
    if b["strategy"] == "sma_cross":
        raw = SmaCross(fast=b["fast"], slow=b["slow"]).generate_signals(df)
    elif b["strategy"] == "supertrend":
        raw = Supertrend(period=b["period"],
                         multiplier=b["multiplier"]).generate_signals(df)
    elif b["strategy"] == "bb_breakout":
        from .strategies import BbBreakout
        raw = BbBreakout(period=b["period"], std=b["std"]).generate_signals(df)
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


def _execute_with_maker(ex, fsym: str, side: str, amount: float, ref_price: float,
                        urgent: bool = False) -> dict:
    """지정가(post-only) 우선 집행 — taker 0.045% 대신 maker 리베이트.

    urgent(스탑 청산 등)는 즉시 시장가. 일반 신호 주문은 호가 근처 지정가를 걸고
    maker_wait_sec 대기, 미체결분은 시장가 폴백 (체결 확실성 보장).
    """
    if urgent:
        return ex.create_order(fsym, "market", side, amount)
    cfg = load_config().get("execution", {})
    wait = cfg.get("maker_wait_sec", 90)
    off = cfg.get("maker_offset_bps", 1) / 10_000
    limit_price = ref_price * (1 - off) if side == "buy" else ref_price * (1 + off)
    limit_price = float(ex.price_to_precision(fsym, limit_price))
    try:
        order = ex.create_order(fsym, "limit", side, amount, limit_price,
                                params={"timeInForce": "GTX"})  # post-only
    except Exception:
        return ex.create_order(fsym, "market", side, amount)  # GTX 즉시체결거부 등 → 폴백

    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(5)
        order = ex.fetch_order(order["id"], fsym)
        if order["status"] == "closed":
            return order
    # 타임아웃: 잔량 취소 후 시장가 폴백
    try:
        ex.cancel_order(order["id"], fsym)
    except Exception:
        pass
    order = ex.fetch_order(order["id"], fsym)
    remaining = float(order.get("remaining") or 0)
    if remaining > 0:
        ex.create_order(fsym, "market", side, remaining)
    return order


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
    order = _execute_with_maker(ex, fsym, side, amount, price, urgent=(target == 0))
    fill = float(order.get("average") or price)
    record_trade({"ts": int(time.time()), "mode": "testnet", "book": book,
                  "side": side, "position": target, "price": fill,
                  "qty": amount, "pnl": "",
                  "balance": round(state["balance"], 2)})
    state.update(position=target, entry_price=fill if target != 0 else None,
                 qty=abs(target_qty) if target != 0 else 0.0)
    return state


def fetch_futures_usdt(ex) -> float:
    """선물 지갑 USDT 잔고 — 데모 서버의 account 엔드포인트 고장 대응.

    fetch_balance(→ /fapi/v*/account)가 데모에서 0을 반환하는 버그가 있어
    정상 동작하는 /fapi/v3/balance를 직접 사용한다 (2026-06-11 확인).
    """
    try:
        for row in ex.fapiPrivateV3GetBalance():
            if row.get("asset") == "USDT":
                return float(row.get("balance") or 0)
    except Exception:
        pass
    try:
        return float(ex.fetch_balance().get("USDT", {}).get("total") or 0)
    except Exception:
        return 0.0


def fetch_live_price(ex=None) -> float:
    """실시간 가격 (테스트넷 ex 있으면 거기서, 없으면 공개 현물 시세)."""
    if ex:
        return float(ex.fetch_ticker(FUTURES_SYMBOL)["last"])
    import ccxt
    pub = ccxt.binance({"enableRateLimit": True})
    return float(pub.fetch_ticker("BTC/USDT")["last"])


EMERGENCY_MULT = 2.0  # 비상밴드 = 손절폭의 2배 (예: sl 4% → 장중 -8% 폭주 시만 즉시 청산)


def fast_risk_check() -> dict:
    """고속 리스크 루프 (매분) — 비상밴드 + 킬스위치 전용.

    ⚠ 일상 손절/트레일링은 여기서 집행하지 않는다 — 검증된 정책은 일봉 종가 평가
    (신호 사이클의 apply_stops)이며, 장중 터치 즉시 체결은 9y 시뮬레이션에서
    CAGR 21.6%→-0.2%로 전략을 파괴함(위크 청산). 이 루프는 진입가 대비
    손절폭의 2배를 초과하는 장중 폭주(재난)만 즉시 끊는다.
    """
    state = load_state()
    ex = make_testnet_exchange()
    price = fetch_live_price(ex)
    books = get_books()
    events = []

    for name, bcfg in books.items():
        book = state["books"].get(name)
        if not book or book["position"] == 0 or not book["entry_price"]:
            continue
        direction = 1 if book["position"] > 0 else -1
        entry = book["entry_price"]
        # 극값 추적은 유지 (일상 트레일링은 신호 사이클이 일봉 기준으로 평가)
        ext = book.get("extreme") or entry
        ext = max(ext, price) if direction > 0 else min(ext, price)
        book["extreme"] = ext

        emergency_loss = EMERGENCY_MULT * bcfg["stop_loss"]
        loss = (price / entry - 1) * direction
        if loss <= -emergency_loss:  # 재난 폭주만 즉시 청산
            if ex:
                execute_testnet(ex, book, 0, "BTC/USDT", price, bcfg["leverage"], book=name)
            else:
                execute_dry_run(book, 0, price, bcfg["leverage"], book=name)
            book["blocked_sign"] = direction
            book["extreme"] = None
            events.append(f"{name}: 비상밴드(-{emergency_loss*100:.0f}%) 청산 @ ${price:,.0f} (진입 ${entry:,.0f})")

    state["equity"] = round(sum(mark_to_market(b, price)
                                for b in state["books"].values()), 2)
    state["peak_equity"] = max(state.get("peak_equity", INITIAL_BALANCE), state["equity"])
    if not state.get("halted") and state["equity"] < state["peak_equity"] * (1 - KILL_SWITCH_DD):
        state["halted"] = True
        events.append(f"KILL-SWITCH 발동 (고점 ${state['peak_equity']:,.0f} 대비 -{KILL_SWITCH_DD*100:.0f}%)")
        for name, bcfg in books.items():
            book = state["books"].get(name)
            if book and book["position"] != 0:
                if ex:
                    execute_testnet(ex, book, 0, "BTC/USDT", price, bcfg["leverage"], book=name)
                else:
                    execute_dry_run(book, 0, price, bcfg["leverage"], book=name)
    save_state(state)
    return {"price": price, "equity": state["equity"], "events": events,
            "halted": state.get("halted", False)}


def run_once() -> dict:
    cfg = load_config()
    symbol = cfg["market"]["symbol"]
    state = load_state()
    ex = make_testnet_exchange()
    state["mode"] = "testnet" if ex else "dry_run"

    actions, price = {}, None
    halted = state.get("halted", False)
    if ex:
        state = reconcile(ex, state, fetch_live_price(ex))
        if state.get("recon_block"):
            halted = True  # 불일치 해소 전 신규 진입 차단
            actions["RECON"] = state["recon"]
    for name, bcfg in get_books().items():
        book = state["books"].setdefault(name, _fresh_book(bcfg["weight"]))
        info = compute_target_signal(symbol, name)
        target, price = info["target"], info["price"]
        if halted:
            target = 0  # 킬스위치 발동 중: 청산만 허용
        # 고속루프 스탑아웃 후 재진입 블록: 같은 방향 재진입은 원시 신호 리셋/반전까지 금지
        blocked = book.get("blocked_sign", 0)
        if blocked and target != 0 and (1 if target > 0 else -1) == blocked:
            target = 0
        elif blocked:
            book["blocked_sign"] = 0  # 신호가 0이 되거나 반전 → 블록 해제
        if target != book["position"]:
            if ex:
                # 테스트넷: 북별 증거금 비례 수량으로 주문 (심볼 단일이라 순노출 합산됨)
                execute_testnet(ex, book, target, symbol, price,
                                bcfg["leverage"], book=name)
            else:
                execute_dry_run(book, target, price, bcfg["leverage"], book=name)
            if book["position"] != 0:
                book["extreme"] = book["entry_price"]  # 트레일링 기준점 초기화
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
