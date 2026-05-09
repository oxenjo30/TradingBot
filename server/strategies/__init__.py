from .base import Strategy
from .manual import ManualStrategy
from .sma_cross import SMACrossover
from .rsi_mr import RSIMeanReversion
from .momentum import MomentumBreakout
from .bollinger import BollingerBandMeanReversion
from .breakout_52w import Breakout52Week
from .macd_volume import MACDVolume
from .golden_cross import GoldenCross

REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (
        ManualStrategy,
        SMACrossover,
        RSIMeanReversion,
        MomentumBreakout,
        BollingerBandMeanReversion,
        Breakout52Week,
        MACDVolume,
        GoldenCross,
    )
}


def build(name: str, params: dict) -> Strategy:
    cls = REGISTRY[name]
    return cls(params)


def build(name: str, params: dict) -> Strategy:
    if name not in REGISTRY:
        raise ValueError(f"Unknown strategy: {name}")
    return REGISTRY[name](params)


def describe_all() -> list[dict]:
    return [cls.describe() for cls in REGISTRY.values()]
