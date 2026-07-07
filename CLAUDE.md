# quant_assistant 操作手册

股票量化分析系统（回测 / 组合风控 / 选股筛选）。**无实盘下单，无 API 密钥。**
数据源为免费 akshare（爬东财），本地长期缓存，接口挂了自动降级为离线模式。

## 固定命令（日常只需这六条）

```bash
cd ~/projects/quant-assistant

# 1. 每日检查：拉行情 → 更新持仓现价 → 技术指标 → 风控告警 → HTML 仪表盘
python3 -m quant_assistant daily

# 2. 回测：策略 dual_ma / macd / rsi / kdj / composite
python3 -m quant_assistant backtest 000938 --strategy dual_ma --days 365 --no-open

# 3. 选股筛选（候选池在 quant_assistant/screening/universe.py 手工维护）
python3 -m quant_assistant screen

# 4. 仅生成持仓仪表盘（完全离线，不联网）
python3 -m quant_assistant dashboard

# 5. ETF 周报：组合状态 → 纪律提醒 → 本周交易清单 → Markdown 周报
python3 -m quant_assistant weekly

# 6. ETF 组合级回测：周度配置策略三组/四组对照
python3 -m quant_assistant backtest-portfolio --start 2016-01-01
```

输出位置：终端摘要 + `data/reports/` 下的 HTML（dashboard.html、backtest_*.html，回测报告带时间戳不覆盖）。

## 模块地图

| 目录 | 职责 |
|---|---|
| `quant_assistant/data/fetcher.py` | 唯一联网入口（akshare），缓存与离线降级 |
| `quant_assistant/portfolio/` | 持仓、风控规则、告警、操作建议（完全离线） |
| `quant_assistant/backtest/` | 回测引擎、指标计算、HTML 报告 |
| `quant_assistant/screening/` | 观察池、过滤器、评分 |
| `quant_assistant/config.py` | 所有手工维护的配置（见下） |
| `data/portfolio.json` | 唯一持仓数据文件 |
| `data/cache/` | 行情长期缓存（`{code}_daily.csv`，历史只增不减） |

## 数据文件与缓存机制

- **portfolio.json**：持仓列表。字段见 `data/portfolio.example.json`。港股 `current_price`/`cost_price` 填**港币原价**，系统按 `config.FX_RATES` 自动折算人民币。每次保存自动生成 `portfolio.json.bak`；文件损坏时程序报错并把原文件改名 `*.corrupt-<时间戳>`，用 `.bak` 恢复即可。
- **缓存**：每标的一份 `data/cache/{code}_daily.csv`。缓存覆盖到最近收盘交易日则不联网；否则重拉全段（qfq 复权基准保持一致）。**akshare 失败时自动用旧缓存并打印「数据截止 X（离线模式）」**——看到这个提示说明数据不是最新的，不是故障。

## 手工维护项（数据会过期，改这里）

| 项 | 位置 | 更新方式 |
|---|---|---|
| 港币汇率 `FX_RATES` | `config.py` | 搜"港币兑人民币"填中间价，偏差1-2%无碍 |
| 行业归属 `STOCK_SECTOR` | `config.py` | 新增持仓时补一行 |
| 行业估值中枢 `SECTOR_BENCHMARKS` | `config.py` | 极少动 |
| 禁止池 `FORBIDDEN_POOL` | `config.py` | 财务爆雷/ST 标的加入 |
| ETF 池 `ETF_POOL` | `config.py` | 只维护场内 ETF 元数据 |
| ETF 战略中枢 `TARGET_WEIGHTS` | `config.py` | 调整权重即改规则，需在 commit 写理由 |
| 周度策略参数 `STRATEGY_PARAMS` | `config.py` | 均线/动量/再平衡/断路器/迁移/交易阈值集中维护 |
| 观察池 `A_SHARE_WATCHLIST` | `screening/universe.py` | 增删候选标的 |
| 观察池基本面 `_KNOWN_FUNDAMENTALS` | `screening/screener.py` | 更新 PE/PB/ROE 后同步改 `_FUNDAMENTALS_AS_OF` |

## 周度纪律

1. 交易清单只能由规则生成；agent 的定性分析（新闻/财报）只能作为附注，不得改动清单。
2. 改参数 = 改 `config.py` 并在 git commit 中写理由，一周最多改一次。
3. 断路器触发时，唯一正确操作是执行清单，不许"再等等看"。
4. 连续 4 周未执行清单，系统在周报中黄字提醒偏离度。

## 回测口径（解读结果时必读）

- 成交假设：第 i 日收盘出信号，**第 i+1 日开盘价成交**（含滑点 0.1%）；一字涨跌停日顺延。
- 费用：佣金万2.5（最低5元）；A股卖出印花税千0.5，ETF 免；港股双向千1；过户费万0.1 仅沪市。
- ETF 组合级回测中，未投资现金按年化 2% 逐日计息（货币基金保守近似），主要用于覆盖短融ETF 511360 上市前的现金替代口径。
- 行情为前复权（qfq）：标的除权后历史价格整体漂移，**不同日期跑同一回测结果可能不同**，对比策略请同一天跑。
- 夏普显示 N/A = 数据不足；盈亏比 ∞ = 无亏损交易；年化标注"区间过短"时忽略该数字。

## 常见故障

| 现象 | 处理 |
|---|---|
| 拉行情反复失败 | 先看是否挂了代理（fetcher 已自动绕过 eastmoney 代理）；akshare 接口偶尔变动，`pip install -U akshare` 通常能解决 |
| 提示"离线模式" | 非故障，用的是本地缓存，数据截止日已打印 |
| portfolio.json 损坏报错 | `cp data/portfolio.json.bak data/portfolio.json` |
| 回测报告图表空白 | `data/reports/echarts.min.js` 缺失时会走 CDN；离线则确认该文件存在（源文件在 `quant_assistant/backtest/assets/`） |

## 修改代码的约束

- 联网调用只允许出现在 `data/fetcher.py`，其他模块保持离线可用。
- 不引入收费数据接口，不加实盘下单功能。
- 改动回测撮合/费用逻辑时，同步更新本文件「回测口径」一节。
