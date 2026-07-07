# etf-quant-assistant — ETF 周度配置系统

一个**个人自用级**的量化辅助工具：每周五收盘后自动分析，生成一张可直接照做的 ETF 交易清单。策略为「战略配置 + 趋势过滤 + 动量轮动 + 回撤断路器」，数据源全部免费（akshare），**无实盘接口，下单永远由人工完成**。

> ⚠️ **免责声明**：本项目仅为个人投研工具开源分享，不构成任何投资建议。回测收益不代表未来表现。使用者需对自己的交易决策负全部责任。

## 它做什么、不做什么

| 做 | 不做 |
|---|---|
| 每周生成目标权重与交易清单（含理由和费用估算） | 实盘自动下单 |
| 组合级回测（2016 年至今，含三组机制对照） | 预测市场、选妖股 |
| 回撤断路器、趋势过滤、数据陈旧门禁等风控 | 保证收益 |
| 持仓风控告警、存量持仓分批迁移计划 | 高频/日内交易 |

**诚实的预期**：回测（2016–2026，累计净值口径）年化约 5%，最大回撤约 6%，2018/2022 熊市回撤 4.4%/1.9%（同期沪深300 为 28.8%/24.7%）。这套系统的价值是**低回撤和纪律执行**，不是收益最大化——周报里常年显示与「50%红利低波+50%国债 持有不动」的对照线，让它自己证明存在价值。

## 安装

要求：Python ≥ 3.9，能访问国内公网（东财/天天基金数据源）。

### macOS / Linux

```bash
git clone https://github.com/Dangooy/etf-quant-assistant.git
cd etf-quant-assistant
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Windows（PowerShell）

```powershell
git clone https://github.com/Dangooy/etf-quant-assistant.git
cd etf-quant-assistant
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

以下示例均写 macOS 路径（`.venv/bin/python`），Windows 用户请自行替换为 `.venv\Scripts\python`。建议使用 Windows Terminal / PowerShell 7，老式 cmd 的中文表格显示不佳。

## 快速开始（三步）

**第 1 步：录入持仓。** 复制示例文件并按自己的实际持仓修改（`cash` 填证券账户可用现金，港股价格填港币原价，系统按 `config.py` 的 `FX_RATES` 自动折算人民币）：

```bash
cp data/portfolio.example.json data/portfolio.json
```

**第 2 步：拉取历史数据**（首次一次性，约几分钟）：

```bash
.venv/bin/python scripts/bootstrap_etf_cache.py          # ETF 池日线（周度信号用）
.venv/bin/python scripts/bootstrap_etf_cache.py --nav    # 累计净值（回测用）
```

**第 3 步：出第一份周报：**

```bash
.venv/bin/python -m quant_assistant weekly
```

终端会打印完整周报，同时落盘到 `data/reports/weekly-<日期>.md`。

## 使用

### 命令一览

| 命令 | 用途 | 频率 |
|---|---|---|
| `python -m quant_assistant weekly` | **核心命令**：组合状态、回撤水位、各腿信号、本周交易清单、迁移进度、纪律提醒、对照基准线 | 每周 |
| `python -m quant_assistant daily` | 拉行情→更新持仓现价→技术指标→风控告警→HTML 仪表盘；断路器触及阈值时醒目告警 | 可选，每交易日 |
| `python -m quant_assistant dashboard` | 只生成持仓仪表盘（完全离线） | 随时 |
| `python -m quant_assistant backtest-portfolio --start 2016-01-01` | 组合级回测，输出年度收益表 + 与沪深300对照 + HTML 报告 | 验证策略时 |
| `python -m quant_assistant backtest <code> --strategy dual_ma` | 单标的技术策略回测（双均线/MACD/RSI/KDJ/组合） | 研究用 |
| `python -m quant_assistant screen` | A 股观察池多因子筛选 | 研究用 |

### 周度工作流（每周 10 分钟）

1. 周五收盘后运行 `weekly`（或配置定时任务自动跑）；
2. 周末看报告：清单每条都带触发规则和费用估算，执行顺序固定「先卖出后买入」；
3. 下周一照单下单，然后把成交结果更新进 `data/portfolio.json`（改 `shares`/`cash`）；
4. 下次运行时系统自动核对上期清单执行情况，未执行会黄字提醒偏离金额。

