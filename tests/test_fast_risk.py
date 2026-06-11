"""고속 리스크 루프 테스트 — 실시간 스탑/트레일링/킬스위치."""
import json

import pytest

import src.paper_trader as pt


def setup_env(tmp_path, monkeypatch, books_state, price, halted=False, peak=None):
    monkeypatch.setattr(pt, "STATE_FILE", tmp_path / "s.json")
    monkeypatch.setattr(pt, "EQUITY_CSV", tmp_path / "e.csv")
    monkeypatch.setattr(pt, "TRADES_CSV", tmp_path / "t.csv")
    monkeypatch.setattr(pt, "make_testnet_exchange", lambda: None)
    monkeypatch.setattr(pt, "fetch_live_price", lambda ex=None: price)
    state = {"mode": "dry_run", "cycles": 0, "halted": halted,
             "peak_equity": peak or pt.INITIAL_BALANCE, "books": books_state}
    (tmp_path / "s.json").write_text(json.dumps(state))


def long_book(entry, qty=0.05, balance=2500.0, extreme=None):
    return {"balance": balance, "position": 1.0, "entry_price": entry,
            "qty": qty, "extreme": extreme or entry, "blocked_sign": 0}


def test_normal_stop_does_NOT_fire_intraday(tmp_path, monkeypatch):
    """-4% 손절선은 장중에 안 끊는다 (일봉 종가 평가가 검증된 정책) — 위크 청산 방지."""
    setup_env(tmp_path, monkeypatch,
              {"sma_slow": long_book(60_000)}, price=57_500, peak=2_500)  # -4.2%
    out = pt.fast_risk_check()
    assert out["events"] == []
    st = json.loads((tmp_path / "s.json").read_text())
    assert st["books"]["sma_slow"]["position"] == 1.0  # 유지


def test_emergency_band_fires_intraday(tmp_path, monkeypatch):
    """진입가 대비 -8%(=2×sl) 초과 폭주 → 즉시 청산 + 재진입 블록."""
    setup_env(tmp_path, monkeypatch,
              {"sma_slow": long_book(60_000)}, price=55_000, peak=2_500)  # -8.3%
    out = pt.fast_risk_check()
    assert any("비상밴드" in e for e in out["events"])
    st = json.loads((tmp_path / "s.json").read_text())
    assert st["books"]["sma_slow"]["position"] == 0
    assert st["books"]["sma_slow"]["blocked_sign"] == 1


def test_trailing_not_intraday(tmp_path, monkeypatch):
    """트레일링도 장중엔 안 끊는다 (일봉 종가 평가) — 극값은 추적만."""
    setup_env(tmp_path, monkeypatch,
              {"sma_slow": long_book(55_000, extreme=62_000)}, price=56_900, peak=2_600)
    out = pt.fast_risk_check()
    assert out["events"] == []


def test_no_event_when_healthy(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch,
              {"sma_slow": long_book(60_000)}, price=60_500, peak=2_500)
    out = pt.fast_risk_check()
    assert out["events"] == []
    st = json.loads((tmp_path / "s.json").read_text())
    assert st["books"]["sma_slow"]["position"] == 1.0
    assert st["books"]["sma_slow"]["extreme"] == 60_500  # 극값 갱신


def test_kill_switch_flattens_all(tmp_path, monkeypatch):
    """자산이 고점 대비 -40% 초과 → 전 북 청산 + halted."""
    setup_env(tmp_path, monkeypatch,
              {"sma_slow": long_book(60_000, qty=0.04, balance=2000.0)},
              price=48_000, peak=5_000)  # 평가손익 반영 시 큰 손실
    out = pt.fast_risk_check()
    assert out["halted"] is True
    st = json.loads((tmp_path / "s.json").read_text())
    assert st["books"]["sma_slow"]["position"] == 0
