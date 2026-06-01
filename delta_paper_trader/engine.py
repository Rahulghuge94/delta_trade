from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from delta_paper_trader.broker import PaperBroker
from delta_paper_trader.candles import CandleAggregator
from delta_paper_trader.delta_ws import DeltaPublicStream
from delta_paper_trader.models import Candle, Fill, Position, Quote
from delta_paper_trader.persistence import SQLiteTradeStore
from delta_paper_trader.strategy import build_strategy, strategy_catalog


TAKER_FEE_BPS = Decimal("5")
MAKER_FEE_BPS = Decimal("2")


@dataclass
class StrategyConfig:
    id: str
    name: str
    strategy_type: str
    symbols: list[str]
    capital: Decimal = Decimal("10000")
    quantity: Decimal = Decimal("1")
    max_position: Decimal = Decimal("3")
    fee_bps: Decimal = TAKER_FEE_BPS
    slippage_bps: Decimal = Decimal("1")
    enabled: bool = True
    sl_pct: Decimal = Decimal("0")
    target_pct: Decimal = Decimal("0")
    trailing_sl_pct: Decimal = Decimal("0")
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunningStrategy:
    config: StrategyConfig
    broker: PaperBroker
    strategy: Any
    quote_count: int = 0
    last_signal: str = "not_started"


