from abc import ABC, abstractmethod

import pandas as pd

from .models import Signal


class Strategy(ABC):

    name: str = "BaseStrategy"
    min_warmup: int = 60  # 策略可覆盖：声明最少需要多少根 K 线后才开始触发 on_bar

    def init(self, df: pd.DataFrame):
        pass

    @abstractmethod
    def on_bar(self, i: int, row: pd.Series, df: pd.DataFrame,
               has_position: bool) -> Signal:
        raise NotImplementedError

    def get_reason(self) -> str:
        return ""
