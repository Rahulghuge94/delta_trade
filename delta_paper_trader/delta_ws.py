from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from decimal import Decimal, InvalidOperation
from typing import Any

import websockets
from websockets.client import WebSocketClientProtocol

from delta_paper_trader.models import Quote

LOGGER = logging.getLogger(__name__)


class DeltaPublicStream:
    def __init__(
        self,
        symbols: list[str],
        url: str = "wss://public-socket.india.delta.exchange",
        channel: str = "ob_l1",
        heartbeat_timeout: float = 40.0,
    ) -> None:
        self.symbols = symbols
        self.url = url
        self.channel = channel
        self.heartbeat_timeout = heartbeat_timeout

    async def quotes(self) -> AsyncIterator[Quote]:
        while True:
            try:
                async with websockets.connect(self.url, ping_interval=30, ping_timeout=10) as ws:
                    await self._subscribe(ws)
                    async for quote in self._read_quotes(ws):
                        yield quote
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("stream disconnected; reconnecting in 3 seconds")
                await asyncio.sleep(3)

    async def _subscribe(self, ws: WebSocketClientProtocol) -> None:
        await ws.send(json.dumps({"type": "enable_heartbeat"}))
        await ws.send(
            json.dumps(
                {
                    "type": "subscribe",
                    "payload": {"channels": [{"name": self.channel, "symbols": self.symbols}]},
                }
            )
        )
        LOGGER.info("subscribed channel=%s symbols=%s", self.channel, ",".join(self.symbols))

    async def _read_quotes(self, ws: WebSocketClientProtocol) -> AsyncIterator[Quote]:
        last_heartbeat = time.monotonic()
        while True:
            timeout = max(1.0, self.heartbeat_timeout - (time.monotonic() - last_heartbeat))
            raw_message = await asyncio.wait_for(ws.recv(), timeout=timeout)
            message = json.loads(raw_message)

            if message.get("type") == "heartbeat":
                last_heartbeat = time.monotonic()
                continue
            if message.get("type") == "subscriptions":
                LOGGER.info("subscription response: %s", message)
                continue

            quote = self._parse_quote(message)
            if quote:
                yield quote

    def _parse_quote(self, message: dict[str, Any]) -> Quote | None:
        if message.get("type") == "ob_l1":
            return self._parse_ob_l1(message)
        if message.get("type") == "ticker":
            return self._parse_ticker(message)
        return None

    @staticmethod
    def _parse_ob_l1(message: dict[str, Any]) -> Quote | None:
        try:
            return Quote(
                symbol=str(message["sy"]),
                bid=Decimal(str(message["bp"])),
                ask=Decimal(str(message["ap"])),
                bid_size=Decimal(str(message.get("bs", "0"))),
                ask_size=Decimal(str(message.get("as", "0"))),
                timestamp_us=int(message.get("ts") or message.get("lts") or 0),
                raw=message,
            )
        except (KeyError, InvalidOperation, TypeError, ValueError):
            LOGGER.debug("skipping malformed ob_l1 message: %s", message)
            return None

    @staticmethod
    def _parse_ticker(message: dict[str, Any]) -> Quote | None:
        rows = message.get("d") or []
        if not rows:
            return None
        row = rows[0]
        quote_values = row.get("q") or []
        if len(quote_values) < 4:
            return None
        try:
            return Quote(
                symbol=str(row.get("s") or message["sy"]),
                bid=Decimal(str(quote_values[2])),
                ask=Decimal(str(quote_values[0])),
                bid_size=Decimal(str(quote_values[3])),
                ask_size=Decimal(str(quote_values[1])),
                timestamp_us=int(message.get("ts") or 0),
                raw=message,
            )
        except (KeyError, InvalidOperation, TypeError, ValueError):
            LOGGER.debug("skipping malformed ticker message: %s", message)
            return None