"""슈퍼트렌드 — ATR 기반 트레일링 밴드 플립.

밴드: (고+저)/2 ± multiplier × ATR(period)
종가가 상단 밴드 위로 마감 → 상승 전환(롱), 하단 아래 → 하락 전환(숏).
밴드는 추세 방향으로만 조여진다(래칫).
"""
import numpy as np
import pandas as pd
import ta

from .base import BaseStrategy


class Supertrend(BaseStrategy):
    name = "supertrend"

    def __init__(self, period: int = 10, multiplier: float = 3.0):
        super().__init__(period=period, multiplier=multiplier)
        self.period, self.multiplier = period, multiplier

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        atr = ta.volatility.AverageTrueRange(
            df["high"], df["low"], df["close"], window=self.period
        ).average_true_range()
        mid = (df["high"] + df["low"]) / 2
        upper_basic = (mid + self.multiplier * atr).to_numpy()
        lower_basic = (mid - self.multiplier * atr).to_numpy()
        close = df["close"].to_numpy()
        n = len(df)

        upper = upper_basic.copy()
        lower = lower_basic.copy()
        trend = np.zeros(n)  # 1 상승 / -1 하락
        initialized = False  # 첫 유효 캔들에서 명시적 초기화 (리뷰 반영 — 9y 신호 동일성 검증 완료)
        for i in range(1, n):
            if np.isnan(upper_basic[i]) or atr.iloc[i] == 0:
                continue
            if not initialized:
                mid_band = (upper_basic[i] + lower_basic[i]) / 2
                trend[i] = 1 if close[i] > mid_band else -1
                initialized = True
                continue
            # 래칫: 추세 방향으로만 밴드 갱신
            upper[i] = min(upper_basic[i], upper[i - 1]) if close[i - 1] <= upper[i - 1] else upper_basic[i]
            lower[i] = max(lower_basic[i], lower[i - 1]) if close[i - 1] >= lower[i - 1] else lower_basic[i]
            if trend[i - 1] >= 0:
                trend[i] = -1 if close[i] < lower[i] else 1
            else:
                trend[i] = 1 if close[i] > upper[i] else -1
        # 워밍업 구간은 0
        warmup = self.period + 1
        trend[:warmup] = 0
        return pd.Series(trend, index=df.index)
