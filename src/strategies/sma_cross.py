"""SMA 골든크로스/데드크로스 추세추종 전략."""
import pandas as pd

from .base import BaseStrategy


class SmaCross(BaseStrategy):
    name = "sma_cross"

    def __init__(self, fast: int = 20, slow: int = 60):
        super().__init__(fast=fast, slow=slow)
        if fast >= slow:
            raise ValueError("fast는 slow보다 작아야 함")
        self.fast, self.slow = fast, slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast = df["close"].rolling(self.fast).mean()
        slow = df["close"].rolling(self.slow).mean()
        sig = pd.Series(0, index=df.index)
        sig[fast > slow] = 1   # 골든크로스 구간 롱
        sig[fast < slow] = -1  # 데드크로스 구간 숏
        sig[slow.isna()] = 0
        return sig