class PaperTradingEngine:
    def __init__(
        self,
        url: str = "wss://public-socket.india.delta.exchange",
        channel: str = "ob_l1",
        timeframe_seconds: int = 60,
        db_path: str = "delta_paper_trader.sqlite3",
    ) -> None:
        self.url = url
        self.channel = channel
        self.timeframe_seconds = timeframe_seconds
        self.store = SQLiteTradeStore(db_path)
        self.configs: dict[str, StrategyConfig] = {}
        self.running: dict[str, RunningStrategy] = {}
        self.last_quotes: dict[str, Quote] = {}
        self.candle_aggregator = CandleAggregator(timeframe_seconds=timeframe_seconds)
        self.closed_candles: dict[str, list[Candle]] = {}
        self.last_error: str | None = None
        self.started_at: datetime | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._load_or_seed_configs()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _load_or_seed_configs(self) -> None:
        for payload in self.store.load_strategy_configs():
            config = self._config_from_payload(payload)
            self.configs[config.id] = config
        self.seed_defaults()

    def seed_defaults(self) -> None:
        if self.configs:
            return
        for strategy_type, name, capital, sl, target, trailing, params in [
        #     ("ma_cross", "BTC MA Cross", "10000", "1.5", "3.0", "0.0", {"fast_window": 8, "slow_window": 21}),
        #     ("breakout", "BTC Breakout", "10000", "1.0", "0.0", "2.0", {"lookback": 30}),
        #     ("ema_impulse", "ETH EMA Impulse", "10000", "2.0", "4.0", "0.0", {"fast_span": 8, "slow_span": 21, "min_spread_bps": "2"}),
        #     ("rsi_momentum", "ETH RSI Momentum", "10000", "1.5", "3.0", "0.0", {"period": 14, "long_threshold": "60", "short_threshold": "40"}),
        #     ("vwap_momentum", "BTC VWAP Momentum", "10000", "1.0", "0.0", "1.5", {"window": 50, "min_distance_bps": "3"}),
        # 
                ("ema9_100_pullback", "EMA 9_100 Pullback", "100000", "0.5", "3.0", "0.2", {"fast_window": 9, "slow_window": 100}),
        ]:
            symbols = ["ETHUSD"] if name.startswith("ETH") else ["BTCUSD"]
            self.add_strategy(
                {
                    "name": name,
                    "strategy_type": strategy_type,
                    "symbols": symbols,
                    "capital": capital,
                    "sl_pct": sl,
                    "target_pct": target,
                    "trailing_sl_pct": trailing,
                    "params": params,
                }
            )

    def add_strategy(self, payload: dict[str, Any]) -> StrategyConfig:
        config = self._config_from_payload(payload)
        self.configs[config.id] = config
        self.store.save_strategy_config(_config_to_dict(config))
        if self.is_running and config.enabled:
            self.running[config.id] = self._build_running_strategy(config)
            self.store.save_broker(config.id, self.running[config.id].broker)
        else:
            self.running.pop(config.id, None)
        return config

    @staticmethod
    def _config_from_payload(payload: dict[str, Any]) -> StrategyConfig:
        return StrategyConfig(
            id=payload.get("id") or uuid.uuid4().hex[:10],
            name=payload.get("name") or "Momentum strategy",
            strategy_type=payload.get("strategy_type") or "ma_cross",
            symbols=[str(symbol).upper() for symbol in payload.get("symbols", ["BTCUSD"])],
            capital=_decimal(payload.get("capital", "10000")),
            quantity=_decimal(payload.get("quantity", "1")),
            max_position=_decimal(payload.get("max_position", "3")),
            fee_bps=_decimal(payload.get("fee_bps", TAKER_FEE_BPS)),
            slippage_bps=_decimal(payload.get("slippage_bps", "1")),
            enabled=bool(payload.get("enabled", True)),
            sl_pct=_decimal(payload.get("sl_pct", "0")),
            target_pct=_decimal(payload.get("target_pct", "0")),
            trailing_sl_pct=_decimal(payload.get("trailing_sl_pct", "0")),
            params=_normalize_params(payload.get("params") or {}),
        )

    async def update_strategy(self, strategy_id: str, payload: dict[str, Any]) -> StrategyConfig:
        async with self._lock:
            config = self.configs[strategy_id]
            for key in ["name", "strategy_type", "enabled"]:
                if key in payload:
                    setattr(config, key, payload[key])
            if "symbols" in payload:
                config.symbols = [str(symbol).upper() for symbol in payload["symbols"]]
            for key in ["capital", "quantity", "max_position", "fee_bps", "slippage_bps", "sl_pct", "target_pct", "trailing_sl_pct"]:
                if key in payload:
                    setattr(config, key, _decimal(payload[key]))
            if "params" in payload:
                config.params = _normalize_params(payload["params"] or {})
            self.store.save_strategy_config(_config_to_dict(config))
            if self.is_running and config.enabled:
                self.running[strategy_id] = self._build_running_strategy(config)
                self.store.save_broker(strategy_id, self.running[strategy_id].broker)
            elif self.is_running:
                self.running.pop(strategy_id, None)
            else:
                self.running.pop(strategy_id, None)
            return config

    async def delete_strategy(self, strategy_id: str) -> None:
        async with self._lock:
            self.configs.pop(strategy_id, None)
            self.running.pop(strategy_id, None)
            self.store.delete_strategy(strategy_id)

    async def start(self, symbols: list[str] | None = None) -> None:
        async with self._lock:
            if self.is_running:
                return
            self.last_error = None
            self.started_at = datetime.now(timezone.utc)
            self.candle_aggregator = CandleAggregator(timeframe_seconds=self.timeframe_seconds)
            self.closed_candles = {}
            self.running = {
                config.id: self._build_running_strategy(config)
                for config in self.configs.values()
                if config.enabled
            }
            stream_symbols = sorted(set(symbols or self._enabled_symbols()))
            if not stream_symbols:
                raise ValueError("No enabled symbols to stream")
            self._task = asyncio.create_task(self._run_stream(stream_symbols))

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run_stream(self, symbols: list[str]) -> None:
        stream = DeltaPublicStream(symbols=symbols, url=self.url, channel=self.channel)
        try:
            async for quote in stream.quotes():
                await self.on_quote(quote)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            raise

    async def on_quote(self, quote: Quote) -> None:
        async with self._lock:
            self.last_quotes[quote.symbol] = quote
            closed_candle = self.candle_aggregator.update(quote)
            for item in self.running.values():
                if quote.symbol not in item.config.symbols:
                    continue
                item.quote_count += 1
                item.broker.mark(quote)
                if closed_candle is None:
                    item.last_signal = "building_1m_candle"
                    self.store.save_broker(item.config.id, item.broker)
                    continue
                self._store_candle(closed_candle)
                signal = item.strategy.on_candle(closed_candle, item.broker)
                item.last_signal = signal.reason
                item.broker.execute_signal(quote, signal)
                self.store.save_broker(item.config.id, item.broker)

    def _enabled_symbols(self) -> list[str]:
        return [symbol for config in self.configs.values() if config.enabled for symbol in config.symbols]

    def _build_running_strategy(self, config: StrategyConfig) -> RunningStrategy:
        broker = self.store.load_broker(
            config.id,
            initial_balance=config.capital,
            fee_bps=config.fee_bps,
            slippage_bps=config.slippage_bps,
            max_abs_position=config.max_position,
        ) or PaperBroker(
            initial_balance=config.capital,
            fee_bps=config.fee_bps,
            slippage_bps=config.slippage_bps,
            max_abs_position=config.max_position,
        )
        return RunningStrategy(
            config=config,
            broker=broker,
            strategy=build_strategy(
                config.strategy_type,
                config.quantity,
                config.sl_pct,
                config.target_pct,
                config.trailing_sl_pct,
                config.params,
            ),
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self.is_running,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "url": self.url,
            "channel": self.channel,
            "timeframe": "1m",
            "timeframe_seconds": self.timeframe_seconds,
            "fee_model": {
                "paper_fill": "market/taker",
                "futures_taker_bps": str(TAKER_FEE_BPS),
                "futures_maker_bps": str(MAKER_FEE_BPS),
                "gst_rate": "18%",
                "notes": "Defaults exclude funding, settlement fees, taxes, and account-specific VIP discounts. 18% GST is added on top of trading fees.",
            },
            "last_error": self.last_error,
            "catalog": strategy_catalog(),
            "quotes": {symbol: _quote_to_dict(quote) for symbol, quote in self.last_quotes.items()},
            "active_candles": {
                candle.symbol: _candle_to_dict(candle) for candle in self.candle_aggregator.active_candles()
            },
            "closed_candles": {
                symbol: [_candle_to_dict(candle) for candle in candles[-20:]]
                for symbol, candles in self.closed_candles.items()
            },
            "strategies": [self._strategy_snapshot(config) for config in self.configs.values()],
        }

    def _strategy_snapshot(self, config: StrategyConfig) -> dict[str, Any]:
        running = self.running.get(config.id)
        broker = running.broker if running else self._load_snapshot_broker(config)
        return {
            **_config_to_dict(config),
            "running": running is not None,
            "quote_count": running.quote_count if running else 0,
            "last_signal": running.last_signal if running else "stopped",
            "equity": str(broker.equity()) if broker else str(config.capital),
            "cash": str(broker.cash) if broker else str(config.capital),
            "positions": [_position_to_dict(position) for position in broker.positions.values()] if broker else [],
            "fills": [_fill_to_dict(fill) for fill in broker.fills[-25:]] if broker else [],
        }

    def _load_snapshot_broker(self, config: StrategyConfig) -> PaperBroker | None:
        return self.store.load_broker(
            config.id,
            initial_balance=config.capital,
            fee_bps=config.fee_bps,
            slippage_bps=config.slippage_bps,
            max_abs_position=config.max_position,
        )

    def _store_candle(self, candle: Candle) -> None:
        candles = self.closed_candles.setdefault(candle.symbol, [])
        if candles and candles[-1].start == candle.start:
            return
        candles.append(candle)
        if len(candles) > 500:
            del candles[:-500]


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, str):
            stripped = value.strip()
            if stripped == "":
                continue
            try:
                decimal_value = Decimal(stripped)
            except Exception:
                normalized[key] = stripped
            else:
                normalized[key] = int(decimal_value) if decimal_value == decimal_value.to_integral() else decimal_value
        else:
            normalized[key] = value
    return normalized


