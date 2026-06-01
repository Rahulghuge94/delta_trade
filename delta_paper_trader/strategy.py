from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from delta_paper_trader.broker import PaperBroker
from delta_paper_trader.models import Candle, Side, Signal, Position


@dataclass
class Strategy:
    code = "base"
    display_name = "Base strategy"
    description = "Base strategy interface."
    trade_quantity: Decimal = Decimal("1")
    sl_pct: Decimal = Decimal("0")
    target_pct: Decimal = Decimal("0")
    trailing_sl_pct: Decimal = Decimal("0")

    def on_candle(self, candle: Candle, broker: PaperBroker) -> Signal:
        position = broker.position_for(candle.symbol)
        if position.quantity != 0:
            if position.quantity > 0:
                position.highest_price = max(position.highest_price or position.avg_entry, candle.high)
            elif position.quantity < 0:
                position.lowest_price = min(position.lowest_price or position.avg_entry, candle.low)

            exit_signal = self.check_sl_target(candle, position)
            if exit_signal:
                return exit_signal

        return self.generate_signal(candle, broker)

    def check_sl_target(self, candle: Candle, position: Position) -> Signal | None:
        qty = abs(position.quantity)
        side = position.side

        if side == "long":
            if self.sl_pct > 0:
                sl_level = position.avg_entry * (Decimal("1") - self.sl_pct / Decimal("100"))
                if candle.low <= sl_level:
                    return Signal(Side.SELL, qty, f"Stop Loss triggered at {sl_level} (candle low: {candle.low})")

            if self.trailing_sl_pct > 0 and position.highest_price > 0:
                trail_level = position.highest_price * (Decimal("1") - self.trailing_sl_pct / Decimal("100"))
                if candle.low <= trail_level:
                    return Signal(Side.SELL, qty, f"Trailing Stop Loss triggered at {trail_level} (highest: {position.highest_price})")

            if self.target_pct > 0:
                target_level = position.avg_entry * (Decimal("1") + self.target_pct / Decimal("100"))
                if candle.high >= target_level:
                    return Signal(Side.SELL, qty, f"Target Take Profit triggered at {target_level} (candle high: {candle.high})")

        elif side == "short":
            if self.sl_pct > 0:
                sl_level = position.avg_entry * (Decimal("1") + self.sl_pct / Decimal("100"))
                if candle.high >= sl_level:
                    return Signal(Side.BUY, qty, f"Stop Loss triggered at {sl_level} (candle high: {candle.high})")

            if self.trailing_sl_pct > 0 and position.lowest_price > 0:
                trail_level = position.lowest_price * (Decimal("1") + self.trailing_sl_pct / Decimal("100"))
                if candle.high >= trail_level:
                    return Signal(Side.BUY, qty, f"Trailing Stop Loss triggered at {trail_level} (lowest: {position.lowest_price})")

            if self.target_pct > 0:
                target_level = position.avg_entry * (Decimal("1") - self.target_pct / Decimal("100"))
                if candle.low <= target_level:
                    return Signal(Side.BUY, qty, f"Target Take Profit triggered at {target_level} (candle low: {candle.low})")

        return None

    def generate_signal(self, candle: Candle, broker: PaperBroker) -> Signal:
        raise NotImplementedError


def _flip_signal(broker: PaperBroker, candle: Candle, side: Side, quantity: Decimal, reason: str) -> Signal:
    current_qty = broker.position_for(candle.symbol).quantity
    if side is Side.BUY and current_qty <= 0:
        return Signal(Side.BUY, quantity + abs(current_qty), reason)
    if side is Side.SELL and current_qty >= 0:
        return Signal(Side.SELL, quantity + abs(current_qty), reason)
    return Signal.hold("already_positioned")


@dataclass
class MovingAverageCrossStrategy(Strategy):
    code = "ma_cross"
    display_name = "Fast/slow moving average cross"
    description = "Trades 1-minute candle closes when short momentum crosses above or below a slower rolling average."

    trade_quantity: Decimal = Decimal("1")
    fast_window: int = 2
    slow_window: int = 5
    prices: dict[str, deque[Decimal]] = field(default_factory=lambda: defaultdict(deque))
    last_bias: dict[str, str] = field(default_factory=dict)

    def generate_signal(self, candle: Candle, broker: PaperBroker) -> Signal:
        history = self.prices[candle.symbol]
        history.append(candle.close)
        while len(history) > self.slow_window:
            history.popleft()

        if len(history) < self.slow_window:
            return Signal.hold("warming_up")

        values = list(history)
        fast = sum(values[-self.fast_window :]) / Decimal(self.fast_window)
        slow = sum(values) / Decimal(self.slow_window)
        bias = "long" if fast > slow else "short" if fast < slow else "flat"

        if bias == self.last_bias.get(candle.symbol):
            return Signal.hold("bias_unchanged")

        self.last_bias[candle.symbol] = bias
        if bias == "long":
            return _flip_signal(broker, candle, Side.BUY, self.trade_quantity, f"fast_ma {fast} crossed above slow_ma {slow}")
        if bias == "short":
            return _flip_signal(broker, candle, Side.SELL, self.trade_quantity, f"fast_ma {fast} crossed below slow_ma {slow}")
        return Signal.hold("flat_bias")


