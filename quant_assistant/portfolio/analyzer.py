from typing import Dict
from collections import defaultdict
from tabulate import tabulate


class PortfolioAnalyzer:

    def __init__(self, portfolio_manager):
        self.pm = portfolio_manager

    def concentration_analysis(self) -> Dict:
        total_assets = self.pm.total_assets
        result = {"positions": [], "hhi_index": 0.0}
        hhi = 0.0
        for pos in sorted(self.pm.positions, key=lambda p: p.market_value, reverse=True):
            weight = pos.market_value / total_assets if total_assets > 0 else 0
            result["positions"].append({
                "code": pos.code,
                "name": pos.name,
                "weight": weight,
                "market_value": pos.market_value,
            })
            hhi += (weight * 100) ** 2
        if self.pm.cash > 0:
            cash_weight = self.pm.cash / total_assets if total_assets > 0 else 0
            hhi += (cash_weight * 100) ** 2
        result["hhi_index"] = hhi
        return result

    def market_distribution(self) -> Dict[str, float]:
        total_assets = self.pm.total_assets
        dist = defaultdict(float)
        for pos in self.pm.positions:
            dist[pos.market.value] += pos.market_value / total_assets if total_assets > 0 else 0
        if self.pm.cash > 0:
            dist["现金"] += self.pm.cash / total_assets if total_assets > 0 else 0
        return dict(dist)

    def sector_distribution(self) -> Dict[str, float]:
        total_assets = self.pm.total_assets
        dist = defaultdict(float)
        for pos in self.pm.positions:
            sector = pos.sector or "未分类"
            dist[sector] += pos.market_value / total_assets if total_assets > 0 else 0
        if self.pm.cash > 0:
            dist["现金"] += self.pm.cash / total_assets if total_assets > 0 else 0
        return dict(dist)

    def profit_loss_summary(self) -> Dict:
        total_pnl = sum(p.profit_loss_amount for p in self.pm.positions)
        total_cost = self.pm.total_cost
        return {
            "total_pnl_amount": total_pnl,
            "total_pnl_pct": total_pnl / total_cost if total_cost > 0 else 0,
            "winners": [p for p in self.pm.positions if p.profit_loss_pct > 0],
            "losers": [p for p in self.pm.positions if p.profit_loss_pct < 0],
            "max_winner": max(self.pm.positions, key=lambda p: p.profit_loss_pct, default=None),
            "max_loser": min(self.pm.positions, key=lambda p: p.profit_loss_pct, default=None),
        }

    def print_dashboard(self):
        total_mv = self.pm.total_market_value
        total_assets = self.pm.total_assets
        total_cost = self.pm.total_cost

        table_data = []
        for pos in sorted(self.pm.positions, key=lambda p: p.market_value, reverse=True):
            weight = pos.market_value / total_assets * 100 if total_assets > 0 else 0
            table_data.append([
                pos.code, pos.name, pos.market.value,
                f"{pos.shares:,}", f"{pos.cost_price:.4f}",
                f"{pos.current_price:.4f}",
                f"{pos.profit_loss_pct:+.2%}",
                f"{pos.profit_loss_amount:+,.0f}",
                f"{weight:.1f}%",
            ])

        headers = ["代码", "名称", "市场", "持股", "成本", "现价", "盈亏%", "盈亏额", "仓位"]
        print("\n" + "=" * 80)
        print("  持仓仪表盘")
        print("=" * 80)
        print(tabulate(table_data, headers=headers, tablefmt="grid"))

        total_pnl = total_mv - total_cost
        total_pnl_pct = total_pnl / total_cost if total_cost > 0 else 0
        print(f"\n  总资产: ¥{total_assets:,.0f}  |  持仓市值: ¥{total_mv:,.0f}  |  "
              f"现金: ¥{self.pm.cash:,.0f}  |  总成本: ¥{total_cost:,.0f}  |  "
              f"总盈亏: ¥{total_pnl:+,.0f} ({total_pnl_pct:+.2%})")

    def fundamental_analysis(self) -> list[dict]:
        """估值偏离分析：对比每只股票与行业中枢"""
        from ..config import SECTOR_BENCHMARKS
        results = []
        for pos in self.pm.positions:
            bench = SECTOR_BENCHMARKS.get(pos.sector, SECTOR_BENCHMARKS["未分类"])
            result = {"code": pos.code, "name": pos.name, "sector": pos.sector}
            if pos.has_fundamentals:
                result["pe"] = pos.pe
                result["pb"] = pos.pb
                result["roe"] = pos.roe
                result["pe_deviation"] = (pos.pe - bench["pe"]) / bench["pe"] if bench["pe"] else 0
                result["pb_deviation"] = (pos.pb - bench["pb"]) / bench["pb"] if bench["pb"] else 0
                # 估值判断
                if pos.pe < bench["pe"] * 0.7:
                    result["valuation"] = "低估"
                elif pos.pe > bench["pe"] * 1.5:
                    result["valuation"] = "高估"
                else:
                    result["valuation"] = "合理"
            else:
                result["pe"] = None
                result["valuation"] = "未录入"
            results.append(result)
        return results

    def print_fundamentals(self):
        results = self.fundamental_analysis()
        has_data = any(r["pe"] is not None for r in results)

        print("\n" + "=" * 80)
        print("  基本面估值分析（相对行业中枢）")
        print("=" * 80)

        if not has_data:
            print("  (尚未录入PE/PB数据，请在 portfolio.json 中补充)")
            return

        from ..config import SECTOR_BENCHMARKS
        table_data = []
        for r in results:
            if r["pe"] is None:
                table_data.append([r["code"], r["name"], r["sector"], "-", "-", "-", "未录入"])
            else:
                bench = SECTOR_BENCHMARKS.get(r["sector"], SECTOR_BENCHMARKS["未分类"])
                table_data.append([
                    r["code"], r["name"], r["sector"],
                    f"{r['pe']:.1f} (中枢{bench['pe']})",
                    f"{r['pb']:.2f} (中枢{bench['pb']:.1f})",
                    f"{r['roe']:.1f}%",
                    r["valuation"],
                ])

        headers = ["代码", "名称", "行业", "PE", "PB", "ROE", "估值判断"]
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
