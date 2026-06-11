"""자가학습 의사결정 가드레일 테스트."""
from src.self_learn import decide


def grid(*oos):
    """params는 인덱스 라벨, oos_sharpe만 의미."""
    return [{"params": {"p": i}, "oos_sharpe": s} for i, s in enumerate(oos)]


def test_keeps_current_when_best():
    g = grid(0.2, 0.9, 0.3)
    d = decide(g, {"p": 1})
    assert d["action"] == "유지"


def test_rejects_isolated_spike():
    """이웃이 음수인 고립 최고값은 채택 금지."""
    g = grid(-0.5, 1.5, -0.6, 0.4)
    d = decide(g, {"p": 3})
    assert d["action"] == "유지"
    assert "고원" in d["reason"] or "고립" in d["reason"]


def test_rejects_marginal_improvement():
    """개선폭 < 0.15면 관성 유지."""
    g = grid(0.50, 0.58, 0.45)
    d = decide(g, {"p": 0})
    assert d["action"] == "유지"


def test_adopts_plateau_improvement():
    """이웃도 양수 + 개선폭 충분 → 교체."""
    g = grid(0.1, 0.6, 0.9, 0.7)
    d = decide(g, {"p": 0})
    assert d["action"] == "교체"
    assert d["chosen"] == {"p": 2}


def grid2d(vals):
    """vals: {(fast,slow): oos} — 2차원 그리드."""
    return [{"params": {"fast": f, "slow": s}, "oos_sharpe": o}
            for (f, s), o in vals.items()]


def test_2d_neighbors_reject_isolated_spike():
    """2D에서 대각/원거리는 이웃이 아님 — 십자 이웃이 음수면 고립 스파이크로 기각."""
    g = grid2d({
        (10, 100): -0.5, (10, 200): 1.8, (10, 300): -0.4,   # 위아래(slow축) 음수
        (20, 100): 0.6,  (20, 200): -0.6, (20, 300): 0.5,   # (20,200)도 음수
        (30, 100): 0.4,  (30, 200): 0.3,  (30, 300): 0.2,
    })
    d = decide(g, {"fast": 30, "slow": 100})
    assert d["action"] == "유지"          # (10,200)은 십자 이웃 전부 음수 → 기각


def test_2d_adopts_plateau():
    """십자 이웃이 양수인 2D 고원은 채택."""
    g = grid2d({
        (10, 100): 0.5, (10, 200): 0.9, (10, 300): 0.6,
        (20, 100): 0.4, (20, 200): 1.2, (20, 300): 0.7,
        (30, 100): 0.1, (30, 200): 0.8, (30, 300): 0.3,
    })
    d = decide(g, {"fast": 30, "slow": 300})
    assert d["action"] == "교체"
    assert d["chosen"] == {"fast": 20, "slow": 200}


def test_policy_observe_mode_blocks(tmp_path, monkeypatch):
    """라이브 90일 미만 + 드리프트 정상 → 교체 차단 (관측 모드)."""
    import json, time
    import src.self_learn as sl
    monkeypatch.setattr(sl, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sl, "HISTORY_CSV", tmp_path / "h.csv")
    (tmp_path / "paper_state.json").write_text(json.dumps({"epoch_start": int(time.time()) - 10*86400}))
    (tmp_path / "drift_status.json").write_text(json.dumps({"state": "정상"}))
    assert "관측 모드" in sl._policy_block("sma_slow")


def test_policy_critical_allows_change(tmp_path, monkeypatch):
    """드리프트 CRITICAL이면 관측 모드 해제 (적응 허용)."""
    import json, time
    import src.self_learn as sl
    monkeypatch.setattr(sl, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sl, "HISTORY_CSV", tmp_path / "h.csv")
    (tmp_path / "paper_state.json").write_text(json.dumps({"epoch_start": int(time.time()) - 10*86400}))
    (tmp_path / "drift_status.json").write_text(json.dumps({"state": "CRITICAL"}))
    assert sl._policy_block("sma_slow") == ""


def test_policy_cooldown_after_two_changes(tmp_path, monkeypatch):
    """직전 2회 연속 교체된 북은 쿨다운 — CRITICAL(교체 가능 상황)에서도 우선 적용."""
    import json, time
    import pandas as pd
    import src.self_learn as sl
    monkeypatch.setattr(sl, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sl, "HISTORY_CSV", tmp_path / "h.csv")
    (tmp_path / "paper_state.json").write_text(json.dumps({"epoch_start": int(time.time()) - 200*86400}))
    (tmp_path / "drift_status.json").write_text(json.dumps({"state": "CRITICAL"}))
    pd.DataFrame([{"book": "b1", "action": "교체"}, {"book": "b1", "action": "교체"}]).to_csv(tmp_path / "h.csv", index=False)
    assert "쿨다운" in sl._policy_block("b1")


def test_policy_stable_drift_blocks_after_90d(tmp_path, monkeypatch):
    """90일 지나도 드리프트 정상이면 보수 유지 (평상시 교체 금지)."""
    import json, time
    import src.self_learn as sl
    monkeypatch.setattr(sl, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sl, "HISTORY_CSV", tmp_path / "h.csv")
    (tmp_path / "paper_state.json").write_text(json.dumps({"epoch_start": int(time.time()) - 120*86400}))
    (tmp_path / "drift_status.json").write_text(json.dumps({"state": "정상"}))
    assert "안정 상태" in sl._policy_block("b1")


def test_policy_recon_block_blocks_learning(tmp_path, monkeypatch):
    """체결/잔고 이상(recon_block) 시 학습 보류 — 운영 리스크 우선."""
    import json, time
    import src.self_learn as sl
    monkeypatch.setattr(sl, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sl, "HISTORY_CSV", tmp_path / "h.csv")
    (tmp_path / "paper_state.json").write_text(json.dumps(
        {"epoch_start": int(time.time()) - 120*86400, "recon_block": True}))
    (tmp_path / "drift_status.json").write_text(json.dumps({"state": "CRITICAL"}))
    assert "운영 리스크" in sl._policy_block("b1")
