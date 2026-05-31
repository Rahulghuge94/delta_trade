from datetime import datetime, timezone
from decimal import Decimal

from delta_paper_trader.candles import CandleAggregator
from delta_paper_trader.models import Quote


def quote(price: str, minute: int, second: int) -> Quote:
    timestamp = datetime(2026, 1, 1, 0, minute, second, tzinfo=timezone.utc)
    value = Decimal(price)
    return Quote(
        symbol="BTCUSD",
        bid=value,
        ask=value,
        bid_size=Decimal("2"),
        ask_size=Decimal("3"),
        timestamp_us=int(timestamp.timestamp() * 1_000_000),
        raw={},
    )


def test_aggregator_closes_one_minute_candle() -> None:
    aggregator = CandleAggregator(timeframe_seconds=60)

    assert aggregator.update(quote("100", 0, 1)) is None
    assert aggregator.update(quote("105", 0, 30)) is None
    closed = aggregator.update(quote("101", 1, 0))

    assert closed is not None
    assert closed.open == Decimal("100")
    assert closed.high == Decimal("105")
    assert closed.low == Decimal("100")
    assert closed.close == Decimal("105")
    assert closed.volume == Decimal("10")