@dataclass
class BreakoutMomentumStrategy(Strategy):
    code = "breakout"
    display_name = "1m candle breakout momentum"
    description = "Buys closes above the rolling candle high and sells closes below the rolling candle low."

    trade_quantity: Decimal = Decimal("1")
    lookback: int = 30
    prices: dict[str, deque[Decimal]] = field(default_factory=lambda: defaultdict(deque))
    last_bias: dict[str, str] = field(default_factory=dict)

    def generate_signal(self, candle: Candle, broker: PaperBroker) -> Signal:
        history = self.prices[candle.symbol]
        if len(history) < self.lookback:
            history.append(candle.close)
            return Signal.hold("warming_up")

        high = max(history)
        low = min(history)
        history.append(candle.close)
        while len(history) > self.lookback:
            history.popleft()

        bias = "long" if candle.close > high else "short" if candle.close < low else "flat"
        if bias == "flat" or bias == self.last_bias.get(candle.symbol):
            return Signal.hold("no_breakout")

        self.last_bias[candle.symbol] = bias
        if bias == "long":
            return _flip_signal(broker, candle, Side.BUY, self.trade_quantity, f"breakout above {high}")
        return _flip_signal(broker, candle, Side.SELL, self.trade_quantity, f"breakdown below {low}")


@dataclass
class EmaImpulseStrategy(Strategy):
    code = "ema_impulse"
    display_name = "EMA impulse"
    description = "Follows 1-minute candle EMA impulse when fast EMA separates from slow EMA."

    trade_quantity: Decimal = Decimal("1")
    fast_span: int = 8
    slow_span: int = 21
    min_spread_bps: Decimal = Decimal("2")
    ema_fast: dict[str, Decimal] = field(default_factory=dict)
    ema_slow: dict[str, Decimal] = field(default_factory=dict)
    last_bias: dict[str, str] = field(default_factory=dict)

    def generate_signal(self, candle: Candle, broker: PaperBroker) -> Signal:
        fast = self._ema(self.ema_fast.get(candle.symbol), candle.close, self.fast_span)
        slow = self._ema(self.ema_slow.get(candle.symbol), candle.close, self.slow_span)
        self.ema_fast[candle.symbol] = fast
        self.ema_slow[candle.symbol] = slow

        spread_bps = ((fast - slow) / candle.close) * Decimal("10000")
        bias = "long" if spread_bps > self.min_spread_bps else "short" if spread_bps < -self.min_spread_bps else "flat"
        if bias == "flat" or bias == self.last_bias.get(candle.symbol):
            return Signal.hold("impulse_not_confirmed")

        self.last_bias[candle.symbol] = bias
        if bias == "long":
            return _flip_signal(broker, candle, Side.BUY, self.trade_quantity, f"ema impulse spread_bps={spread_bps}")
        return _flip_signal(broker, candle, Side.SELL, self.trade_quantity, f"ema impulse spread_bps={spread_bps}")

    @staticmethod
    def _ema(previous: Decimal | None, price: Decimal, span: int) -> Decimal:
        if previous is None:
            return price
        alpha = Decimal("2") / Decimal(span + 1)
        return (price * alpha) + (previous * (Decimal("1") - alpha))


@dataclass
class RsiMomentumStrategy(Strategy):
    code = "rsi_momentum"
    display_name = "RSI momentum"
    description = "Goes with strong 1-minute candle RSI readings and flips when momentum breaks the lower band."

    trade_quantity: Decimal = Decimal("1")
    period: int = 14
    long_threshold: Decimal = Decimal("60")
    short_threshold: Decimal = Decimal("40")
    prices: dict[str, deque[Decimal]] = field(default_factory=lambda: defaultdict(deque))
    last_bias: dict[str, str] = field(default_factory=dict)

    def generate_signal(self, candle: Candle, broker: PaperBroker) -> Signal:
        history = self.prices[candle.symbol]
        history.append(candle.close)
        while len(history) > self.period + 1:
            history.popleft()
        if len(history) < self.period + 1:
            return Signal.hold("warming_up")

        values = list(history)
        gains = []
        losses = []
        for previous, current in zip(values, values[1:]):
            change = current - previous
            gains.append(max(change, Decimal("0")))
            losses.append(abs(min(change, Decimal("0"))))

        avg_gain = sum(gains) / Decimal(self.period)
        avg_loss = sum(losses) / Decimal(self.period)
        rsi = Decimal("100") if avg_loss == 0 else Decimal("100") - (Decimal("100") / (Decimal("1") + (avg_gain / avg_loss)))
        bias = "long" if rsi >= self.long_threshold else "short" if rsi <= self.short_threshold else "flat"
        if bias == "flat" or bias == self.last_bias.get(candle.symbol):
            return Signal.hold("rsi_neutral")

        self.last_bias[candle.symbol] = bias
        if bias == "long":
            return _flip_signal(broker, candle, Side.BUY, self.trade_quantity, f"rsi momentum {rsi}")
        return _flip_signal(broker, candle, Side.SELL, self.trade_quantity, f"rsi weakness {rsi}")


