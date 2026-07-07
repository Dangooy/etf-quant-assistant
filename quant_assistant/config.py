from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
REPORT_DIR = DATA_DIR / "reports"

# 手工维护的汇率：港币 → 人民币。用于把港股持仓折算成 CNY 后再算仓位权重/总盈亏。
# 更新方式：搜索"港币兑人民币"，把中间价填进来即可，偏差 1-2% 对风控结论无影响。
FX_RATES = {
    "HKD": 0.92,
}

# ETF 周度配置系统（docs/DESIGN-etf-weekly.md Phase 1）
# ETF_POOL 只维护场内 ETF 元数据；实际目标权重由 TARGET_WEIGHTS 和后续规则引擎决定。
ETF_POOL = {
    "511010": {"name": "国债ETF", "layer": "防守", "role": "久期收益"},
    "511360": {"name": "短融ETF", "layer": "防守", "role": "现金替代、迁移中转站"},
    "510300": {"name": "沪深300ETF", "layer": "进攻", "role": "A股核心"},
    "512890": {"name": "红利低波ETF", "layer": "进攻", "role": "低波权益，回撤友好"},
    "510500": {"name": "中证500ETF", "layer": "进攻", "role": "A股弹性"},
    "518880": {"name": "黄金ETF", "layer": "分散", "role": "危机对冲"},
    "513100": {"name": "纳指ETF", "layer": "分散", "role": "海外权益"},
    "513500": {"name": "标普500ETF", "layer": "分散", "role": "海外权益"},
}

# 战略中枢权重。A 股腿和海外腿会在 Phase 2 由动量规则选择实际持有标的；
# 这里给出一组可求和为 100% 的默认中枢模板，未入选候选在规则层权重为 0。
TARGET_WEIGHTS = {
    "511010": 0.35,   # 国债 35%
    "511360": 0.20,   # 短融 20%
    "510300": 0.125,  # A股腿候选，动量入选时约 12.5%
    "512890": 0.125,  # A股腿候选，动量入选时约 12.5%
    "510500": 0.0,    # A股腿候选，Phase 2 动量入选后使用 A股腿槽位
    "518880": 0.10,   # 黄金 10%
    "513100": 0.10,   # 海外腿候选，动量入选时约 10%
    "513500": 0.0,    # 海外腿候选，Phase 2 动量入选后使用海外腿槽位
}

# 周度策略参数集中维护。改参数需在 commit 中说明理由。
STRATEGY_PARAMS = {
    "ma_period_days": 200,          # 趋势过滤：收盘低于 200 日均线则该风险腿归零
    "momentum_window_weeks": 26,    # 动量轮动：26 周收益率排序
    "rebalance_band": 0.20,         # 再平衡带：相对目标权重偏离 ±20% 才交易
    "drawdown_warn": 0.06,          # 回撤断路器：组合自高点回撤 6% 风险腿减半
    "drawdown_stop": 0.08,          # 回撤断路器：组合自高点回撤 8% 风险腿清零
    "weekly_migration_limit": 0.15, # 存量迁移：每周卖出总额不超过总资产 15%
    "migration_overweight_threshold": 0.30, # 存量迁移：优先减占总资产超 30% 的仓位
    "lot_size": 100,                # 交易清单：按 100 份取整
    "min_trade_amount": 2000.0,     # 交易清单：单笔金额低于 2000 元忽略
    "commission_rate": 0.00025,     # 费用估算：佣金万 2.5
    "min_commission": 5.0,          # 费用估算：最低佣金 5 元
    "qdii_premium_limit": 0.03,     # QDII 溢价保护：溢价超过 3% 暂停买入
    "max_data_age_days": 7,         # 数据陈旧门禁：任一腿行情超过 7 天则禁止生成交易清单
}

RISK_DEFAULTS = {
    "single_position_max": 0.30,
    "single_position_warn": 0.20,
    "stop_loss_pct": -0.15,
    "total_loss_limit": -0.20,
    "market_hk_max": 0.60,
}

STOCK_SECTOR = {
    "000001": "金融",
    "00700": "信息技术",
}

# 行业估值中枢 (PE/PB/ROE%)，用于判断估值偏离
SECTOR_BENCHMARKS = {
    "信息技术": {"pe": 35, "pb": 4.0, "roe": 12},
    "金融":      {"pe": 8,  "pb": 0.8, "roe": 10},
    "消费":      {"pe": 25, "pb": 4.5, "roe": 18},
    "医药":      {"pe": 30, "pb": 3.5, "roe": 15},
    "科技ETF":   {"pe": 20, "pb": 2.5, "roe": 10},
    "未分类":    {"pe": 15, "pb": 1.5, "roe": 8},
}

# 手动维护的禁止池：财务爆雷 / ST / 流动性差
FORBIDDEN_POOL = set()

# A股涨跌停幅度
LIMIT_PCT = {
    "主板": 0.10,
    "创业板": 0.20,
    "科创板": 0.20,
    "北交所": 0.30,
    "ETF": 0.10,
}
