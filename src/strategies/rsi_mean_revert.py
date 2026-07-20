"""RSI 평균회귀 전략 — 과매도 진입, 중립 복귀 시 청산."""
import pandas as pd
import ta

from .base import BaseStrategy


class RsiMeanRevert(BaseStrategy):
    name = "rsi_mean_revert"

    def __init__(self, period: int = 14, oversold: int = 30, overbought: int = 70,
                 exit_level: int = 50):
        super().__init__(period=period, oversold=oversold, overbought=overbought,
                         exit_level=exit_level)
        self.period, self.oversold = period, oversold
        self.overbought, self.exit_level = overbought, exit_level

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        rsi = ta.momentum.RSIIndicator(df["close"], window=self.period).rsi()
        sig = pd.Series(0, index=df.index)
        position = 0
        values = rsi.to_numpy()
        out = sig.to_numpy(copy=True)  # pandas 3 CoW: 뷰는 읽기 전용
        for i, r in enumerate(values):
            if pd.isna(r):
                position = 0
            elif position == 0:
                if r < self.oversold:
                    position = 1   # 과매도 → 롱
                elif r > self.overbought:
                    position = -1  # 과매수 → 숏
            elif position == 1 and r >= self.exit_level:
                position = 0       # 중립 복귀 → 청산
            elif position == -1 and r <= self.exit_level:
                position = 0
            out[i] = position
        return pd.Series(out, index=df.index)
