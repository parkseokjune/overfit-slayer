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


def test_reset_jump_excluded(tmp_path, monkeypatch):
    """장부 리셋(거래 없는 큰 점프)은 수익률에서 제외 — 가짜 CRITICAL 방지."""
    import src.drift_monitor as dm
    csv = tmp_path / "e.csv"
    rows = ["ts,mode,price,equity,halted"]
    # 1만→리셋 5천→이후 정상 변동
    base = 1700000000
    vals = [10000, 10000, 5000, 5010, 5020, 4990, 5005]
    for i, v in enumerate(vals):
        rows.append(f"{base + i*86400},testnet,60000,{v},False")
    csv.write_text("\n".join(rows))
    monkeypatch.setattr(dm, "EQUITY_CSV", csv)
    r = dm.live_daily_returns()
    assert (r.abs() < 0.05).all()  # -50% 리셋이 수익률로 안 들어옴
    assert len(r) >= 3
