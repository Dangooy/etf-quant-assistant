from typing import List

from ..models import RiskAlert, Market
from ..config import RISK_DEFAULTS, FORBIDDEN_POOL


class RiskRule:
    def __init__(self, name: str, level: str, threshold: float):
        self.name = name
        self.level = level
        self.threshold = threshold

    def check(self, pm) -> List[RiskAlert]:
        raise NotImplementedError


class SinglePositionRule(RiskRule):
    def __init__(self, name: str, level: str, threshold: float,
                 upper: float = None):
        """upper: 仅在 threshold < weight <= upper 区间触发。
        用于预警规则，避免与上限规则同时触发产生矛盾建议。"""
        super().__init__(name, level, threshold)
        self.upper = upper

    def check(self, pm) -> List[RiskAlert]:
        alerts = []
        total_assets = pm.total_assets
        for pos in pm.positions:
            weight = pos.market_value / total_assets if total_assets > 0 else 0
            if weight > self.threshold and (self.upper is None or weight <= self.upper):
                alerts.append(RiskAlert(
                    level=self.level,
                    rule_name=self.name,
                    message=(f"{pos.name}({pos.code}) 仓位 {weight:.1%} "
                             f"超过阈值 {self.threshold:.0%}"),
                    stock_code=pos.code,
                    current_value=weight,
                    threshold=self.threshold,
                ))
        return alerts


class StopLossRule(RiskRule):
    def check(self, pm) -> List[RiskAlert]:
        alerts = []
        for pos in pm.positions:
            if pos.profit_loss_pct < self.threshold:
                alerts.append(RiskAlert(
                    level=self.level,
                    rule_name=self.name,
                    message=(f"{pos.name}({pos.code}) 亏损 {pos.profit_loss_pct:.1%} "
                             f"已触及止损线 {self.threshold:.0%}"),
                    stock_code=pos.code,
                    current_value=pos.profit_loss_pct,
                    threshold=self.threshold,
                ))
        return alerts


class MarketConcentrationRule(RiskRule):
    def check(self, pm) -> List[RiskAlert]:
        alerts = []
        total_assets = pm.total_assets
        hk_mv = sum(p.market_value for p in pm.positions if p.market == Market.HK)
        hk_ratio = hk_mv / total_assets if total_assets > 0 else 0
        if hk_ratio > self.threshold:
            alerts.append(RiskAlert(
                level=self.level,
                rule_name=self.name,
                message=(f"港股占比 {hk_ratio:.1%} 超过阈值 {self.threshold:.0%}，"
                         f"建议分散到A股"),
                current_value=hk_ratio,
                threshold=self.threshold,
            ))
        return alerts


class TotalLossRule(RiskRule):
    def check(self, pm) -> List[RiskAlert]:
        alerts = []
        total_assets = pm.total_assets
        total_cost_basis = pm.total_cost + pm.cash
        total_pnl = ((total_assets - total_cost_basis) / total_cost_basis
                     if total_cost_basis > 0 else 0)
        if total_pnl < self.threshold:
            alerts.append(RiskAlert(
                level=self.level,
                rule_name=self.name,
                message=(f"总资产亏损 {total_pnl:.1%} 已触及限制 {self.threshold:.0%}，"
                         f"建议大幅减仓"),
                current_value=total_pnl,
                threshold=self.threshold,
            ))
        return alerts


class ForbiddenPoolRule(RiskRule):
    """禁止池检查：持仓中出现禁止池标的时触发 CRITICAL 告警"""

    def __init__(self):
        super().__init__("禁止池", "CRITICAL", 0)

    def check(self, pm) -> List[RiskAlert]:
        alerts = []
        for pos in pm.positions:
            if pos.code in FORBIDDEN_POOL:
                alerts.append(RiskAlert(
                    level="CRITICAL",
                    rule_name=self.name,
                    message=f"{pos.name}({pos.code}) 在禁止池中，存在退市或财务爆雷风险，建议立即清仓",
                    stock_code=pos.code,
                ))
        return alerts


class RiskEngine:

    def __init__(self):
        self.rules: List[RiskRule] = []
        self._init_default_rules()

    def _init_default_rules(self):
        self.rules = [
            SinglePositionRule("单只仓位上限", "DANGER", RISK_DEFAULTS["single_position_max"]),
            SinglePositionRule("单只仓位预警", "WARNING", RISK_DEFAULTS["single_position_warn"],
                               upper=RISK_DEFAULTS["single_position_max"]),
            StopLossRule("个股止损线", "DANGER", RISK_DEFAULTS["stop_loss_pct"]),
            MarketConcentrationRule("港股占比上限", "WARNING", RISK_DEFAULTS["market_hk_max"]),
            TotalLossRule("总亏损限制", "CRITICAL", RISK_DEFAULTS["total_loss_limit"]),
            ForbiddenPoolRule(),
        ]

    def run_all_checks(self, pm) -> List[RiskAlert]:
        all_alerts = []
        for rule in self.rules:
            all_alerts.extend(rule.check(pm))
        severity_order = {"CRITICAL": 0, "DANGER": 1, "WARNING": 2}
        all_alerts.sort(key=lambda a: severity_order.get(a.level, 99))
        return all_alerts

    def add_rule(self, rule: RiskRule):
        self.rules.append(rule)
