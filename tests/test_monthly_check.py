"""월간 점검 테스트."""
import json
import time

import pandas as pd

import src.monthly_check as mc


def test_healthy_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "RESULTS_DIR", tmp_path)
    now = int(time.time())
    (tmp_path / "paper_state.json").write_text(json.dumps(
        {"epoch_start": now - 5*86400, "books": {"a": {"balance": 5000}}}))
    (tmp_path / "drift_status.json").write_text(json.dumps({"state": "정상"}))
    rows = ["ts,mode,price,equity,halted"] + [f"{now - i*3600},testnet,60000,5000,False" for i in range(48)]
    (tmp_path / "equity_history.csv").write_text("\n".join(rows))
    r = mc.check()
    assert "✅" in r["판정"]


def test_recon_block_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "RESULTS_DIR", tmp_path)
    now = int(time.time())
    (tmp_path / "paper_state.json").write_text(json.dumps(
        {"epoch_start": now, "recon_block": True, "books": {}}))
    (tmp_path / "drift_status.json").write_text(json.dumps({"state": "정상"}))
    rows = ["ts,mode,price,equity,halted"] + [f"{now - i*3600},testnet,60000,5000,False" for i in range(48)]
    (tmp_path / "equity_history.csv").write_text("\n".join(rows))
    r = mc.check()
    assert "⛔" in r["판정"]
