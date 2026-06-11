"""통계적 검증 — Deflated Sharpe Ratio (Bailey & López de Prado, 2014).

다중검정 보정: N번의 전략 실험 끝에 얻은 최고 Sharpe는 우연만으로도 높아진다.
DSR = "관측 Sharpe가 [N회 시도 시 우연이 만들 기대 최대 Sharpe]를 초과할 확률".
DSR > 0.95면 다중검정을 감안해도 통계적으로 유의한 전략.
"""
import numpy as np
import pandas as pd
from scipy import stats as sps

EULER_GAMMA = 0.5772156649


def expected_max_sharpe(n_trials: int, trial_sr_var: float) -> float:
    """N회 독립 시도에서 우연이 만드는 기대 최대 Sharpe (per-period 단위)."""
    if n_trials < 2:
        return 0.0
    z1 = sps.norm.ppf(1 - 1 / n_trials)
    z2 = sps.norm.ppf(1 - 1 / (n_trials * np.e))
    return np.sqrt(trial_sr_var) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def probabilistic_sharpe_ratio(returns: pd.Series, sr_benchmark: float) -> float:
    """PSR: 관측 수익률의 Sharpe가 벤치마크 SR을 초과할 확률 (skew/kurt 보정)."""
    r = returns.dropna()
    t = len(r)
    sr = r.mean() / r.std()  # per-period
    skew = sps.skew(r)
    kurt = sps.kurtosis(r, fisher=False)
    denom = np.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr ** 2)
    z = (sr - sr_benchmark) * np.sqrt(t - 1) / denom
    return float(sps.norm.cdf(z))


def deflated_sharpe_ratio(returns: pd.Series, trial_sharpes_annual: np.ndarray,
                          periods_per_year: int = 365) -> dict:
    """관측 수익률 + 전체 실험의 Sharpe 분포 → DSR."""
    trial_sr = np.asarray(trial_sharpes_annual, dtype=float) / np.sqrt(periods_per_year)
    trial_sr = trial_sr[~np.isnan(trial_sr)]
    n = len(trial_sr)
    sr_max_expected = expected_max_sharpe(n, np.var(trial_sr))
    dsr = probabilistic_sharpe_ratio(returns, sr_max_expected)
    r = returns.dropna()
    return {
        "n_trials": n,
        "observed_sharpe_annual": round(float(r.mean() / r.std() * np.sqrt(periods_per_year)), 3),
        "expected_max_sharpe_annual_by_luck": round(float(sr_max_expected * np.sqrt(periods_per_year)), 3),
        "dsr": round(dsr, 4),
        "verdict": "유의 (다중검정 감안해도 우연 아님)" if dsr > 0.95
                   else "경계 (우연 가능성 무시 못함)" if dsr > 0.80
                   else "기각 수준 (우연으로 설명 가능)",
    }
