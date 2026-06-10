"""리스크 관리 — 손절/트레일링 스탑을 시그널 레벨에서 적용.

stop_loss_pct, trailing_pct는 **가격 변동** 기준이다 (증거금 손실 아님).
레버리지 L에서 가격 -2% 손절 = 증거금 -2L% 손실.
스탑 발동 후엔 원시 시그널이 0이 되거나 방향이 바뀔 때까지 재진입 금지.
"""
import numpy as np
import pandas as pd

from .strategies.base import BaseStrategy


def apply_stops(df: pd.DataFrame, signals: pd.Series,
                stop_loss_pct: float = 0.02,
                trailing_pct: float = None) -> pd.Series:
    close = df["close"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    raw = signals.to_numpy(dtype=float)
    out = np.zeros(len(raw))

    position = 0.0
    entry = extreme = 0.0
    blocked_sign = 0.0  # 스탑 발동 후 재진입 금지 방향

    for i in range(len(raw)):
        s = raw[i]
        if s == 0 or (blocked_sign != 0 and np.sign(s) != blocked_sign):
            blocked_sign = 0.0  # 원시 시그널이 끊기거나 방향이 바뀌면 블록 해제
        if position == 0:
            if s != 0 and np.sign(s) != blocked_sign:
                position, entry, extreme = s, close[i], close[i]
                out[i] = s
            continue

        if s != position:  # 원시 시그널이 청산/플립
            position = 0.0
            if s != 0 and np.sign(s) != blocked_sign:
                position, entry, extreme = s, close[i], close[i]
            out[i] = position
            continue

        # 보유 중: 스탑 체크 (이번 캔들 극값 기준)
        if position > 0:
            stop_hit = stop_loss_pct and (low[i] / entry - 1) <= -stop_loss_pct
            extreme = max(extreme, high[i])
            trail_hit = trailing_pct and (low[i] / extreme - 1) <= -trailing_pct
        else:
            stop_hit = stop_loss_pct and (high[i] / entry - 1) >= stop_loss_pct
            extreme = min(extreme, low[i])
            trail_hit = trailing_pct and (high[i] / extreme - 1) >= trailing_pct

        if stop_hit or trail_hit:
            blocked_sign = np.sign(position)
            position = 0.0
            out[i] = 0
        else:
            out[i] = position

    return pd.Series(out, index=signals.index)


class StopWrapped(BaseStrategy):
    """기존 전략에 손절/트레일링을 입히는 래퍼 — walk_forward에 그대로 전달 가능."""

    def __init__(self, inner: BaseStrategy, stop_loss_pct: float = 0.02,
                 trailing_pct: float = None):
        super().__init__(**inner.params, stop_loss_pct=stop_loss_pct,
                         trailing_pct=trailing_pct)
        self.inner = inner
        self.stop_loss_pct = stop_loss_pct
        self.trailing_pct = trailing_pct
        self.name = f"{inner.name}+stop"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return apply_stops(df, self.inner.generate_signals(df),
                           self.stop_loss_pct, self.trailing_pct)
