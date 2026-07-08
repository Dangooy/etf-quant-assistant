# 策略不变量

本页列出审计整改后必须长期保持的红线。任何实现、重构、回测或报告改动，都必须先确认这些不变量没有被破坏；对应守卫测试必须真实存在且通过。

## 1. 联网调用只存在于 `quant_assistant/data/fetcher.py`

- 不变量：除数据获取层外，allocation、rebalance、weekly、backtest、portfolio 等模块都必须离线可运行，不得直接引入行情联网依赖。
- 守卫测试：`tests/test_invariants.py::InvariantTest::test_network_imports_stay_inside_fetcher`

## 2. 信号日不成交，下一交易日成交

- 不变量：回测和撮合不得使用信号日尚不可成交的价格，避免前视偏差；信号生成后必须在下一可交易日执行。
- 守卫测试：`tests/test_phase5_backtest_portfolio_indicators.py::Phase5BacktestExecutionTest::test_signal_executes_on_next_day_open`

## 3. 数据陈旧或缺失且有持仓时，交易清单整体阻断

- 不变量：行情陈旧或当前持仓标的行情缺失时，必须拒绝生成交易清单，包括迁移清单；宁可不给信号，也不给基于坏数据的清单。
- 守卫测试：`tests/test_phase2_allocation_rebalance.py::Phase2AllocationRebalanceTest::test_stale_gate_blocks_trade_plan`
- 守卫测试：`tests/test_phase2_allocation_rebalance.py::Phase2AllocationRebalanceTest::test_missing_data_with_current_position_blocks_all_trades`

## 4. 断路器高水位重置只能在确认执行后发生

- 不变量：`risk_zero` 只生成待确认的 pending reset；只有确认上期风险腿卖出已执行后，才允许应用高水位重置并清除 pending。
- 守卫测试：`tests/test_phase4_weekly.py::Phase4WeeklyTest::test_weekly_pending_reset_stays_armed_when_stop_trade_not_executed`
- 守卫测试：`tests/test_phase4_weekly.py::Phase4WeeklyTest::test_weekly_pending_reset_applies_after_stop_trade_execution`

## 5. 出入金必须记入 `cash_flows`，禁止直接改 `cash` 绕过台账

- 不变量：断路器回撤计算必须用累计出入金台账校正高水位；旧 state 首次见到 `flow_total_seen` 缺失时只写基线，不用历史流水一次性冲击高水位。
- 守卫测试：`tests/test_phase2_allocation_rebalance.py::Phase2AllocationRebalanceTest::test_cash_outflow_adjusts_high_water_and_avoids_false_stop`
- 守卫测试：`tests/test_phase2_allocation_rebalance.py::Phase2AllocationRebalanceTest::test_old_state_initializes_flow_baseline_without_changing_high_water`
- 守卫测试：`tests/test_phase5_backtest_portfolio_indicators.py::Phase5PortfolioManagerTest::test_missing_cash_flows_field_loads_as_empty_ledger`

## 6. 黄金样本基准值变化必须在 commit message 中解释

- 不变量：黄金样本是策略行为锚点；期末净值、最大回撤、交易笔数或年度收益序列变化，等同于策略行为变化，禁止静默更新基准。
- 守卫测试：`tests/test_golden_backtest.py::GoldenPortfolioBacktestTest::test_full_variant_matches_golden_fixture`

## 7. 交易清单只能由规则生成，定性判断只进报告附注

- 不变量：买卖方向、份额、金额、迁移限速、再平衡带、现金约束和 QDII 溢价拦截必须由规则函数计算；主观判断只能进入报告说明，不得直接改变交易清单。
- 守卫测试：`tests/test_phase2_allocation_rebalance.py::Phase2AllocationRebalanceTest::test_migration_trade_amount_is_capped_to_weekly_limit`
- 守卫测试：`tests/test_phase2_allocation_rebalance.py::Phase2AllocationRebalanceTest::test_buy_orders_are_limited_by_cash_after_sells_and_prioritized`
- 守卫测试：`tests/test_phase2_allocation_rebalance.py::Phase2AllocationRebalanceTest::test_planner_skips_qdii_buy_when_premium_over_limit`
