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
