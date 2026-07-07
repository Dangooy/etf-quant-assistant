from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import datetime


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Trade:
    date: datetime.date
    direction: str
    price: float
    shares: int
    amount: float
    commission: float
    stamp_tax: float
    total_cost: float
    reason: str = ""

    @property
    def net_amount(self) -> float:
        if self.direction == "BUY":
            return -(self.amount + self.total_cost)
        return self.amount - self.total_cost


@dataclass
class HoldingPosition:
    shares: int = 0
    avg_cost: float = 0.0

    @property
    def is_empty(self) -> bool:
        return self.shares <= 0


@dataclass
class DailySnapshot:
    date: datetime.date
    cash: float
    position_value: float
    total_equity: float
    shares: int
    close_price: float


@dataclass
class BacktestConfig:
    initial_capital: float = 100_000.0
    commission_rate: float = 0.00025
    min_commission: float = 5.0
    stamp_tax_rate: float = 0.0005      # A股卖出印花税，2023-08-28 起减半为千0.5；ETF 免征
    hk_stamp_tax_rate: float = 0.001    # 港股印花税，买卖双向千1
    transfer_fee_rate: float = 0.00001  # 过户费万0.1，仅沪市A股，双向
    slippage_pct: float = 0.001
    position_pct: float = 0.95
    lot_size: int = 100


@dataclass
class BacktestResult:
    code: str
    name: str
    strategy_name: str
    config: BacktestConfig
    start_date: Optional[datetime.date]
    end_date: Optional[datetime.date]
    trades: list = field(default_factory=list)
    daily_snapshots: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    signals_log: list = field(default_factory=list)
