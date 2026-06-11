"""포지션 정합 검사 테스트."""
import json

import src.paper_trader as pt


class FakeEx:
    def __init__(self, qty):  # qty: 거래소 순포지션 (BTC, 부호 포함)
        self.qty = qty
    def fetch_positions(self, syms):
        if self.qty == 0:
            return []
        return [{"contracts": abs(self.qty), "side": "long" if self.qty > 0 else "short"}]


def state_with(local_pos, local_qty):
    return {"books": {"b1": {"balance": 2500.0, "position": local_pos,
                             "entry_price": 60000.0, "qty": local_qty}}}


def test_match_passes():
    s = pt.reconcile(FakeEx(0.05), state_with(1, 0.05), 60_000)
    assert s["recon"] == "ok" and not s["recon_block"]


def test_mismatch_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "RESULTS_DIR", tmp_path)
    s = pt.reconcile(FakeEx(0.0), state_with(1, 0.05), 60_000)  # 장부 롱 0.05, 거래소 0
    assert s["recon_block"] is True
    assert (tmp_path / "ALERT.txt").exists()


def test_tiny_diff_tolerated():
    """최소주문 미만 잔차(더스트)는 불일치로 안 봄."""
    s = pt.reconcile(FakeEx(0.0501), state_with(1, 0.05), 60_000)
    assert s["recon"] == "ok"


def test_atomic_save(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(pt, "RESULTS_DIR", tmp_path)
    pt.save_state({"a": 1})
    assert json.loads((tmp_path / "s.json").read_text()) == {"a": 1}
    assert not (tmp_path / "s.tmp").exists()
