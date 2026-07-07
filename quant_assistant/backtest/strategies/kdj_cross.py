import pandas as pd

from ..strategy import Strategy
from ..models import Signal


class KDJCrossStrategy(Strategy):

    def __init__(self, low_zone: float = 30, high_zone: float = 70):
        self.low_zone = low_zone
        self.high_zone = high_zone
        self.name = f"KDJ交叉({low_zone}/{high_zone})"
        self._reason = ""

    def on_bar(self, i, row, df, has_position):
        if i < 1:
            return Signal.HOLD
        prev = df.iloc[i - 1]
        k = row.get("K")
        d = row.get("D")
        k_p = prev.get("K")
        d_p = prev.get("D")

        if pd.notna(k) and pd.notna(d) and pd.notna(k_p) and pd.notna(d_p):
            if k_p <= d_p and k > d and k < self.low_zone:
                self._reason = f"KDJ低位金叉(K={k:.0f})"
                return Signal.BUY
            if k_p >= d_p and k < d and k > self.high_zone:
                self._reason = f"KDJ高位死叉(K={k:.0f})"
                return Signal.SELL
        return Signal.HOLD

    def get_reason(self):
        return self._reason
