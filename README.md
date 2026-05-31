# Delta Exchange Paper Momentum Trader

Python paper-trading engine for day-trading momentum strategies on Delta Exchange public market data. It does not place live orders. It builds shared `1m` candles from the live top-of-book quote stream, simulates market fills on the next live quote after a candle signal, and tracks per-strategy capital, positions, realized PnL, unrealized PnL, and fees.

## Momentum Strategies Included

- Fast/slow moving average cross: follows short-term `1m` candle trend flips.
- Rolling breakout momentum: buys closes above recent candle highs and sells closes below recent candle lows.
- EMA impulse: trades when fast and slow candle EMAs separate by a minimum spread.
- RSI momentum: follows strong `1m` candle RSI readings above or below configurable bands.
- Rolling VWAP momentum: uses candle volume proxy and trades reclaim/rejection around rolling VWAP.

These are starting points for paper testing. Lower-timeframe day trading is very fee and slippage sensitive, so keep quantity and max-position small until the live paper results are stable.

## Fee Model

The app defaults to futures taker fees because paper fills are simulated as market orders:

- Futures taker: `0.05%` or `5 bps`
- Futures maker: `0.02%` or `2 bps`

Source checked on May 31, 2026: Delta Exchange fee page. The simulator excludes funding, settlement fees, taxes/GST, liquidation costs, and any account-specific VIP discounts.

## Setup

```powershell
cd "C:\Users\Rahul Ghuge\delta_trade"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run The Web UI

```powershell
uvicorn delta_paper_trader.app:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

From the UI you can add, enable, disable, delete, start, and stop strategy configurations. Each strategy gets its own paper broker and capital bucket, so profit and fees are shown separately.

## Run The CLI

```powershell
python -m delta_paper_trader.main --symbols BTCUSD --qty 1 --max-position 3
```

Quick smoke test:

```powershell
python -m delta_paper_trader.main --symbols BTCUSD --fast 2 --slow 3 --max-quotes 10
```

Use multiple symbols like this:

```powershell
python -m delta_paper_trader.main --symbols BTCUSD ETHUSD --qty 1
```

## Safety Note

This project is paper-trading only. If you later add real orders, put live trading behind a separate explicit mode, API-key environment variables, strict max-loss limits, and a kill switch.
