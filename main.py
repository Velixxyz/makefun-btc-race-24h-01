"""Hourglass: a one-hour Donchian breakout bot for the cbBTC 24h race.

The idea, in plain words: Bitcoin spends most of a day drifting or falling,
and the money sits in a few sharp legs up. This bot stays in cash almost all
of the time and only buys when the price breaks out of its last hour's range
by a hair, then rides the move with a trailing stop that gives back half a
percent from the best close seen since entry. It never shorts, never uses
leverage, never trades more than once per minute, and it waits two hours
before its first trade so the one-hour window it reads is properly formed
instead of a fragment of the day's open. After a stop-out it sits out for
30 bars: the breakout failed, so paying another ~40 bps to re-enter the
same failed move is the classic whipsaw tax, and the bot refuses to pay it.

Five numbers, all round: a 60-bar (one-hour) breakout window, a 5-basis-point
buffer above the old high so a mere touch does not trigger it, a 0.50%
trailing stop, a 120-bar minimum history, and a 30-bar re-entry cooldown
after a stop-out. On the dev window that earned +18.66 USDC on 1,000 USDC
with three round trips, a worst drawdown of 1.38%, and two small losing
trades against one +3% rally trade. That is the honest shape of it: trend
following lives or dies on whether the race window has a leg like that,
and no parameter here pretends otherwise.

Everything is integer arithmetic on the prices the harness sends, no clock,
no network, no file reads, no randomness: the same bars always produce the
same orders.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
LOOKBACK = 60            # bars in the breakout window (one hour of 1m bars)
MIN_HISTORY = 120       # bars before the first trade (two hours of history)
BUFFER_BPS = 5           # breakout must clear the old high by this much
TRAIL_BPS = 50           # trailing stop: 0.50% below the peak close since entry
COOLDOWN_BARS = 30       # bars to sit out after a stop-out before a new entry
MAX_SLIPPAGE_BPS = 100   # 1%: far above the ~15 bps a full-size fill moves


class Hourglass:
    def __init__(self):
        self.closes = []   # every close seen, in order
        self.highs = []    # every bar high seen, in order
        self.peak = 0      # best close since the current entry (0 when flat)
        self.cooldown_until = 0  # bar count until which new entries are blocked

    def on_batch(self, state, batch):
        bar = None
        for b in batch.get("bars", []):
            if b["symbol"] == SYMBOL:
                bar = b
                break
        if bar is None:
            return []
        close = int(bar["c"])
        high = int(bar["h"])
        self.closes.append(close)
        self.highs.append(high)

        if state.warming_up:
            return []

        held = state.positions.get(SYMBOL)
        qty = held.qty if held is not None else 0

        if qty > 0:
            # Holding: trail the stop under the best close since entry.
            if close > self.peak:
                self.peak = close
            if close * 10000 <= self.peak * (10000 - TRAIL_BPS):
                self.peak = 0
                # The breakout failed: sit out a while instead of paying
                # another ~40 bps to re-enter the same failed move.
                self.cooldown_until = len(self.closes) + COOLDOWN_BARS
                return [{
                    "side": "sell",
                    "symbol": SYMBOL,
                    "qty": qty,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }]
            return []

        # Flat: reset the peak and look for a breakout of the last hour's high.
        self.peak = 0
        if len(self.closes) <= MIN_HISTORY:
            return []
        if len(self.closes) <= self.cooldown_until:
            return []
        window = self.highs[-LOOKBACK - 1:-1]  # previous 60 bars, not this one
        if len(window) < LOOKBACK:
            return []
        breakout = max(window)
        if close * 10000 >= breakout * (10000 + BUFFER_BPS):
            self.peak = close
            return [{
                "side": "buy",
                "symbol": SYMBOL,
                "notional_quote_units": state.cash,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }]
        return []


makefun_bars.run(Hourglass().on_batch)
