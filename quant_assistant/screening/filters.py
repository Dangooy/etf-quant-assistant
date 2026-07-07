"""
多因子筛选条件：每个 Filter 是一个可调用对象，返回 True/False。
过滤器可自由组合（默认 AND 逻辑）。
"""
from typing import Optional

import pandas as pd


class Filter:
    """筛选条件基类"""
    name: str = ""

    def check(self, code: str, info: dict, df: Optional[pd.DataFrame],
              fundamentals: Optional[dict]) -> bool:
        raise NotImplementedError


class PEMaxFilter(Filter):
    """PE 不超过上限"""
    def __init__(self, max_pe: float):
        self.name = f"PE<={max_pe}"
        self.max_pe = max_pe

    def check(self, code, info, df, fundamentals):
        if not fundamentals or not fundamentals.get("pe"):
            return True  # 无数据不过滤
        return fundamentals["pe"] <= self.max_pe


class PEMinFilter(Filter):
    """PE 不低于下限（排除负PE）"""
    def __init__(self, min_pe: float = 0):
        self.name = f"PE>={min_pe}"
        self.min_pe = min_pe

    def check(self, code, info, df, fundamentals):
        if not fundamentals or not fundamentals.get("pe"):
            return True
        return fundamentals["pe"] >= self.min_pe


class PBMaxFilter(Filter):
    """PB 不超过上限"""
    def __init__(self, max_pb: float):
        self.name = f"PB<={max_pb}"
        self.max_pb = max_pb

    def check(self, code, info, df, fundamentals):
        if not fundamentals or not fundamentals.get("pb"):
            return True
        return fundamentals["pb"] <= self.max_pb


class ROEMinFilter(Filter):
    """ROE 不低于下限"""
    def __init__(self, min_roe: float):
        self.name = f"ROE>={min_roe}%"
        self.min_roe = min_roe

    def check(self, code, info, df, fundamentals):
        if not fundamentals or not fundamentals.get("roe"):
            return True
        return fundamentals["roe"] >= self.min_roe


class SectorFilter(Filter):
    """行业过滤"""
    def __init__(self, allowed_sectors: list):
        self.name = f"行业∈{allowed_sectors}"
        self.allowed = set(allowed_sectors)

    def check(self, code, info, df, fundamentals):
        return info.get("sector", "") in self.allowed


class MATrendFilter(Filter):
    """均线多头排列：MA5 > MA20"""
    name = "MA5>MA20"

    def check(self, code, info, df, fundamentals):
        if df is None or df.empty or "MA5" not in df.columns or "MA20" not in df.columns:
            return True
        last = df.iloc[-1]
        return bool(last["MA5"] > last["MA20"])


class AboveMA20Filter(Filter):
    """股价在 MA20 上方"""
    name = "收盘>MA20"

    def check(self, code, info, df, fundamentals):
        if df is None or df.empty or "MA20" not in df.columns:
            return True
        last = df.iloc[-1]
        return bool(last["收盘"] > last["MA20"])


class VolumeActiveFilter(Filter):
    """量比 > 0.5，排除无量僵尸股"""
    name = "量比>0.5"

    def check(self, code, info, df, fundamentals):
        if df is None or df.empty or "量比" not in df.columns:
            return True
        last = df.iloc[-1]
        return float(last.get("量比", 1.0)) > 0.5
