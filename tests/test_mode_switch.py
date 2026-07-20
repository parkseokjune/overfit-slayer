"""모드 전환 안전성 테스트 — dry_run→testnet 유령 포지션 방지.

2026-07-20 실발생 시나리오: dry_run 시절 장부 롱 0.0773이 testnet 전환 후
recon_block 상태에서 '청산' 매도 실주문으로 나가 거래소에 신규 숏 0.0772가
생겼다. 수정: (1) 전환 첫 사이클에 시뮬 장부 평탄화, (2) recon 불일치 중
청산은 reduceOnly 강제.
"""
import json

import src.paper_trader as pt

PRICE = 64_000.0


class FakeEx:
    """테스트넷 거래소 스텁 — Binance reduceOnly 거부 규칙(-2022) 에뮬레이션."""

    def __init__(self, qty=0.0, usdt=5000.0, price=PRICE):
        self.qty, self.usdt, self.price = qty, usdt, price
        self.attempts = []  # 거부 포함 모든 create_order 시도
        self.orders = []    # 실제 접수(체결)된 주문

    def fapiPrivateV3GetBalance(self):
        return [{"asset": "USDT", "balance": str(self.usdt)}]

    def fetch_positions(self, syms):
        if self.qty == 0:
            return []
        return [{"contracts": abs(self.qty),
                 "side": "long" if self.qty > 0 else "short"}]

    def fetch_ticker(self, sym):
        return {"last": self.price}

    def load_markets(self):
        pass

    def set_leverage(self, lev, sym):
        pass

    def amount_to_precision(self, sym, x):
        return f"{x:.3f}"

    def price_to_precision(self, sym, x):
        return f"{x:.1f}"

    def create_order(self, sym, typ, side, amount, price=None, params=None):
        params = params or {}
        self.attempts.append({"type": typ, "side": side,
                              "amount": float(amount), "params": params})
        if params.get("reduceOnly"):
            reducible = self.qty if side == "sell" else -self.qty
            if reducible <= 0:  # 줄일 포지션 없음 → 거래소가 거부
                raise Exception("binance -2022 ReduceOnly Order is rejected")
        self.orders.append(self.attempts[-1])
        return {"id": "1", "status": "closed", "average": self.price,
                "remaining": 0}


