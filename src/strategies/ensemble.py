"""자체 합성 전략 — 트렌드 위원회(다수결) + 변동성 타게팅 래퍼.

설계 근거 (results/experiments.csv 분석):
- 단일 유명 전략(돈치안/슈퍼트렌드/MACD/변동성돌파)은 전부 OOS 음수
- 살아남은 건 스탑+레짐 필터가 붙은 전략뿐
- 트렌드 전략들의 시그널 합의가 강할 때만 진입하면 false signal이 줄어든다
  (리서치: 돈치안 멀티기간 앙상블 Sharpe 1.58 사례)

파이프라인 권장 순서:
TrendCommittee(이산 투표) → apply_regime_filter → apply_stops → VolTarget(분수 축소)
"""
import numpy as np
import pandas as pd

from .base import BaseStrategy
from .donchian import Donchian
from .macd_momentum import MacdMomentum
from .sma_cross import SmaCross
from .supertrend import Supertrend


class TrendCommittee(BaseStrategy):
    """4개 트렌드 전략의 다수결. |평균투표| >= threshold일 때만 진입."""
    name = "trend_committee"

    def __init__(self, threshold: float = 0.5):
        super().__init__(threshold=threshold)
        self.threshold = threshold
        self.members = [
            SmaCross(fast=20, slow=150),
            Donchian(entry_n=55, exit_n=20),
            Supertrend(period=10, multiplier=3.0),
            MacdMomentum(),
        ]

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        votes = pd.concat([m.generate_signals(df) for m in self.members], axis=1)
        avg = votes.mean(axis=1)
        sig = pd.Series(0, index=df.index)
        sig[avg >= self.threshold] = 1
        sig[avg <= -self.threshold] = -1
        return sig


class VolTarget(BaseStrategy):
    """변동성 타게팅 — 실현변동성이 목표 초과 시 포지션 비례 축소 (분수 포지션).

    스탑/필터 적용이 끝난 이산 시그널 위에 마지막으로 입힌다.
    """
    name = "vol_target"

    def __init__(self, inner: BaseStrategy, vol_target_annual: float = 0.35,
                 lookback: int = 30, periods_per_year: int = 365):
        super().__init__(**inner.params, vol_target_annual=vol_target_annual,
                         lookback=lookback)
        self.inner = inner
        self.vol_target = vol_target_annual
        self.lookback = lookback
        self.periods_per_year = periods_per_year
        self.name = f"{inner.name}+volT"

    def scale(self, df: pd.DataFrame) -> pd.Series:
        realized = (df["close"].pct_change().rolling(self.lookback).std()
                    * np.sqrt(self.periods_per_year))
        return (self.vol_target / realized).clip(upper=1.0).fillna(0.0)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return self.inner.generate_signals(df) * self.scale(df)