@dataclass
class VwapMomentumStrategy(Strategy):
    code = "vwap_momentum"
    display_name = "1m rolling VWAP momentum"
    description = "Uses 1-minute candle volume proxy and trades VWAP reclaim/rejection."

    trade_quantity: Decimal = Decimal("1")
    window: int = 50
    min_distance_bps: Decimal = Decimal("3")
    samples: dict[str, deque[tuple[Decimal, Decimal]]] = field(default_factory=lambda: defaultdict(deque))
    last_bias: dict[str, str] = field(default_factory=dict)

    def generate_signal(self, candle: Candle, broker: PaperBroker) -> Signal:
        size_proxy = max(candle.volume, Decimal("1"))
        samples = self.samples[candle.symbol]
        samples.append((candle.typical_price, size_proxy))
        while len(samples) > self.window:
            samples.popleft()
        if len(samples) < self.window:
            return Signal.hold("warming_up")

        total_size = sum(size for _, size in samples)
        vwap = sum(price * size for price, size in samples) / total_size
        distance_bps = ((candle.close - vwap) / candle.close) * Decimal("10000")
        bias = "long" if distance_bps > self.min_distance_bps else "short" if distance_bps < -self.min_distance_bps else "flat"
        if bias == "flat" or bias == self.last_bias.get(candle.symbol):
            return Signal.hold("near_vwap")

        self.last_bias[candle.symbol] = bias
        if bias == "long":
            return _flip_signal(broker, candle, Side.BUY, self.trade_quantity, f"price above rolling_vwap {vwap}")
        return _flip_signal(broker, candle, Side.SELL, self.trade_quantity, f"price below rolling_vwap {vwap}")


