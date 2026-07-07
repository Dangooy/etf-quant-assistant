import pandas as pd

from ..strategy import Strategy
from ..models import Signal


class DualMAStrategy(Strategy):

    min_warmup = 20  # 只需 MA20 有效即可，无需等满 60 天

    def __init__(self, fast_period: int = 5, slow_period: int = 20):
        self.fast_ma = f"MA{fast_period}"
        self.slow_ma = f"MA{slow_period}"
        self.name = f"双均线({fast_period}/{slow_period})"
        self._reason = ""

    def on_bar(self, i, row, df, has_position):
        if i < 1:
            return Signal.HOLD
        prev = df.iloc[i - 1]
        fast_now = row.get(self.fast_ma)
        slow_now = row.get(self.slow_ma)
        fast_prev = prev.get(self.fast_ma)
        slow_prev = prev.get(self.slow_ma)

        if pd.notna(fast_now) and pd.notna(slow_now) and pd.notna(fast_prev) and pd.notna(slow_prev):
            if fast_prev <= slow_prev and fast_now > slow_now:
                self._reason = f"{self.fast_ma}上穿{self.slow_ma}金叉"
                return Signal.BUY
            if fast_prev >= slow_prev and fast_now < slow_now:
                self._reason = f"{self.fast_ma}下穿{self.slow_ma}死叉"
                return Signal.SELL
        return Signal.HOLD

    def get_reason(self):
        return self._reason
