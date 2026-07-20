"""볼린저밴드 상단 돌파 추세 전략 — 상단 돌파 시 롱, 중심선 이탈 시 청산."""
import pandas as pd
import ta

from .base import BaseStrategy


class BbBreakout(BaseStrategy):
    name = "bb_breakout"

    def __init__(self, period: int = 20, std: float = 2.0):
        super().__init__(period=period, std=std)
        self.period, self.std = period, std

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        bb = ta.volatility.BollingerBands(df["close"], window=self.period,
                                          window_dev=self.std)
        upper, mid, lower = bb.bollinger_hband(), bb.bollinger_mavg(), bb.bollinger_lband()
        close = df["close"].to_numpy()
        up, md, lo = upper.to_numpy(), mid.to_numpy(), lower.to_numpy()
        out = pd.Series(0, index=df.index).to_numpy(copy=True)  # pandas 3 CoW: 뷰는 읽기 전용
        position = 0
        for i in range(len(df)):
            if pd.isna(up[i]):
                position = 0
            elif position == 0:
                if close[i] > up[i]:
                    position = 1   # 상단 돌파 → 롱
                elif close[i] < lo[i]:
                    position = -1  # 하단 이탈 → 숏
            elif position == 1 and close[i] < md[i]:
                position = 0       # 중심선 복귀 → 청산
            elif position == -1 and close[i] > md[i]:
                position = 0
            out[i] = position
        return pd.Series(out, index=df.index)
