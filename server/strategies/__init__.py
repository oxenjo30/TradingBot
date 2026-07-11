from .base import Strategy
from .manual import ManualStrategy
from .sma_cross import SMACrossover
from .rsi_mr import RSIMeanReversion
from .momentum import MomentumBreakout
from .bollinger import BollingerBandMeanReversion
from .breakout_52w import Breakout52Week
from .macd_volume import MACDVolume
from .golden_cross import GoldenCross
from .crypto_trend import CryptoTrend
from .crypto_rsi_bounce import CryptoRSIBounce
from .crypto_volatility_breakout import CryptoVolatilityBreakout
from .crypto_grid import CryptoGrid
from .ema_confluence import EMAConfluence
from .chart_patterns import ClassicPatterns
from .liquid_stock_trend import LiquidStockTrend
from .btc_eth_trend import BtcEthTrend
from .dual_momentum import DualMomentum

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
        CryptoTrend,
        CryptoRSIBounce,
        CryptoVolatilityBreakout,
        CryptoGrid,
        EMAConfluence,
        ClassicPatterns,
        # Task 8 research candidates — registered but auto_trade=False, so they
        # exist in the registry yet are NOT auto-assigned or enabled by default.
        LiquidStockTrend,
        BtcEthTrend,
        DualMomentum,
    )
}


def build(name: str, params: dict) -> Strategy:
    if name not in REGISTRY:
        raise ValueError(f"Unknown strategy: {name}")
    return REGISTRY[name](params)


def describe_all() -> list[dict]:
    return [cls.describe() for cls in REGISTRY.values()]
