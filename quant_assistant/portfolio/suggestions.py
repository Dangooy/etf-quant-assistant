"""
操作建议引擎：根据风控告警和持仓数据，按规则生成操作建议。
建议由规则推导，不针对特定股票硬编码。
"""
from typing import List

from .holdings import PortfolioManager
from ..models import RiskAlert
from ..config import RISK_DEFAULTS


def generate_suggestions(pm: PortfolioManager, alerts: List[RiskAlert]) -> List[str]:
    """
    根据告警类型和持仓数据，按优先级生成操作建议。
    每条建议都是"规则条件 → 建议动作"的映射，人可以修改规则阈值。
    """
    suggestions = []
    for alert in alerts:
        if alert.rule_name == "单只仓位上限":
            pos = pm.get_position(alert.stock_code)
            if pos:
                target_weight = RISK_DEFAULTS["single_position_max"]
                excess = alert.current_value - target_weight
                suggestions.append(
                    f"{pos.name}({pos.code})仓位{alert.current_value:.1%}，"
                    f"超限{excess:.1%}。建议分批减仓至{target_weight:.0%}以下"
                )

        elif alert.rule_name == "个股止损线":
            pos = pm.get_position(alert.stock_code)
            if pos:
                loss_pct = alert.current_value
                if loss_pct < -0.30:
                    suggestions.append(
                        f"{pos.name}({pos.code})亏损{loss_pct:.1%}严重超限。"
                        f"若无明确反转催化剂，建议止损离场"
                    )
                else:
                    suggestions.append(
                        f"{pos.name}({pos.code})亏损{loss_pct:.1%}触及止损线。"
                        f"建议设置反弹减仓目标价，逢高分批减持"
                    )

        elif alert.rule_name == "港股占比上限":
            suggestions.append(
                f"港股占比{alert.current_value:.1%}超限。"
                f"建议减仓港股后优先配置A股优质标的，降低汇率和波动风险"
            )

        elif alert.rule_name == "总亏损限制":
            suggestions.append(
                f"总资产亏损{alert.current_value:.1%}已触及限制。"
                f"建议大幅减仓至安全仓位，优先砍亏损最大的持仓"
            )

        elif alert.rule_name == "单只仓位预警":
            pos = pm.get_position(alert.stock_code)
            if pos:
                suggestions.append(
                    f"{pos.name}({pos.code})仓位{alert.current_value:.1%}接近预警线，"
                    f"暂不操作但需密切关注"
                )

    # 去重
    seen = set()
    unique = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    return unique
