from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from delta_paper_trader.broker import PaperBroker
from delta_paper_trader.models import Fill, Position, Side


class SQLiteTradeStore:
    def __init__(self, path: str | Path = "delta_paper_trader.sqlite3") -> None:
        self.path = Path(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                create table if not exists strategy_configs (
                    id text primary key,
                    payload text not null,
                    updated_at text not null
                );

                create table if not exists broker_state (
                    strategy_id text primary key,
                    cash text not null,
                    initial_balance text not null,
                    updated_at text not null
                );

                create table if not exists positions (
                    strategy_id text not null,
                    symbol text not null,
                    quantity text not null,
                    avg_entry text not null,
                    realized_pnl text not null,
                    fees_paid text not null,
                    gst_paid text not null,
                    last_mark text not null,
                    highest_price text not null,
                    lowest_price text not null,
                    updated_at text not null,
                    primary key (strategy_id, symbol)
                );

                create table if not exists fills (
                    strategy_id text not null,
                    fill_index integer not null,
                    symbol text not null,
                    side text not null,
                    quantity text not null,
                    price text not null,
                    fee text not null,
                    gst text not null,
                    realized_pnl text not null,
                    timestamp text not null,
                    reason text not null,
                    primary key (strategy_id, fill_index)
                );
                """
            )

    def load_strategy_configs(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("select payload from strategy_configs order by updated_at, id").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def save_strategy_config(self, payload: dict[str, Any]) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                insert into strategy_configs (id, payload, updated_at)
                values (?, ?, ?)
                on conflict(id) do update set payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (payload["id"], json.dumps(payload), now),
            )

    def delete_strategy(self, strategy_id: str) -> None:
        with self._connect() as connection:
            connection.execute("delete from strategy_configs where id = ?", (strategy_id,))
            connection.execute("delete from broker_state where strategy_id = ?", (strategy_id,))
            connection.execute("delete from positions where strategy_id = ?", (strategy_id,))
            connection.execute("delete from fills where strategy_id = ?", (strategy_id,))

    def save_broker(self, strategy_id: str, broker: PaperBroker) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                insert into broker_state (strategy_id, cash, initial_balance, updated_at)
                values (?, ?, ?, ?)
                on conflict(strategy_id) do update set
                    cash=excluded.cash,
                    initial_balance=excluded.initial_balance,
                    updated_at=excluded.updated_at
                """,
                (strategy_id, str(broker.cash), str(broker.initial_balance), now),
            )
            connection.execute("delete from positions where strategy_id = ?", (strategy_id,))
            connection.executemany(
                """
                insert into positions (
                    strategy_id, symbol, quantity, avg_entry, realized_pnl, fees_paid,
                    gst_paid, last_mark, highest_price, lowest_price, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        strategy_id,
                        position.symbol,
                        str(position.quantity),
                        str(position.avg_entry),
                        str(position.realized_pnl),
                        str(position.fees_paid),
                        str(position.gst_paid),
                        str(position.last_mark),
                        str(position.highest_price),
                        str(position.lowest_price),
                        now,
                    )
                    for position in broker.positions.values()
                ],
            )
            connection.execute("delete from fills where strategy_id = ?", (strategy_id,))
            connection.executemany(
                """
                insert into fills (
                    strategy_id, fill_index, symbol, side, quantity, price, fee, gst,
                    realized_pnl, timestamp, reason
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        strategy_id,
                        index,
                        fill.symbol,
                        fill.side.value,
                        str(fill.quantity),
                        str(fill.price),
                        str(fill.fee),
                        str(fill.gst),
                        str(fill.realized_pnl),
                        fill.timestamp.isoformat(),
                        fill.reason,
                    )
                    for index, fill in enumerate(broker.fills)
                ],
            )

    def load_broker(
        self,
        strategy_id: str,
        *,
        initial_balance: Decimal,
        fee_bps: Decimal,
        slippage_bps: Decimal,
        max_abs_position: Decimal,
    ) -> PaperBroker | None:
        with self._connect() as connection:
            state = connection.execute(
                "select cash, initial_balance from broker_state where strategy_id = ?",
                (strategy_id,),
            ).fetchone()
            if state is None:
                return None

            position_rows = connection.execute(
                "select * from positions where strategy_id = ?",
                (strategy_id,),
            ).fetchall()
            fill_rows = connection.execute(
                "select * from fills where strategy_id = ? order by fill_index",
                (strategy_id,),
            ).fetchall()

        broker = PaperBroker(
            initial_balance=Decimal(state["initial_balance"] or str(initial_balance)),
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            max_abs_position=max_abs_position,
        )
        broker.cash = Decimal(state["cash"])
        broker.positions = {
            row["symbol"]: Position(
                symbol=row["symbol"],
                quantity=Decimal(row["quantity"]),
                avg_entry=Decimal(row["avg_entry"]),
                realized_pnl=Decimal(row["realized_pnl"]),
                fees_paid=Decimal(row["fees_paid"]),
                last_mark=Decimal(row["last_mark"]),
                gst_paid=Decimal(row["gst_paid"]),
                highest_price=Decimal(row["highest_price"]),
                lowest_price=Decimal(row["lowest_price"]),
            )
            for row in position_rows
        }
        broker.fills = [
            Fill(
                symbol=row["symbol"],
                side=Side(row["side"]),
                quantity=Decimal(row["quantity"]),
                price=Decimal(row["price"]),
                fee=Decimal(row["fee"]),
                gst=Decimal(row["gst"]),
                realized_pnl=Decimal(row["realized_pnl"]),
                timestamp=datetime.fromisoformat(row["timestamp"]),
                reason=row["reason"],
            )
            for row in fill_rows
        ]
        return broker


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