def setup_env(tmp_path, monkeypatch, fake, mode, pos_name, position=1.0,
              qty=0.0773, targets=None):
    """run_once 실행 환경 구성 — pos_name 북에만 포지션, 나머지는 평탄."""
    monkeypatch.setattr(pt, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(pt, "EQUITY_CSV", tmp_path / "e.csv")
    monkeypatch.setattr(pt, "TRADES_CSV", tmp_path / "t.csv")
    monkeypatch.setattr(pt, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(pt, "make_testnet_exchange", lambda: fake)
    targets = targets or {}
    monkeypatch.setattr(pt, "compute_target_signal",
                        lambda sym, name: {"target": targets.get(name, 0),
                                           "price": PRICE, "candle_ts": 0})
    books = {n: pt._fresh_book(b["weight"]) for n, b in pt.get_books().items()}
    books[pos_name].update(position=position, entry_price=PRICE, qty=qty)
    state = {"mode": mode, "cycles": 0, "epoch_start": 0, "books": books}
    (tmp_path / "s.json").write_text(json.dumps(state))
    return state


def test_flatten_sim_books_unit():
    """평탄화 유닛: 포지션 있는 북만 리셋, 분수 포지션도 처리."""
    state = {"books": {
        "a": {"position": 0.5, "entry_price": 60_000.0, "qty": 0.04,
              "extreme": 61_000.0, "blocked_sign": 0, "balance": 2000.0},
        "b": {"position": 0, "entry_price": None, "qty": 0.0, "balance": 1000.0}}}
    dropped = pt.flatten_sim_books(state)
    assert len(dropped) == 1 and dropped[0].startswith("a ")
    assert state["books"]["a"]["position"] == 0
    assert state["books"]["a"]["qty"] == 0.0
    assert state["books"]["a"]["entry_price"] is None
    assert state["books"]["b"]["balance"] == 1000.0  # 무포지션 북은 그대로


def test_dry_run_to_testnet_resets_book_no_orders(tmp_path, monkeypatch):
    """2026-07-20 시나리오: 전환 첫 사이클에 시뮬 장부 평탄화 → 실주문 0건."""
    fake = FakeEx(qty=0.0)  # 거래소는 무포지션 (dry_run 장부만 롱)
    pos_name = list(pt.get_books())[0]
    setup_env(tmp_path, monkeypatch, fake, mode="dry_run", pos_name=pos_name)

    out = pt.run_once()

    assert fake.attempts == []  # 유령 '청산' 주문이 거래소로 나가지 않음
    assert "MODE_SWITCH" in out["actions"]
    assert out["mode"] == "testnet" and out["halted"] is False
    saved = json.loads((tmp_path / "s.json").read_text())
    assert saved["recon"] == "ok"  # 평탄화 후 장부=거래소 → 불일치 경보 없음
    assert all(b["position"] == 0 for b in saved["books"].values())


def test_mismatch_close_forces_reduce_only_and_survives_reject(tmp_path, monkeypatch):
    """이미 testnet인데 장부만 롱(불일치): 청산은 reduceOnly로 나가고,
    거래소가 거부해도 유령 숏 없이 장부 보존 + 차단 유지."""
    fake = FakeEx(qty=0.0)  # 거래소 무포지션 → reduceOnly 매도는 거부됨
    pos_name = list(pt.get_books())[0]
    setup_env(tmp_path, monkeypatch, fake, mode="testnet", pos_name=pos_name)

    out = pt.run_once()

    assert len(fake.attempts) == 1
    assert fake.attempts[0]["side"] == "sell"
    assert fake.attempts[0]["params"].get("reduceOnly") is True
    assert fake.orders == []  # 거부됨 → 거래소에 유령 숏이 생기지 않음
    assert out["actions"]["RECON"].startswith("MISMATCH")
    saved = json.loads((tmp_path / "s.json").read_text())
    assert saved["books"][pos_name]["position"] == 1.0  # 장부 보존 (수동 확인 대기)
    assert saved["recon_block"] is True


def test_mismatch_close_with_real_position_reduces(tmp_path, monkeypatch):
    """불일치라도 거래소에 실포지션이 있으면 reduceOnly 청산이 정상 체결."""
    fake = FakeEx(qty=0.03)  # 거래소 롱 0.03 vs 장부 롱 0.0773 → 불일치
    pos_name = list(pt.get_books())[0]
    setup_env(tmp_path, monkeypatch, fake, mode="testnet", pos_name=pos_name)

    pt.run_once()

    assert len(fake.orders) == 1
    assert fake.orders[0]["side"] == "sell"
    assert fake.orders[0]["params"].get("reduceOnly") is True
    saved = json.loads((tmp_path / "s.json").read_text())
    assert saved["books"][pos_name]["position"] == 0  # 청산 반영


def test_no_flatten_when_already_testnet(tmp_path, monkeypatch):
    """testnet 연속 운영(정합 ok)에선 평탄화도 주문도 없어야 함."""
    fake = FakeEx(qty=0.0773)  # 거래소=장부 일치
    pos_name = list(pt.get_books())[0]
    setup_env(tmp_path, monkeypatch, fake, mode="testnet", pos_name=pos_name,
              targets={pos_name: 1.0})  # 신호도 롱 유지

    out = pt.run_once()

    assert "MODE_SWITCH" not in out["actions"]
    assert fake.attempts == []
    saved = json.loads((tmp_path / "s.json").read_text())
    assert saved["books"][pos_name]["position"] == 1.0  # 실포지션 장부 보존
