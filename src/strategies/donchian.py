"""돈치안 채널 돌파 (터틀 트레이딩, Richard Dennis/Richard Donchian).

진입: 종가가 직전 entry_n 캔들 최고가 돌파 → 롱 (최저가 이탈 → 숏)
청산: 종가가 직전 exit_n 캔들 반대편 극값 이탈
터틀 오리지널은 20/10 (시스템1), 55/20 (시스템2).
"""
import pandas as pd

from .base import BaseStrategy


class Donchian(BaseStrategy):
    name = "donchian"

    def __init__(self, entry_n: int = 20, exit_n: int = 10):
        super().__init__(entry_n=entry_n, exit_n=exit_n)
        self.entry_n, self.exit_n = entry_n, exit_n

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        # 직전 N캔들 (현재 캔들 제외 — shift(1)) 극값
        entry_hi = df["high"].rolling(self.entry_n).max().shift(1)
        entry_lo = df["low"].rolling(self.entry_n).min().shift(1)
        exit_hi = df["high"].rolling(self.exit_n).max().shift(1)
        exit_lo = df["low"].rolling(self.exit_n).min().shift(1)
        close = df["close"].to_numpy()
        e_hi, e_lo = entry_hi.to_numpy(), entry_lo.to_numpy()
        x_hi, x_lo = exit_hi.to_numpy(), exit_lo.to_numpy()

        out = [0] * len(df)
        position = 0
        for i in range(len(df)):
            if pd.isna(e_hi[i]):
                position = 0
            elif position == 0:
                if close[i] > e_hi[i]:
                    position = 1
                elif close[i] < e_lo[i]:
                    position = -1
            elif position == 1 and close[i] < x_lo[i]:
                position = 0
            elif position == -1 and close[i] > x_hi[i]:
                position = 0
            out[i] = position
        return pd.Series(out, index=df.index)
