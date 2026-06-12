"""운영 레이어 테스트 (체결원장/알림/복구)."""
import json
import time

import pandas as pd


def test_exec_quality_aggregates(tmp_path, monkeypatch):
    import src.exec_quality as eq
    monkeypatch.setattr(eq, "TRADES_CSV", tmp_path / "t.csv")
    now = int(time.time())
    pd.DataFrame([
        {"ts": now, "order_type": "maker", "slippage_bps": -1.0},
        {"ts": now, "order_type": "maker", "slippage_bps": 0.5},
        {"ts": now, "order_type": "market_fallback", "slippage_bps": 4.0},
    ]).to_csv(tmp_path / "t.csv", index=False)
    s = eq.summary()
    assert s["n"] == 3 and s["maker_rate"] == 0.67 or abs(s["maker_rate"] - 2/3) < 0.01
    assert s["avg_slippage_bps"] is not None
    assert "✅" in s["status"]


def test_notify_writes_log(tmp_path, monkeypatch):
    import src.notify as nf
    monkeypatch.setattr(nf, "LOG", tmp_path / "n.log")
    monkeypatch.setattr(nf, "RESULTS_DIR", tmp_path)
    nf.notify("TEST", "hello")
    assert "hello" in (tmp_path / "n.log").read_text()


def test_recover_adopt_exchange(monkeypatch):
    import src.recover as rc
    class FakeEx:
        def fetch_positions(self, syms):
            return [{"contracts": 0.05, "side": "long", "entryPrice": 60000}]
    monkeypatch.setattr(rc, "fetch_futures_usdt", lambda ex: 5000.0)
    monkeypatch.setattr(rc, "fetch_live_price", lambda ex=None: 60000.0)
    state = {"books": {}, "recon_block": True}
    out = rc.adopt_exchange(FakeEx(), state, 0.05)
    assert out["recon_block"] is False
    assert out["epoch_start"] > 0
    total_qty = sum(b["qty"] for b in out["books"].values())
    assert abs(total_qty - 0.05) < 1e-9
