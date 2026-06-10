"""MACD 모멘텀 — MACD선/시그널선 크로스오버 양방향."""
import pandas as pd
import ta

from .base import BaseStrategy


class MacdMomentum(BaseStrategy):
    name = "macd_momentum"

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        super().__init__(fast=fast, slow=slow, signal=signal)
        self.fast, self.slow, self.signal = fast, slow, signal

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        macd = ta.trend.MACD(df["close"], window_fast=self.fast,
                             window_slow=self.slow, window_sign=self.signal)
        line, sig_line = macd.macd(), macd.macd_signal()
        out = pd.Series(0, index=df.index)
        out[line > sig_line] = 1
        out[line < sig_line] = -1
        out[sig_line.isna()] = 0
        return out
