"""전략 베이스 클래스.

모든 전략은 generate_signals(df)를 구현한다.
입력: OHLCV DataFrame (open/high/low/close/volume 컬럼)
출력: 포지션 시그널 Series — 1(롱), 0(현금), -1(숏; 현물에선 0으로 취급)
시그널은 해당 캔들 종가 기준으로 계산되고, 체결은 다음 캔들에서 일어난다(백테스터 책임).
"""
from abc import ABC, abstractmethod

import pandas as pd


class BaseStrategy(ABC):
    name: str = "base"

    def __init__(self, **params):
        self.params = params

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        ...

    def __repr__(self):
        p = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.name}({p})"
