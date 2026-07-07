from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import datetime


class Market(Enum):
    A_SZ = "深圳"
    A_SH = "上海"
    HK = "港股"
    ETF = "ETF"


@dataclass
class StockPosition:
    code: str
    name: str
    market: Market
    shares: int
    cost_price: float
    current_price: float
    sector: str = ""
    last_updated: Optional[datetime.datetime] = None
    # 基本面因子（0 表示未录入）
    pe: float = 0.0
    pb: float = 0.0
    roe: float = 0.0
    market_cap: float = 0.0

    @property
    def fx_rate(self) -> float:
        """折算成人民币的汇率。港股价格是港币，其余市场按 1.0 处理。"""
        from .config import FX_RATES
        if self.market == Market.HK:
            return FX_RATES.get("HKD", 1.0)
        return 1.0

    @property
    def market_value(self) -> float:
        """市值（人民币）"""
        return self.shares * self.current_price * self.fx_rate

    @property
    def cost_value(self) -> float:
        """成本（人民币）"""
        return self.shares * self.cost_price * self.fx_rate

    @property
    def profit_loss_pct(self) -> float:
        if self.cost_price == 0:
            return 0.0
        return (self.current_price - self.cost_price) / self.cost_price

    @property
    def profit_loss_amount(self) -> float:
        return self.market_value - self.cost_value

    @property
    def has_fundamentals(self) -> bool:
        return self.pe > 0 and self.pb > 0


@dataclass
class RiskAlert:
    level: str
    rule_name: str
    message: str
    stock_code: str = ""
    current_value: float = 0.0
    threshold: float = 0.0
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.now)