@dataclass
class Ema9_100PullbackStrategy(Strategy):
    """1-minute EMA 9 / EMA 100 pullback strategy.

    Trend filter:
    - Long  bias: EMA 9 > EMA 100
    - Short bias: EMA 9 < EMA 100

    Entry (short example):
    1. EMA 9 is below EMA 100 (trend confirmed bearish).
    2. Price pulls back up into the EMA 9 ± pullback_band_bps zone.
    3. The current candle closes *below* EMA 9 (bearish rejection confirmed).
    4. EMA 9 spread vs EMA 100 exceeds min_trend_bps (trend has meaningful separation,
       not a flat/choppy cross).

    The same logic applies symmetrically for longs.

    Exits are handled by the base-class sl_pct / target_pct / trailing_sl_pct
    mechanism so the strategy integrates seamlessly with the existing risk
    management layer.  Recommended defaults when calling build_strategy:
        sl_pct=0.37          (~$270 buffer above EMA 100 on a $73k BTC price)
        target_pct=0.55      (TP1 ~1× risk; ride remainder with trailing_sl_pct)
        trailing_sl_pct=0.18 (trails the best price once TP1 zone is cleared)
    """

    code = "ema9_100_pullback"
    display_name = "EMA 9/100 pullback"
    description = (
        "Waits for a pullback to EMA 9 in the direction confirmed by EMA 100, "
        "then enters on a rejection close. Trend, band, and spread filters raise win rate."
    )

    trade_quantity: Decimal = Decimal("1")
    # ── EMA spans ────────────────────────────────────────────────────────────
    fast_span: int = 9
    slow_span: int = 100
    # ── Entry filters ────────────────────────────────────────────────────────
    # How close price must be to EMA 9 to qualify as a "pullback" (basis points
    # of the current close price).  80 bps ≈ $58 on a $72 700 BTC price.
    pullback_band_bps: Decimal = Decimal("80")
    # Minimum separation between EMA 9 and EMA 100 expressed in bps of close.
    # Avoids entering during flat/sideways markets where both EMAs are tangled.
    min_trend_bps: Decimal = Decimal("10")
    # ── Internal state ───────────────────────────────────────────────────────
    ema_fast: dict[str, Decimal] = field(default_factory=dict)
    ema_slow: dict[str, Decimal] = field(default_factory=dict)
    # Previous candle close — used for the "consecutive red/green" rejection check.
    prev_close: dict[str, Decimal] = field(default_factory=dict)
    last_bias: dict[str, str] = field(default_factory=dict)

    # ── EMA helper ───────────────────────────────────────────────────────────
    @staticmethod
    def _ema(previous: Decimal | None, price: Decimal, span: int) -> Decimal:
        if previous is None:
            return price
        alpha = Decimal("2") / Decimal(span + 1)
        return (price * alpha) + (previous * (Decimal("1") - alpha))

    # ── Core signal logic ────────────────────────────────────────────────────
    def generate_signal(self, candle: Candle, broker: PaperBroker) -> Signal:
        sym = candle.symbol

        # ── 1. Update EMAs ───────────────────────────────────────────────────
        ema9 = self._ema(self.ema_fast.get(sym), candle.close, self.fast_span)
        ema100 = self._ema(self.ema_slow.get(sym), candle.close, self.slow_span)
        self.ema_fast[sym] = ema9
        self.ema_slow[sym] = ema100

        prev = self.prev_close.get(sym)
        self.prev_close[sym] = candle.close

        # Need at least one prior close to confirm rejection direction.
        if prev is None:
            return Signal.hold("warming_up")

        # ── 2. Trend filter — EMA 9 vs EMA 100 ──────────────────────────────
        spread_bps = ((ema9 - ema100) / candle.close) * Decimal("10000")
        trend_bps_abs = abs(spread_bps)
        if trend_bps_abs < self.min_trend_bps:
            return Signal.hold("trend_not_established")

        trend_bias = "long" if spread_bps > 0 else "short"

        # ── 3. Pullback filter — price within band of EMA 9 ─────────────────
        distance_bps = abs((candle.close - ema9) / candle.close) * Decimal("10000")
        if distance_bps > self.pullback_band_bps:
            return Signal.hold("price_not_at_ema9")

        # ── 4. Rejection candle filter ───────────────────────────────────────
        # Short setup: candle must close below EMA 9 (bearish rejection).
        # Long  setup: candle must close above EMA 9 (bullish reclaim).
        if trend_bias == "short" and candle.close >= ema9:
            return Signal.hold("no_bearish_rejection")
        if trend_bias == "long" and candle.close <= ema9:
            return Signal.hold("no_bullish_reclaim")

        # ── 5. Deduplicate — only act on bias changes ────────────────────────
        if trend_bias == self.last_bias.get(sym):
            return Signal.hold("bias_unchanged")
        self.last_bias[sym] = trend_bias

        # ── 6. Emit signal ───────────────────────────────────────────────────
        reason = (
            f"ema9={ema9:.2f} ema100={ema100:.2f} "
            f"spread_bps={spread_bps:.1f} dist_bps={distance_bps:.1f}"
        )
        if trend_bias == "short":
            return _flip_signal(
                broker, candle, Side.SELL, self.trade_quantity,
                f"pullback_rejection_short {reason}",
            )
        return _flip_signal(
            broker, candle, Side.BUY, self.trade_quantity,
            f"pullback_reclaim_long {reason}",
        )

STRATEGY_TYPES: dict[str, type[Strategy]] = {
    MovingAverageCrossStrategy.code: MovingAverageCrossStrategy,
    BreakoutMomentumStrategy.code: BreakoutMomentumStrategy,
    EmaImpulseStrategy.code: EmaImpulseStrategy,
    RsiMomentumStrategy.code: RsiMomentumStrategy,
    VwapMomentumStrategy.code: VwapMomentumStrategy,
    Ema9_100PullbackStrategy.code: Ema9_100PullbackStrategy,
}


def strategy_catalog() -> list[dict[str, Any]]:
    return [
        {
            "code": strategy_type.code,
            "name": strategy_type.display_name,
            "description": strategy_type.description,
        }
        for strategy_type in STRATEGY_TYPES.values()
    ]


def build_strategy(
    strategy_type: str,
    quantity: Decimal,
    sl_pct: Decimal | dict[str, Any] | None = None,
    target_pct: Decimal = Decimal("0"),
    trailing_sl_pct: Decimal = Decimal("0"),
    params: dict[str, Any] | None = None
) -> Strategy:
    if isinstance(sl_pct, dict):
        params = sl_pct
        sl_pct = Decimal("0")

    sl_pct = Decimal(str(sl_pct or "0"))
    target_pct = Decimal(str(target_pct or "0"))
    trailing_sl_pct = Decimal(str(trailing_sl_pct or "0"))

    params = dict(params or {})
    params["trade_quantity"] = quantity
    params["sl_pct"] = sl_pct
    params["target_pct"] = target_pct
    params["trailing_sl_pct"] = trailing_sl_pct
    try:
        strategy_cls = STRATEGY_TYPES[strategy_type]
    except KeyError as exc:
        raise ValueError(f"Unknown strategy type: {strategy_type}") from exc
    return strategy_cls(**params)