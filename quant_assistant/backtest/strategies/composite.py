from ..strategy import Strategy
from ..models import Signal


class CompositeStrategy(Strategy):

    def __init__(self, strategies: list, buy_threshold: int = 2,
                 sell_threshold: int = 2):
        self.strategies = strategies
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        names = "+".join(s.name for s in strategies)
        self.name = f"组合({names})"
        self._reason = ""

    def init(self, df):
        for s in self.strategies:
            s.init(df)

    def on_bar(self, i, row, df, has_position):
        buy_votes = 0
        sell_votes = 0
        reasons = []

        for s in self.strategies:
            signal = s.on_bar(i, row, df, has_position)
            if signal == Signal.BUY:
                buy_votes += 1
                reasons.append(f"{s.name}:买")
            elif signal == Signal.SELL:
                sell_votes += 1
                reasons.append(f"{s.name}:卖")

        if buy_votes >= self.buy_threshold:
            self._reason = f"投票买入({buy_votes}票): " + ", ".join(reasons)
            return Signal.BUY
        if sell_votes >= self.sell_threshold:
            self._reason = f"投票卖出({sell_votes}票): " + ", ".join(reasons)
            return Signal.SELL
        return Signal.HOLD

    def get_reason(self):
        return self._reason
