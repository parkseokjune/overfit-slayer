"""드리프트 모니터 테스트."""
import numpy as np

from src.drift_monitor import bootstrap_percentile


def test_consistent_path_is_mid_percentile():
    """백테스트와 같은 분포의 라이브 → 중간 분위."""
    rng = np.random.default_rng(0)
    bt = rng.normal(0.001, 0.02, 2000)
    live_cum = float(np.prod(1 + rng.choice(bt, 30)) - 1)
    pct = bootstrap_percentile(bt, live_cum, 30)
    assert 2 < pct < 98


def test_crash_path_is_low_percentile():
    """백테스트 분포보다 한참 나쁜 라이브(-30%/30일) → 하위 분위."""
    rng = np.random.default_rng(0)
    bt = rng.normal(0.001, 0.02, 2000)
    pct = bootstrap_percentile(bt, -0.30, 30)
    assert pct < 5


def test_epoch_marker_excludes_old_data(tmp_path, monkeypatch):
    """epoch_start 이전 스냅샷은 제외 — 리셋이 수익률로 안 들어오고, 제외 수가 보고됨."""
    import json
    import src.drift_monitor as dm
    csv = tmp_path / "e.csv"
    rows = ["ts,mode,price,equity,halted"]
    base = 1700000000
    vals = [10000, 10000, 5000, 5010, 5020, 4990, 5005]  # 리셋(10000→5000)은 epoch 경계
    for i, v in enumerate(vals):
        rows.append(f"{base + i*86400},testnet,60000,{v},False")
    csv.write_text("\n".join(rows))
    (tmp_path / "paper_state.json").write_text(json.dumps({"epoch_start": base + 2*86400}))
    monkeypatch.setattr(dm, "EQUITY_CSV", csv)
    monkeypatch.setattr(dm, "RESULTS_DIR", tmp_path)
    r, excluded = dm.live_daily_returns()
    assert (r.abs() < 0.05).all()   # -50% 리셋 미포함
    assert excluded == 2            # 제외 표본 수 보고
    assert len(r) >= 3


def test_real_crash_not_excluded(tmp_path, monkeypatch):
    """epoch 안의 실제 -20% 손실일은 절대 제외되지 않는다 (점프 추론 규칙 폐기 검증)."""
    import json
    import src.drift_monitor as dm
    csv = tmp_path / "e.csv"
    rows = ["ts,mode,price,equity,halted"]
    base = 1700000000
    vals = [5000, 5010, 3950, 3900, 3920]  # 3일차 실제 -21% 폭락
    for i, v in enumerate(vals):
        rows.append(f"{base + i*86400},testnet,60000,{v},False")
    csv.write_text("\n".join(rows))
    (tmp_path / "paper_state.json").write_text(json.dumps({"epoch_start": base}))
    monkeypatch.setattr(dm, "EQUITY_CSV", csv)
    monkeypatch.setattr(dm, "RESULTS_DIR", tmp_path)
    r, excluded = dm.live_daily_returns()
    assert excluded == 0
    assert r.min() < -0.20          # 폭락일이 그대로 들어있음
