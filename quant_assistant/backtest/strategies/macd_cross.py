import pandas as pd

from ..strategy import Strategy
from ..models import Signal


class MACDCrossStrategy(Strategy):

    name = "MACD金叉死叉"

    def __init__(self):
        self._reason = ""

    def on_bar(self, i, row, df, has_position):
        if i < 1:
            return Signal.HOLD
        prev = df.iloc[i - 1]
        dif = row.get("DIF")
        dea = row.get("DEA")
        dif_p = prev.get("DIF")
        dea_p = prev.get("DEA")

        if pd.notna(dif) and pd.notna(dea) and pd.notna(dif_p) and pd.notna(dea_p):
            if dif_p <= dea_p and dif > dea:
                self._reason = "MACD金叉"
                return Signal.BUY
            if dif_p >= dea_p and dif < dea:
                self._reason = "MACD死叉"
                return Signal.SELL
        return Signal.HOLD

    def get_reason(self):
        return self._reason
