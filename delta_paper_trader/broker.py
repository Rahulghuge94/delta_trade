from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from delta_paper_trader.models import Fill, Position, Quote, Side, Signal


@dataclass
class PaperBroker:
    initial_balance: Decimal = Decimal("10000")
    fee_bps: Decimal = Decimal("5")
    slippage_bps: Decimal = Decimal("1")
    max_abs_position: Decimal = Decimal("10")
    positions: dict[str, Position] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)
    cash: Decimal = field(init=False)

    def __post_init__(self) -> None:
        self.cash = self.initial_balance

    def mark(self, quote: Quote) -> None:
        position = self.positions.setdefault(quote.symbol, Position(symbol=quote.symbol))
        position.last_mark = quote.mid
        if position.quantity > 0:
            position.highest_price = max(position.highest_price or quote.mid, quote.mid)
        elif position.quantity < 0:
            position.lowest_price = min(position.lowest_price or quote.mid, quote.mid)

    def position_for(self, symbol: str) -> Position:
        return self.positions.setdefault(symbol, Position(symbol=symbol))

    def execute_signal(self, quote: Quote, signal: Signal) -> Fill | None:
        if signal.side is None or signal.quantity <= 0:
            return None

        position = self.position_for(quote.symbol)
        signed_delta = signal.quantity if signal.side is Side.BUY else -signal.quantity
        projected = position.quantity + signed_delta
        if abs(projected) > self.max_abs_position:
            return None

        price = self._fill_price(quote, signal.side)
        base_fee = abs(signal.quantity * price) * self.fee_bps / Decimal("10000")
        gst = base_fee * Decimal("0.18")
        fee = base_fee + gst
        realized = self._apply_fill(position, signed_delta, price)
        position.fees_paid += base_fee
        position.gst_paid += gst
        position.last_mark = quote.mid
        self.cash += realized - fee

        fill = Fill(
            symbol=quote.symbol,
            side=signal.side,
            quantity=signal.quantity,
            price=price,
            fee=base_fee,
            gst=gst,
            realized_pnl=realized,
            timestamp=quote.timestamp if quote.timestamp_us else datetime.now(timezone.utc),
            reason=signal.reason,
        )
        self.fills.append(fill)
        return fill

    def equity(self) -> Decimal:
        return self.cash + sum(position.unrealized_pnl for position in self.positions.values())

    def _fill_price(self, quote: Quote, side: Side) -> Decimal:
        slip = self.slippage_bps / Decimal("10000")
        if side is Side.BUY:
            return quote.ask * (Decimal("1") + slip)
        return quote.bid * (Decimal("1") - slip)

    @staticmethod
    def _apply_fill(position: Position, signed_delta: Decimal, price: Decimal) -> Decimal:
        old_qty = position.quantity
        new_qty = old_qty + signed_delta

        if old_qty == 0 or (old_qty > 0 and signed_delta > 0) or (old_qty < 0 and signed_delta < 0):
            total_qty = abs(old_qty) + abs(signed_delta)
            position.avg_entry = ((position.avg_entry * abs(old_qty)) + (price * abs(signed_delta))) / total_qty
            position.quantity = new_qty
            if old_qty == 0:
                position.highest_price = price
                position.lowest_price = price
            else:
                position.highest_price = max(position.highest_price or price, price)
                position.lowest_price = min(position.lowest_price or price, price)
            return Decimal("0")

        closed_qty = min(abs(old_qty), abs(signed_delta))
        old_direction = Decimal("1") if old_qty > 0 else Decimal("-1")
        realized = (price - position.avg_entry) * closed_qty * old_direction
        position.realized_pnl += realized

        position.quantity = new_qty
        if new_qty == 0:
            position.avg_entry = Decimal("0")
            position.highest_price = Decimal("0")
            position.lowest_price = Decimal("0")
        elif (old_qty > 0 > new_qty) or (old_qty < 0 < new_qty):
            position.avg_entry = price
            position.highest_price = price
            position.lowest_price = price

        return realized
