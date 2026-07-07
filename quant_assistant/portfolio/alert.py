from typing import List
from loguru import logger

from ..models import RiskAlert


class AlertManager:

    LEVEL_ICONS = {
        "CRITICAL": "[!!!]",
        "DANGER": "[!!]",
        "WARNING": "[!]",
    }

    def __init__(self, log_file: str = None):
        if log_file:
            logger.add(log_file, rotation="1 week", encoding="utf-8")

    def output_alerts(self, alerts: List[RiskAlert]):
        if not alerts:
            print("\n  [OK] 风控检查通过，无告警。")
            return

        print("\n" + "=" * 60)
        print("  风控告警报告")
        print("=" * 60)

        for alert in alerts:
            icon = self.LEVEL_ICONS.get(alert.level, "[?]")
            print(f"\n  {icon} [{alert.level}] {alert.rule_name}")
            print(f"      {alert.message}")
            if alert.stock_code:
                print(f"      相关股票: {alert.stock_code}")
            logger.warning(f"[{alert.level}] {alert.rule_name}: {alert.message}")

        critical = sum(1 for a in alerts if a.level == "CRITICAL")
        danger = sum(1 for a in alerts if a.level == "DANGER")
        warning = sum(1 for a in alerts if a.level == "WARNING")
        print(f"\n  --- 汇总: {critical}个严重 | {danger}个危险 | {warning}个预警 ---")
