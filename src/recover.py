"""복구 모드 (DESIGN_NEXT #6) — 포지션 불일치/차단 상태의 정형화된 해소 절차.

사용: python -m src.recover  (대화형 — recon_block 해제는 이 도구로만)
"""
import json
import sys
import time

from .backtest import RESULTS_DIR
from .notify import notify
from .paper_trader import (FUTURES_SYMBOL, fetch_futures_usdt, get_books,
                           load_state, make_testnet_exchange, save_state,
                           _fresh_book, fetch_live_price)


def show_status(ex, state):
    print("=== 장부 ===")
    for k, v in state["books"].items():
        print(f"  {k}: pos {v['position']}, qty {v['qty']}, 잔고 ${v['balance']:,.0f}")
    print(f"  recon_block={state.get('recon_block')}, halted={state.get('halted')}")
    exch_qty = 0.0
    if ex:
        for p in ex.fetch_positions([FUTURES_SYMBOL]):
            if p.get("contracts"):
                q = float(p["contracts"]) * (1 if p["side"] == "long" else -1)
                exch_qty += q
                print(f"=== 거래소: {p['side']} {p['contracts']} @ {p.get('entryPrice')}")
        print(f"=== 거래소 잔고: {fetch_futures_usdt(ex):,.2f} USDT, 순포지션 {exch_qty:+.4f} BTC")
    return exch_qty


def adopt_exchange(ex, state, exch_qty):
    """[A] 거래소를 진실로 — 장부를 거래소에 맞춰 재구성."""
    usdt = fetch_futures_usdt(ex)
    price = fetch_live_price(ex)
    books = get_books()
    state["books"] = {n: _fresh_book(b["weight"]) for n, b in books.items()}
    for n, b in state["books"].items():
        b["balance"] = usdt * books[n]["weight"]
    if abs(exch_qty) > 1e-6:
        # 순포지션은 방향이 맞는 최대 비중 북에 귀속
        sign = 1 if exch_qty > 0 else -1
        target = max(books, key=lambda n: books[n]["weight"])
        state["books"][target].update(position=sign, qty=abs(exch_qty),
                                      entry_price=price, extreme=price)
    state["recon_block"] = False
    state["recon"] = "recovered_adopt_exchange"
    state["epoch_start"] = int(time.time())
    return state


def flatten_all(ex, state):
    """[B] 전량 청산 후 플랫 재시작 (새 epoch)."""
    if ex:
        for p in ex.fetch_positions([FUTURES_SYMBOL]):
            qty = float(p.get("contracts") or 0)
            if qty:
                side = "sell" if p["side"] == "long" else "buy"
                ex.create_order(FUTURES_SYMBOL, "market", side, qty)
    usdt = fetch_futures_usdt(ex) if ex else sum(b["balance"] for b in state["books"].values())
    books = get_books()
    state["books"] = {n: _fresh_book(b["weight"]) for n, b in books.items()}
    for n in state["books"]:
        state["books"][n]["balance"] = usdt * books[n]["weight"]
    state["recon_block"] = False
    state["halted"] = False
    state["recon"] = "recovered_flatten"
    state["epoch_start"] = int(time.time())
    return state


def main():
    ex = make_testnet_exchange()
    state = load_state()
    exch_qty = show_status(ex, state)
    print("\n[A] 거래소를 진실로 (장부 재구성)  [B] 전량 청산 후 재시작  [C] 사유 기록 후 차단 해제  [Q] 취소")
    choice = input("선택: ").strip().upper()
    if choice == "A":
        state = adopt_exchange(ex, state, exch_qty)
    elif choice == "B":
        state = flatten_all(ex, state)
    elif choice == "C":
        reason = input("무시 사유 (기록 강제): ").strip()
        if not reason:
            print("사유 없이는 해제 불가"); sys.exit(1)
        state["recon_block"] = False
        state["recon"] = f"override: {reason}"
    else:
        print("취소"); return
    save_state(state)
    notify("RECOVERY", f"복구 모드 [{choice}] 실행 — recon={state['recon']}")
    print("✅ 완료:", state["recon"])


if __name__ == "__main__":
    main()