### 定时任务（推荐，让系统主动找你）

macOS（launchd，模板内路径请按本机修改）：

```bash
cp scripts/com.quant.weekly.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.quant.weekly.plist
```

Windows（任务计划程序）：

```powershell
schtasks /create /tn "quant-weekly" /sc weekly /d FRI /st 16:30 `
  /tr "C:\你的路径\etf-quant-assistant\.venv\Scripts\python.exe -m quant_assistant weekly"
```

内置**心跳监控**：周报超过 8 天未运行，任何命令启动时都会黄字警告「周报任务可能已停摆」——定时任务静默死掉不会无人察觉。

### 策略规则（全部机械可执行，参数集中在 `config.py`）

- **资产池**：国债 ETF + 短融 ETF（防守 ≥55%）、沪深300/红利低波/中证500（A 股腿动量取 2）、纳指/标普（海外腿取 1）、黄金 10%；
- **趋势过滤**：任一风险腿收盘 < 200 日均线 → 该腿归零，资金回短融；
- **动量轮动**：26 周收益率排序；
- **再平衡带**：权重相对偏离 ±20% 以内不动（控制交易成本）；
- **回撤断路器**：组合自高点回撤 ≥6% 风险腿减半、≥8% 清零并重置高水位，恢复交回趋势规则；
- **数据陈旧门禁**：行情超过 7 天未更新时拒绝生成交易清单——宁可不给信号，不给错误信号；
- **存量迁移**：目标池外的旧持仓按周分批清出，每周卖出 ≤ 总资产 15%。

完整设计与回测验收标准见 [docs/DESIGN-etf-weekly.md](docs/DESIGN-etf-weekly.md)。

### 数据源与离线模式

- 行情：akshare（东财），**免费无 key**；每标的一份长期缓存，历史只增不减；
- 回测：天天基金**累计净值**（含分红、历史不随除权漂移、结果可复现）；
- 联网失败自动降级用本地缓存，并明确标注「数据截止 X（离线模式）」——看到这个提示是保护机制生效，不是故障。东财偶发 IP 限流，等待即可自动恢复。

### 给 AI Agent 使用

本项目为「任何模型都能照手册操作」设计：Claude Code 自动读取 [CLAUDE.md](CLAUDE.md)（操作手册：固定命令/维护项/回测口径/故障处理），Codex 等自动读取 [AGENTS.md](AGENTS.md)（硬约束：联网只许在数据层、清单只能由规则生成、改参数须写理由等）。对 agent 说"跑一下周报并解读"即可。

### 测试

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q     # 29 项：撮合/费用/断路器/迁移限速/数据容错/指标边界
```

## 目录结构

```
quant_assistant/
├── __main__.py          # 统一 CLI 入口
├── config.py            # 所有手工维护的配置（ETF池/权重/策略参数/汇率）
├── allocation/          # 目标权重引擎（趋势→动量→断路器）
├── rebalance/           # 交易清单生成（取整/现金约束/费用/迁移限速）
├── weekly.py            # 周报生成/心跳/清单核对/基准对照
├── backtest/            # 单标的引擎 + 组合级引擎 + HTML 报告
├── portfolio/           # 持仓/风控规则/告警/建议
├── data/fetcher.py      # 唯一联网入口（缓存与离线降级）
├── screening/           # A股观察池多因子筛选
└── analysis/            # 技术指标
```

## 常见问题

| 现象 | 处理 |
|---|---|
| 拉行情反复失败 | 东财偶发 IP 限流，等几小时自动恢复；期间离线模式照常可用 |
| 提示「数据陈旧，禁止按此操作」 | 门禁生效：行情超 7 天未更新，先恢复数据再要清单 |
| portfolio.json 损坏报错 | 每次保存自动备份：`cp data/portfolio.json.bak data/portfolio.json` |
| 回测报告图表空白 | 确认 `data/reports/echarts.min.js` 存在（源文件在 `quant_assistant/backtest/assets/`） |

版本历史见 [CHANGELOG.md](CHANGELOG.md)。
