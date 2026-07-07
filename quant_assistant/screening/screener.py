"""
选股筛选引擎：加载股票池 → 获取数据 → 应用过滤器 → 评分排名 → 输出结果。
"""
from typing import Optional

from tabulate import tabulate

from ..data.fetcher import DataFetcher
from ..analysis.indicators import add_all_indicators
from ..models import Market
from .universe import StockUniverse
from .scorer import score_stock


class StockScreener:
    """多因子选股筛选器"""

    def __init__(self, universe: Optional[StockUniverse] = None,
                 fetcher: Optional[DataFetcher] = None):
        self.universe = universe or StockUniverse()
        self.fetcher = fetcher or DataFetcher()
        self.filters = []

    def add_filter(self, f):
        self.filters.append(f)

    def clear_filters(self):
        self.filters.clear()

    def run(self, top_n: int = 10) -> dict:
        """
        执行筛选流程：
        1. 遍历候选池，拉取行情数据
        2. 依次应用过滤器
        3. 通过筛选的标的进入评分
        4. 按总分降序排列
        """
        results = []
        total = len(self.universe)
        passed = 0

        for code, info in self.universe:
            fundamentals = self._fetch_fundamentals(code)
            df = self.fetcher.fetch_hist(code, Market.A_SZ, days=120)
            # 必须先补算指标，否则 MA/量比类过滤器因缺列而全部放行
            if df is not None and not df.empty:
                df = add_all_indicators(df)

            # 过滤
            skip = False
            for f in self.filters:
                if not f.check(code, info, df, fundamentals):
                    skip = True
                    break
            if skip:
                continue
            passed += 1

            # 评分
            scores = score_stock(code, info, df, fundamentals)
            results.append(scores)

        # 排名
        results.sort(key=lambda r: r["composite"], reverse=True)

        return {
            "total_in_universe": total,
            "passed_filters": passed,
            "results": results[:top_n],
        }

    def _fetch_fundamentals(self, code: str) -> Optional[dict]:
        """从持仓管理器或配置中获取基本面数据"""
        # 先用硬编码补充一些基本面数据（系统已有 PE/PB）
        known = _KNOWN_FUNDAMENTALS.get(code)
        if known:
            return known
        return None


# 观察池已知的基本面数据（手工维护快照，后续可扩展 akshare 批量拉取）
# 更新数据后同步修改 _FUNDAMENTALS_AS_OF，报告中会打印数据截止日提醒
_FUNDAMENTALS_AS_OF = "2025-05"
_KNOWN_FUNDAMENTALS = {
    # 信息技术
    "002415": {"pe": 22.5, "pb": 4.3, "roe": 19.5},
    "000725": {"pe": 18.3, "pb": 1.1, "roe": 6.2},
    "002230": {"pe": 85.0, "pb": 6.8, "roe": 8.5},
    # 消费
    "600519": {"pe": 24.8, "pb": 9.2, "roe": 34.0},
    "000858": {"pe": 18.5, "pb": 4.8, "roe": 22.0},
    "002714": {"pe": 15.2, "pb": 3.1, "roe": 21.5},
    # 医药
    "600276": {"pe": 52.0, "pb": 6.5, "roe": 13.0},
    "300760": {"pe": 28.5, "pb": 8.2, "roe": 30.0},
    "300015": {"pe": 45.0, "pb": 7.5, "roe": 18.0},
    # 金融
    "600036": {"pe": 6.8, "pb": 0.9, "roe": 12.5},
    "601318": {"pe": 9.5, "pb": 1.1, "roe": 13.0},
    # 新能源
    "300750": {"pe": 22.0, "pb": 5.5, "roe": 25.0},
    "002594": {"pe": 28.0, "pb": 5.8, "roe": 22.0},
    # 防御
    "600900": {"pe": 22.0, "pb": 3.2, "roe": 14.0},
    "601088": {"pe": 10.5, "pb": 1.3, "roe": 12.0},
}


def print_screening_report(result: dict):
    """打印筛选报告"""
    print("\n" + "=" * 80)
    print("  多因子选股筛选报告")
    print("=" * 80)
    print(f"  候选池: {result['total_in_universe']} 只")
    print(f"  通过筛选: {result['passed_filters']} 只")
    print(f"  基本面数据截止: {_FUNDAMENTALS_AS_OF}（手工快照，注意时效）")
    print(f"  展示: Top {len(result['results'])}")

    if not result["results"]:
        print("\n  无标的通过当前筛选条件，建议放宽条件")
        return

    table_data = []
    for r in result["results"]:
        table_data.append([
            r["code"], r["name"], r["sector"],
            f"{r['value_score']:.0f}" if r.get("fundamentals_available") else "-",
            f"{r['quality_score']:.0f}" if r.get("fundamentals_available") else "-",
            f"{r['momentum_score']:.0f}" if r.get("technicals_available") else "-",
            f"{r['composite']:.0f}",
        ])

    headers = ["代码", "名称", "行业", "估值分", "质量分", "动量分", "总分"]
    print()
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    print("\n  评分说明：估值分(PE/PB相对行业)、质量分(ROE)、动量分(趋势强度)")
    print("  总分 = 估值×40% + 质量×30% + 动量×30%，越高越好\n")
