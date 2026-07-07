import pandas as pd

from ..strategy import Strategy
from ..models import Signal


class RSIReversalStrategy(Strategy):

    def __init__(self, oversold: float = 30, overbought: float = 70):
        self.oversold = oversold
        self.overbought = overbought
        self.name = f"RSI反转({oversold}/{overbought})"
        self._reason = ""

    def on_bar(self, i, row, df, has_position):
        if i < 1:
            return Signal.HOLD
        prev = df.iloc[i - 1]
        rsi_now = row.get("RSI14")
        rsi_prev = prev.get("RSI14")

        if pd.notna(rsi_now) and pd.notna(rsi_prev):
            if rsi_prev < self.oversold and rsi_now >= self.oversold:
                self._reason = f"RSI从{rsi_prev:.0f}回升至{rsi_now:.0f}，超卖反弹"
                return Signal.BUY
            if rsi_prev > self.overbought and rsi_now <= self.overbought:
                self._reason = f"RSI从{rsi_prev:.0f}跌至{rsi_now:.0f}，超买回落"
                return Signal.SELL
        return Signal.HOLD

    def get_reason(self):
        return self._reason
