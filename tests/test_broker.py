from decimal import Decimal

from delta_paper_trader.broker import PaperBroker
from delta_paper_trader.models import Quote, Side, Signal


def quote(bid: str, ask: str) -> Quote:
    return Quote(
        symbol="BTCUSD",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=Decimal("1"),
        ask_size=Decimal("1"),
        timestamp_us=0,
        raw={},
    )


def test_long_close_realizes_profit_minus_fees() -> None:
    broker = PaperBroker(fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    broker.execute_signal(quote("99", "100"), Signal(Side.BUY, Decimal("1"), "entry"))
    broker.execute_signal(quote("110", "111"), Signal(Side.SELL, Decimal("1"), "exit"))

    position = broker.position_for("BTCUSD")
    assert position.quantity == Decimal("0")
    assert position.realized_pnl == Decimal("10")
    assert broker.cash == Decimal("10010")


def test_short_close_realizes_profit_minus_fees() -> None:
    broker = PaperBroker(fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    broker.execute_signal(quote("100", "101"), Signal(Side.SELL, Decimal("1"), "entry"))
    broker.execute_signal(quote("90", "91"), Signal(Side.BUY, Decimal("1"), "exit"))

    position = broker.position_for("BTCUSD")
    assert position.quantity == Decimal("0")
    assert position.realized_pnl == Decimal("9")
    assert broker.cash == Decimal("10009")


def test_default_fee_is_delta_futures_taker_rate() -> None:
    broker = PaperBroker(slippage_bps=Decimal("0"))
    fill = broker.execute_signal(quote("99", "100"), Signal(Side.BUY, Decimal("1"), "entry"))

    assert fill is not None
    assert fill.fee == Decimal("0.05")
    # Base fee 0.05 + 18% GST (0.009) = 0.059 total fee
    assert broker.cash == Decimal("9999.941")


def test_gst_calculation_and_tracking() -> None:
    broker = PaperBroker(fee_bps=Decimal("5"), slippage_bps=Decimal("0"))
    fill = broker.execute_signal(quote("99", "100"), Signal(Side.BUY, Decimal("1"), "entry"))

    assert fill is not None
    assert fill.fee == Decimal("0.05")
    assert fill.gst == Decimal("0.009")

    position = broker.position_for("BTCUSD")
    assert position.fees_paid == Decimal("0.05")
    assert position.gst_paid == Decimal("0.009")
    assert position.net_pnl == Decimal("-0.559")
    assert broker.cash == Decimal("9999.941")


def test_stop_loss_trigger() -> None:
    from delta_paper_trader.strategy import Strategy
    from delta_paper_trader.models import Candle
    from dataclasses import dataclass
    from datetime import datetime, timezone

    @dataclass
    class MyMock(Strategy):
        def generate_signal(self, candle: Candle, broker: PaperBroker) -> Signal:
            return Signal.hold()

    broker = PaperBroker(fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    broker.execute_signal(quote("99", "100"), Signal(Side.BUY, Decimal("1"), "entry"))

    # 2% Stop Loss -> triggers if candle.low <= 98
    strategy = MyMock(trade_quantity=Decimal("1"), sl_pct=Decimal("2"))

    c1 = Candle("BTCUSD", Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("100"), datetime.now(timezone.utc), datetime.now(timezone.utc))
    sig1 = strategy.on_candle(c1, broker)
    assert sig1.side is None

    c2 = Candle("BTCUSD", Decimal("100"), Decimal("101"), Decimal("97.5"), Decimal("98"), Decimal("100"), datetime.now(timezone.utc), datetime.now(timezone.utc))
    sig2 = strategy.on_candle(c2, broker)
    assert sig2.side == Side.SELL
    assert sig2.quantity == Decimal("1")
    assert "Stop Loss triggered" in sig2.reason


def test_take_profit_trigger() -> None:
    from delta_paper_trader.strategy import Strategy
    from delta_paper_trader.models import Candle
    from dataclasses import dataclass
    from datetime import datetime, timezone

    @dataclass
    class MyMock(Strategy):
        def generate_signal(self, candle: Candle, broker: PaperBroker) -> Signal:
            return Signal.hold()

    broker = PaperBroker(fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    broker.execute_signal(quote("99", "100"), Signal(Side.BUY, Decimal("1"), "entry"))

    # 5% Target -> triggers if candle.high >= 105
    strategy = MyMock(trade_quantity=Decimal("1"), target_pct=Decimal("5"))

    c1 = Candle("BTCUSD", Decimal("100"), Decimal("104"), Decimal("99"), Decimal("100"), Decimal("100"), datetime.now(timezone.utc), datetime.now(timezone.utc))
    sig1 = strategy.on_candle(c1, broker)
    assert sig1.side is None

    c2 = Candle("BTCUSD", Decimal("100"), Decimal("106"), Decimal("99"), Decimal("105"), Decimal("100"), datetime.now(timezone.utc), datetime.now(timezone.utc))
    sig2 = strategy.on_candle(c2, broker)
    assert sig2.side == Side.SELL
    assert sig2.quantity == Decimal("1")
    assert "Target Take Profit triggered" in sig2.reason


def test_trailing_stop_loss_trigger() -> None:
    from delta_paper_trader.strategy import Strategy
    from delta_paper_trader.models import Candle
    from dataclasses import dataclass
    from datetime import datetime, timezone

    @dataclass
    class MyMock(Strategy):
        def generate_signal(self, candle: Candle, broker: PaperBroker) -> Signal:
            return Signal.hold()

    broker = PaperBroker(fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    broker.execute_signal(quote("99", "100"), Signal(Side.BUY, Decimal("1"), "entry"))

    # 2% Trailing SL
    strategy = MyMock(trade_quantity=Decimal("1"), trailing_sl_pct=Decimal("2"))

    # Pushes high watermark to 110. Trailing level = 110 * 0.98 = 107.8.
    # Candle low is 108 (no trigger).
    c1 = Candle("BTCUSD", Decimal("100"), Decimal("110"), Decimal("108"), Decimal("109"), Decimal("100"), datetime.now(timezone.utc), datetime.now(timezone.utc))
    sig1 = strategy.on_candle(c1, broker)
    assert sig1.side is None
    assert broker.position_for("BTCUSD").highest_price == Decimal("110")

    # Drops low to 107, which is below 107.8 -> triggers Trailing SL!
    c2 = Candle("BTCUSD", Decimal("109"), Decimal("109"), Decimal("107"), Decimal("107.5"), Decimal("100"), datetime.now(timezone.utc), datetime.now(timezone.utc))
    sig2 = strategy.on_candle(c2, broker)
    assert sig2.side == Side.SELL
    assert sig2.quantity == Decimal("1")
    assert "Trailing Stop Loss triggered" in sig2.reason
