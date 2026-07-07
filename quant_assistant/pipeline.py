"""
统一管道编排器：拉行情 → 更新现价 → 计算指标 → 风控检查
策略和风控规则由人定义在 config.py / risk_engine.py 中，此模块只负责执行。
"""
import datetime
from typing import Optional

from .portfolio.holdings import PortfolioManager
from .portfolio.analyzer import PortfolioAnalyzer
from .portfolio.risk_engine import RiskEngine
from .data.fetcher import DataFetcher
from .analysis.indicators import add_all_indicators
from .models import RiskAlert


def run_daily_pipeline(pm: PortfolioManager, days: int = 120):
    """
    执行每日管道，返回 (stock_data, alerts, analyzer).

    管道顺序：
    1. 拉取行情数据（akshare → 缓存优先）
    2. 用最新收盘价更新持仓
    3. 计算技术指标
    4. 运行风控检查
    """
    fetcher = DataFetcher()
    engine = RiskEngine()
    stock_data = {}
    fetch_errors = []

    for pos in pm.positions:
        df = fetcher.fetch_hist(pos.code, pos.market, days=days)
        if df is not None and not df.empty:
            df = add_all_indicators(df)
            stock_data[pos.code] = df
            last_price = float(df.iloc[-1]["收盘"])
            pm.update_price(pos.code, last_price)
        else:
            fetch_errors.append(f"{pos.name}({pos.code})")

    analyzer = PortfolioAnalyzer(pm)
    alerts = engine.run_all_checks(pm)

    return {
        "stock_data": stock_data,
        "alerts": alerts,
        "analyzer": analyzer,
        "fetch_errors": fetch_errors,
        "fetcher": fetcher,
        "engine": engine,
    }