def _config_to_dict(config: StrategyConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "name": config.name,
        "strategy_type": config.strategy_type,
        "symbols": config.symbols,
        "capital": str(config.capital),
        "quantity": str(config.quantity),
        "max_position": str(config.max_position),
        "fee_bps": str(config.fee_bps),
        "slippage_bps": str(config.slippage_bps),
        "enabled": config.enabled,
        "sl_pct": str(config.sl_pct),
        "target_pct": str(config.target_pct),
        "trailing_sl_pct": str(config.trailing_sl_pct),
        "params": {key: str(value) for key, value in config.params.items()},
    }


def _quote_to_dict(quote: Quote) -> dict[str, Any]:
    return {
        "symbol": quote.symbol,
        "bid": str(quote.bid),
        "ask": str(quote.ask),
        "mid": str(quote.mid),
        "bid_size": str(quote.bid_size),
        "ask_size": str(quote.ask_size),
        "timestamp": quote.timestamp.isoformat() if quote.timestamp_us else None,
    }


def _candle_to_dict(candle: Candle) -> dict[str, Any]:
    return {
        "symbol": candle.symbol,
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "volume": str(candle.volume),
        "start": candle.start.isoformat(),
        "end": candle.end.isoformat(),
    }


def _position_to_dict(position: Position) -> dict[str, Any]:
    return {
        "symbol": position.symbol,
        "side": position.side,
        "quantity": str(position.quantity),
        "avg_entry": str(position.avg_entry),
        "realized_pnl": str(position.realized_pnl),
        "unrealized_pnl": str(position.unrealized_pnl),
        "fees_paid": str(position.fees_paid),
        "gst_paid": str(position.gst_paid),
        "highest_price": str(position.highest_price),
        "lowest_price": str(position.lowest_price),
        "net_pnl": str(position.net_pnl),
        "last_mark": str(position.last_mark),
    }


def _fill_to_dict(fill: Fill) -> dict[str, Any]:
    return {
        "symbol": fill.symbol,
        "side": fill.side.value,
        "quantity": str(fill.quantity),
        "price": str(fill.price),
        "fee": str(fill.fee),
        "gst": str(fill.gst),
        "realized_pnl": str(fill.realized_pnl),
        "timestamp": fill.timestamp.isoformat(),
        "reason": fill.reason,
    }
