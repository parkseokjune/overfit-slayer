from .base import BaseStrategy
from .bb_breakout import BbBreakout
from .donchian import Donchian
from .macd_momentum import MacdMomentum
from .rsi_mean_revert import RsiMeanRevert
from .sma_cross import SmaCross
from .supertrend import Supertrend
from .vol_breakout import VolBreakout

ALL_STRATEGIES = {
    "sma_cross": SmaCross,
    "rsi_mean_revert": RsiMeanRevert,
    "bb_breakout": BbBreakout,
    "donchian": Donchian,
    "vol_breakout": VolBreakout,
    "supertrend": Supertrend,
    "macd_momentum": MacdMomentum,
}


def build_strategies(cfg: dict):
    """config.yaml의 strategies 섹션으로 전략 인스턴스 생성."""
    return [ALL_STRATEGIES[name](**params)
            for name, params in cfg.get("strategies", {}).items()
            if name in ALL_STRATEGIES]
