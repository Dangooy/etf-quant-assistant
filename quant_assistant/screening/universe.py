"""
股票池管理：维护筛选候选标的列表。
初期用手动维护的 watchlist，后续可接入 akshare 拉取全市场。
"""
from typing import Optional


# 精选A股观察池：行业分散的优质标的，用于替代过度集中的港股仓位
A_SHARE_WATCHLIST = {
    # 信息技术
    "002415": {"name": "海康威视", "sector": "信息技术"},
    "000725": {"name": "京东方A",  "sector": "信息技术"},
    "002230": {"name": "科大讯飞", "sector": "信息技术"},
    # 消费
    "600519": {"name": "贵州茅台", "sector": "消费"},
    "000858": {"name": "五粮液",   "sector": "消费"},
    "002714": {"name": "牧原股份", "sector": "消费"},
    # 医药
    "600276": {"name": "恒瑞医药", "sector": "医药"},
    "300760": {"name": "迈瑞医疗", "sector": "医药"},
    "300015": {"name": "爱尔眼科", "sector": "医药"},
    # 金融（分散组合风险）
    "600036": {"name": "招商银行", "sector": "金融"},
    "601318": {"name": "中国平安", "sector": "金融"},
    # 新能源/制造
    "300750": {"name": "宁德时代", "sector": "新能源"},
    "002594": {"name": "比亚迪",   "sector": "新能源"},
    # 高股息/防御
    "600900": {"name": "长江电力", "sector": "公用事业"},
    "601088": {"name": "中国神华", "sector": "能源"},
}


class StockUniverse:
    """股票池：管理候选标的列表及基本信息"""

    def __init__(self, watchlist: Optional[dict] = None):
        self.stocks = watchlist or A_SHARE_WATCHLIST

    def add(self, code: str, name: str, sector: str):
        self.stocks[code] = {"name": name, "sector": sector}

    def remove(self, code: str):
        self.stocks.pop(code, None)

    def get_codes(self) -> list:
        return list(self.stocks.keys())

    def get_info(self, code: str) -> Optional[dict]:
        return self.stocks.get(code)

    def __len__(self):
        return len(self.stocks)

    def __iter__(self):
        return iter(self.stocks.items())
