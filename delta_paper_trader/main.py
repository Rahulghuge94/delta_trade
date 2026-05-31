from __future__ import annotations

import argparse
import asyncio
import logging
from decimal import Decimal

from delta_paper_trader.broker import PaperBroker
from delta_paper_trader.candles import CandleAggregator
from delta_paper_trader.delta_ws import DeltaPublicStream
from delta_paper_trader.strategy import MovingAverageCrossStrategy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Delta Exchange public-feed paper trader")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSD"], help="Delta symbols, for example BTCUSD ETHUSD")
    parser.add_argument("--balance", default="10000", help="Starting paper balance")
    parser.add_argument("--qty", default="1", help="Contracts per new strategy position")
    parser.add_argument("--max-position", default="3", help="Maximum absolute contracts per symbol")
    parser.add_argument("--fast", type=int, default=8, help="Fast moving average window")
    parser.add_argument("--slow", type=int, default=21, help="Slow moving average window")
    parser.add_argument("--channel", default="ob_l1", choices=["ob_l1", "ticker"], help="Public channel to consume")
    parser.add_argument("--url", default="wss://public-socket.india.delta.exchange", help="Delta public WebSocket URL")
    parser.add_argument("--timeframe-seconds", type=int, default=60, help="Candle timeframe in seconds")
    parser.add_argument("--max-quotes", type=int, default=0, help="Stop after this many quotes; 0 runs forever")
    return parser


async def run(args: argparse.Namespace) -> None:
    broker = PaperBroker(
        initial_balance=Decimal(args.balance),
        max_abs_position=Decimal(args.max_position),
    )
    strategy = MovingAverageCrossStrategy(
        trade_quantity=Decimal(args.qty),
        fast_window=args.fast,
        slow_window=args.slow,
    )
    stream = DeltaPublicStream(symbols=args.symbols, url=args.url, channel=args.channel)
    candles = CandleAggregator(timeframe_seconds=args.timeframe_seconds)

    quote_count = 0
    async for quote in stream.quotes():
        quote_count += 1
        broker.mark(quote)
        candle = candles.update(quote)
        if candle is None:
            logging.info(
                "QUOTE %s bid=%s ask=%s building=%ss pos=%s equity=%s",
                quote.symbol,
                quote.bid,
                quote.ask,
                args.timeframe_seconds,
                broker.position_for(quote.symbol).quantity,
                broker.equity(),
            )
            if args.max_quotes and quote_count >= args.max_quotes:
                break
            continue

        signal = strategy.on_candle(candle, broker)
        fill = broker.execute_signal(quote, signal)
        position = broker.position_for(quote.symbol)

        if fill:
            logging.info(
                "FILL %s %s qty=%s price=%s fee=%s realized=%s reason=%s",
                fill.symbol,
                fill.side.value.upper(),
                fill.quantity,
                fill.price,
                fill.fee,
                fill.realized_pnl,
                fill.reason,
            )

        logging.info(
            "QUOTE %s bid=%s ask=%s pos=%s avg=%s equity=%s unrealized=%s",
            quote.symbol,
            quote.bid,
            quote.ask,
            position.quantity,
            position.avg_entry,
            broker.equity(),
            position.unrealized_pnl,
        )

        if args.max_quotes and quote_count >= args.max_quotes:
            break


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    main()
