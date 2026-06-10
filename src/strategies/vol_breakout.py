"""래리 윌리엄스 변동성 돌파.

원전(Long-term Secrets to Short-term Trading): 당일 가격이
시가 + k × (전일 고가-저가)를 넘으면 진입, 당일 종가/익일 시가에 청산.

캔들 단위 적응: 캔들 t에서 close[t] > open[t] + k × range[t-1] → 다음 캔들 1개 보유.
하방 돌파는 숏. 보유기간이 1캔들이라 회전이 빠름 → 수수료 민감.
"""
import pandas as pd

from .base import BaseStrategy


class VolBreakout(BaseStrategy):
    name = "vol_breakout"

    def __init__(self, k: float = 0.5):
        super().__init__(k=k)
        self.k = k

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        prev_range = (df["high"] - df["low"]).shift(1)
        up_th = df["open"] + self.k * prev_range
        dn_th = df["open"] - self.k * prev_range
        sig = pd.Series(0, index=df.index)
        sig[df["close"] > up_th] = 1
        sig[df["close"] < dn_th] = -1
        sig[prev_range.isna()] = 0
        return sig
