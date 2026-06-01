from delta_paper_trader.backtest import run_backtest


def test_run_backtest_returns_summary_and_equity_curve() -> None:
    candles = [
        {"symbol": "BTCUSD", "start": "2026-01-01T00:00:00Z", "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"},
        {"symbol": "BTCUSD", "start": "2026-01-01T00:01:00Z", "open": "100", "high": "102", "low": "100", "close": "101", "volume": "1"},
        {"symbol": "BTCUSD", "start": "2026-01-01T00:02:00Z", "open": "101", "high": "103", "low": "101", "close": "102", "volume": "1"},
        {"symbol": "BTCUSD", "start": "2026-01-01T00:03:00Z", "open": "102", "high": "104", "low": "102", "close": "103", "volume": "1"},
    ]

    result = run_backtest(
        {
            "strategy_type": "breakout",
            "quantity": "1",
            "fee_bps": "0",
            "slippage_bps": "0",
            "params": {"lookback": 2},
            "candles": candles,
        }
    )

    assert result["summary"]["candles"] == 4
    assert len(result["equity_curve"]) == 4
    assert result["summary"]["fills"] == 1
