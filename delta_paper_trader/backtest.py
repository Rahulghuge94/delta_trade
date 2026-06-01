from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from delta_paper_trader.broker import PaperBroker
from delta_paper_trader.models import Candle, Quote
from delta_paper_trader.strategy import build_strategy


def run_backtest(payload: dict[str, Any]) -> dict[str, Any]:
    candles = [_parse_candle(row) for row in payload.get("candles", [])]
    if not candles:
        raise ValueError("Backtest requires at least one candle")

    capital = _decimal(payload.get("capital", "10000"))
    quantity = _decimal(payload.get("quantity", "1"))
    fee_bps = _decimal(payload.get("fee_bps", "5"))
    slippage_bps = _decimal(payload.get("slippage_bps", "1"))
    max_position = _decimal(payload.get("max_position", "3"))

    broker = PaperBroker(
        initial_balance=capital,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        max_abs_position=max_position,
    )
    strategy = build_strategy(
        payload.get("strategy_type", "ma_cross"),
        quantity,
        _decimal(payload.get("sl_pct", "0")),
        _decimal(payload.get("target_pct", "0")),
        _decimal(payload.get("trailing_sl_pct", "0")),
        payload.get("params") or {},
    )

    equity_curve = []
    signal_log = []
    for candle in candles:
        quote = _quote_from_candle(candle)
        broker.mark(quote)
        signal = strategy.on_candle(candle, broker)
        fill = broker.execute_signal(quote, signal)
        broker.mark(quote)
        equity_curve.append(
            {
                "time": candle.end.isoformat(),
                "equity": str(broker.equity()),
                "close": str(candle.close),
            }
        )
        if fill:
            signal_log.append(
                {
                    "time": fill.timestamp.isoformat(),
                    "symbol": fill.symbol,
                    "side": fill.side.value,
                    "quantity": str(fill.quantity),
                    "price": str(fill.price),
                    "realized_pnl": str(fill.realized_pnl),
                    "reason": fill.reason,
                }
            )

    final_equity = broker.equity()
    total_fees = sum(position.fees_paid for position in broker.positions.values())
    total_gst = sum(position.gst_paid for position in broker.positions.values())
    realized_fills = [fill for fill in broker.fills if fill.realized_pnl != 0]
    winning_fills = [fill for fill in realized_fills if fill.realized_pnl > 0]
    gross_profit = sum(fill.realized_pnl for fill in realized_fills if fill.realized_pnl > 0)
    gross_loss = abs(sum(fill.realized_pnl for fill in realized_fills if fill.realized_pnl < 0))

    return {
        "summary": {
            "candles": len(candles),
            "fills": len(broker.fills),
            "starting_equity": str(capital),
            "final_equity": str(final_equity),
            "total_return": str(final_equity - capital),
            "total_return_pct": str(((final_equity - capital) / capital) * Decimal("100") if capital else Decimal("0")),
            "max_drawdown": str(_max_drawdown([Decimal(point["equity"]) for point in equity_curve])),
            "win_rate": str((Decimal(len(winning_fills)) / Decimal(len(realized_fills))) * Decimal("100") if realized_fills else Decimal("0")),
            "profit_factor": str(gross_profit / gross_loss if gross_loss else Decimal("0")),
            "fees_paid": str(total_fees),
            "gst_paid": str(total_gst),
        },
        "equity_curve": equity_curve,
        "fills": signal_log,
    }


def _parse_candle(row: dict[str, Any]) -> Candle:
    start = _parse_time(row.get("start") or row.get("time") or row.get("timestamp"))
    end = _parse_time(row.get("end")) if row.get("end") else start
    return Candle(
        symbol=str(row.get("symbol", "BTCUSD")).upper(),
        open=_decimal(row["open"]),
        high=_decimal(row["high"]),
        low=_decimal(row["low"]),
        close=_decimal(row["close"]),
        volume=_decimal(row.get("volume", "1")),
        start=start,
        end=end,
    )


def _quote_from_candle(candle: Candle) -> Quote:
    timestamp_us = int(candle.end.timestamp() * 1_000_000)
    return Quote(
        symbol=candle.symbol,
        bid=candle.close,
        ask=candle.close,
        bid_size=max(candle.volume, Decimal("1")),
        ask_size=max(candle.volume, Decimal("1")),
        timestamp_us=timestamp_us,
        raw={},
    )


def _parse_time(value: Any) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _max_drawdown(equity_values: list[Decimal]) -> Decimal:
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for equity in equity_values:
        peak = max(peak, equity)
        if peak:
            max_drawdown = max(max_drawdown, ((peak - equity) / peak) * Decimal("100"))
    return max_drawdown
