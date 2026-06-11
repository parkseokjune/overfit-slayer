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
