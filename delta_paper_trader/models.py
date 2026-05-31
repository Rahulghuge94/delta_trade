from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    timestamp_us: int
    raw: dict[str, Any]

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp_us / 1_000_000, tz=timezone.utc)


@dataclass(frozen=True)
class Signal:
    side: Side | None
    quantity: Decimal = Decimal("0")
    reason: str = "hold"

    @classmethod
    def hold(cls, reason: str = "hold") -> "Signal":
        return cls(side=None, reason=reason)


@dataclass(frozen=True)
class Candle:
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    start: datetime
    end: datetime

    @property
    def typical_price(self) -> Decimal:
        return (self.high + self.low + self.close) / Decimal("3")


@dataclass(frozen=True)
class Fill:
    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal
    fee: Decimal
    realized_pnl: Decimal
    timestamp: datetime
    reason: str
    gst: Decimal = Decimal("0")


@dataclass
class Position:
    symbol: str
    quantity: Decimal = Decimal("0")
    avg_entry: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    fees_paid: Decimal = Decimal("0")
    last_mark: Decimal = Decimal("0")
    gst_paid: Decimal = Decimal("0")
    highest_price: Decimal = Decimal("0")
    lowest_price: Decimal = Decimal("0")

    @property
    def side(self) -> str:
        if self.quantity > 0:
            return "long"
        if self.quantity < 0:
            return "short"
        return "flat"

    @property
    def unrealized_pnl(self) -> Decimal:
        if self.quantity == 0 or self.last_mark == 0:
            return Decimal("0")
        return (self.last_mark - self.avg_entry) * self.quantity

    @property
    def net_pnl(self) -> Decimal:
        return self.realized_pnl + self.unrealized_pnl - self.fees_paid - self.gst_paid
