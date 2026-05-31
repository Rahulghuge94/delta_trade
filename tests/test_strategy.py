from decimal import Decimal
from datetime import datetime, timedelta, timezone

from delta_paper_trader.broker import PaperBroker
from delta_paper_trader.models import Candle, Side
from delta_paper_trader.strategy import BreakoutMomentumStrategy, build_strategy, strategy_catalog


def candle(price: str) -> Candle:
    value = Decimal(price)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Candle(
        symbol="BTCUSD",
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("1"),
        start=start,
        end=start + timedelta(minutes=1),
    )


def test_catalog_lists_momentum_strategies() -> None:
    codes = {item["code"] for item in strategy_catalog()}
    assert {"ma_cross", "breakout", "ema_impulse", "rsi_momentum", "vwap_momentum"} <= codes


def test_build_strategy_accepts_params() -> None:
    strategy = build_strategy("breakout", Decimal("2"), {"lookback": 3})
    assert isinstance(strategy, BreakoutMomentumStrategy)
    assert strategy.trade_quantity == Decimal("2")
    assert strategy.lookback == 3


def test_breakout_strategy_generates_buy_signal() -> None:
    strategy = BreakoutMomentumStrategy(trade_quantity=Decimal("1"), lookback=3)
    broker = PaperBroker(fee_bps=Decimal("0"), slippage_bps=Decimal("0"))

    assert strategy.on_candle(candle("100"), broker).side is None
    assert strategy.on_candle(candle("101"), broker).side is None
    assert strategy.on_candle(candle("102"), broker).side is None

    signal = strategy.on_candle(candle("103"), broker)

    assert signal.side is Side.BUY
    assert signal.quantity == Decimal("1")
