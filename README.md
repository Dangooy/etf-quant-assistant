# quant_assistant — 股票量化分析系统

回测 / 组合分析 / 选股筛选系统（无实盘下单，不含 API 密钥）。
数据源为免费 akshare，本地长期缓存，联网失败自动降级离线模式。

## 快速开始

```bash
pip install -r requirements.txt
python3 -m quant_assistant daily        # 每日检查
python3 -m quant_assistant backtest 000938 --strategy dual_ma
python3 -m quant_assistant screen
python3 -m quant_assistant dashboard    # 离线可用
python3 -m quant_assistant weekly       # ETF 周报与本周交易清单
```

**日常操作、配置维护、回测口径、故障处理见 [CLAUDE.md](CLAUDE.md)。**

## 模块结构

- `quant_assistant/__main__.py` — 统一 CLI 入口（daily / backtest / backtest-portfolio / screen / dashboard / weekly）
- `quant_assistant/backtest/` — 回测引擎（engine / metrics / strategy / runner / report）
- `quant_assistant/portfolio/` — 组合管理（持仓、风控引擎、告警、建议），完全离线
- `quant_assistant/screening/` — 选股筛选（universe / filters / scorer）
- `quant_assistant/analysis/` — 技术指标计算
- `quant_assistant/data/` — 数据获取（唯一联网入口，含缓存与离线降级）
- `data/cache/` — 行情长期缓存（历史只增不减）
- `data/portfolio.json` — 当前持仓组合（每次保存自动备份 .bak）
- `data/reports/` — 仪表盘与回测报告输出
