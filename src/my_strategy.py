"""Claude 자체 합성 기법 — "위원회(Committee) 파이프라인".

experiments.csv 분석에서 도출한 생존 요소만 조합:
  트렌드 위원회 다수결 (false signal 억제)
  → 레짐 필터 (고변동 관망, 추세장 역방향 차단)
  → 손절 5% / 트레일링 8% (청산 방지 — 이게 없으면 레버리지에서 전멸)
  → 변동성 타게팅 (고변동 구간 분수 포지션 축소)
"""
import pandas as pd

from .ai_analyst import apply_regime_filter
from .risk import apply_stops
from .strategies.base import BaseStrategy
from .strategies.ensemble import TrendCommittee, VolTarget

PPY = {"1h": 24 * 365, "4h": 6 * 365, "1d": 365}


class CommitteePipeline(BaseStrategy):
    name = "committee_pipeline"

    def __init__(self, threshold: float = 0.5, stop_loss_pct: float = 0.05,
                 trailing_pct: float = 0.08, regime_lookback: int = 100,
                 vol_target_annual: float = None, vol_lookback: int = 30,
                 timeframe: str = "1d"):
        super().__init__(threshold=threshold, stop_loss_pct=stop_loss_pct,
                         trailing_pct=trailing_pct, regime_lookback=regime_lookback,
                         vol_target_annual=vol_target_annual, timeframe=timeframe)
        self.committee = TrendCommittee(threshold=threshold)
        self.stop_loss_pct = stop_loss_pct
        self.trailing_pct = trailing_pct
        self.regime_lookback = regime_lookback
        self.vol_target_annual = vol_target_annual
        self.vol_lookback = vol_lookback
        self.timeframe = timeframe

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        sig = self.committee.generate_signals(df)
        sig = apply_regime_filter(df, sig, self.regime_lookback)
        sig = apply_stops(df, sig, self.stop_loss_pct, self.trailing_pct)
        if self.vol_target_annual:
            vt = VolTarget(self.committee, self.vol_target_annual,
                           self.vol_lookback, PPY[self.timeframe])
            sig = sig * vt.scale(df)
        return sig
