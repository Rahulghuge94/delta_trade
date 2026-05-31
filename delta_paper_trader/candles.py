from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from delta_paper_trader.models import Candle, Quote


@dataclass
class MutableCandle:
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    start: datetime
    end: datetime

    def update(self, quote: Quote) -> None:
        price = quote.mid
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += _quote_volume(quote)

    def freeze(self) -> Candle:
        return Candle(
            symbol=self.symbol,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            start=self.start,
            end=self.end,
        )


class CandleAggregator:
    def __init__(self, timeframe_seconds: int = 60) -> None:
        self.timeframe_seconds = timeframe_seconds
        self.current: dict[str, MutableCandle] = {}

    def update(self, quote: Quote) -> Candle | None:
        timestamp = quote.timestamp if quote.timestamp_us else datetime.now(timezone.utc)
        start = _bucket_start(timestamp, self.timeframe_seconds)
        active = self.current.get(quote.symbol)

        if active is None:
            self.current[quote.symbol] = _new_candle(quote, start, self.timeframe_seconds)
            return None

        if start >= active.end:
            closed = active.freeze()
            self.current[quote.symbol] = _new_candle(quote, start, self.timeframe_seconds)
            return closed

        active.update(quote)
        return None

    def active_candles(self) -> list[Candle]:
        return [candle.freeze() for candle in self.current.values()]


def _new_candle(quote: Quote, start: datetime, timeframe_seconds: int) -> MutableCandle:
    price = quote.mid
    return MutableCandle(
        symbol=quote.symbol,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=_quote_volume(quote),
        start=start,
        end=start + timedelta(seconds=timeframe_seconds),
    )


def _bucket_start(timestamp: datetime, timeframe_seconds: int) -> datetime:
    timestamp = timestamp.astimezone(timezone.utc)
    epoch_seconds = int(timestamp.timestamp())
    bucket = epoch_seconds - (epoch_seconds % timeframe_seconds)
    return datetime.fromtimestamp(bucket, tz=timezone.utc)


def _quote_volume(quote: Quote) -> Decimal:
    return max(quote.bid_size + quote.ask_size, Decimal("1"))
