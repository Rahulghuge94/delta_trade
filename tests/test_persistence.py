from decimal import Decimal

from delta_paper_trader.broker import PaperBroker
from delta_paper_trader.models import Quote, Side, Signal
from delta_paper_trader.persistence import SQLiteTradeStore


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


def test_store_round_trips_broker_positions_and_fills(tmp_path) -> None:
    store = SQLiteTradeStore(tmp_path / "state.sqlite3")
    broker = PaperBroker(fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    broker.execute_signal(quote("99", "100"), Signal(Side.BUY, Decimal("1"), "entry"))
    broker.mark(quote("104", "105"))

    store.save_broker("strategy-1", broker)
    restored = store.load_broker(
        "strategy-1",
        initial_balance=Decimal("10000"),
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        max_abs_position=Decimal("3"),
    )

    assert restored is not None
    assert restored.cash == broker.cash
    assert restored.position_for("BTCUSD").quantity == Decimal("1")
    assert restored.position_for("BTCUSD").last_mark == Decimal("104.5")
    assert len(restored.fills) == 1
    assert restored.fills[0].reason == "entry"
