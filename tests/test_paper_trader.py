"""페이퍼 트레이더 dry-run 체결 로직 테스트."""
import pytest

from src.paper_trader import execute_dry_run, mark_to_market


def fresh_state():
    return {"mode": "dry_run", "balance": 10_000.0, "position": 0,
            "entry_price": None, "qty": 0.0, "cycles": 0}


def test_open_long_then_close_with_profit(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paper_trader.TRADES_CSV", tmp_path / "t.csv")
    s = fresh_state()
    s = execute_dry_run(s, target=1, price=50_000, leverage=2)
    assert s["position"] == 1
    assert s["qty"] == pytest.approx(10_000 * 2 / 50_000 * 0.998, rel=0.01)

    # +10% 가격 상승 후 청산: 2x 레버리지 → 자산 약 +20%
    s = execute_dry_run(s, target=0, price=55_000, leverage=2)
    assert s["position"] == 0
    assert s["balance"] > 11_500  # 수수료 차감 후에도 +15% 이상


def test_short_profits_when_price_falls(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paper_trader.TRADES_CSV", tmp_path / "t.csv")
    s = fresh_state()
    s = execute_dry_run(s, target=-1, price=50_000, leverage=2)
    assert s["position"] == -1
    s = execute_dry_run(s, target=0, price=45_000, leverage=2)
    assert s["balance"] > 11_500  # -10% 하락 × 2x 숏 = 약 +20%


def test_flip_long_to_short(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paper_trader.TRADES_CSV", tmp_path / "t.csv")
    s = fresh_state()
    s = execute_dry_run(s, target=1, price=50_000, leverage=2)
    s = execute_dry_run(s, target=-1, price=50_000, leverage=2)
    assert s["position"] == -1
    assert s["entry_price"] == 50_000


def test_mark_to_market():
    s = fresh_state()
    s.update(position=1, entry_price=50_000, qty=0.4)
    assert mark_to_market(s, 51_000) == pytest.approx(10_000 + 0.4 * 1_000)


def test_kill_switch_halts_trading(tmp_path, monkeypatch):
    """자산이 고점 대비 -15% 넘게 빠지면 halted 플래그가 선다."""
    import src.paper_trader as pt
    monkeypatch.setattr(pt, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(pt, "EQUITY_CSV", tmp_path / "e.csv")
    monkeypatch.setattr(pt, "TRADES_CSV", tmp_path / "t.csv")
    monkeypatch.setattr(pt, "make_testnet_exchange", lambda: None)
    # 시그널 고정: 항상 관망
    monkeypatch.setattr(pt, "compute_target_signal",
                        lambda sym, name: {"target": 0, "price": 50_000, "candle_ts": 0})
    # 고점 12000, 현재 잔고 합 10000 → -16.7% → 킬스위치
    state = {"mode": None, "cycles": 0, "peak_equity": 12_000.0,
             "books": {n: {"balance": 5_000.0, "position": 0, "entry_price": None, "qty": 0.0}
                       for n in pt.BOOKS}}
    (tmp_path / "s.json").write_text(__import__("json").dumps(state))
    out = pt.run_once()
    assert out["halted"] is True
    assert "KILL_SWITCH" in out["actions"]
