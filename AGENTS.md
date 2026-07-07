# 给实施代理（Codex 等）的项目约定

本项目的完整操作手册在 [CLAUDE.md](CLAUDE.md)，需求与架构设计在 [docs/DESIGN-etf-weekly.md](docs/DESIGN-etf-weekly.md)，分期实施提示词在 [docs/PROMPTS-etf-weekly.md](docs/PROMPTS-etf-weekly.md)。开工前必须全部读完。

## 硬性约束（违反任何一条 = 验收不通过）

1. 联网调用只允许出现在 `quant_assistant/data/fetcher.py`，其他模块必须离线可用。
2. 不引入收费数据接口，不加实盘下单功能。
3. Python 3.9 兼容：类型注解用 `Optional[X]`/`List[X]`，不用 `X | None`，不用 `match`。
4. 运行与自测一律用项目内 `.venv/bin/python`，不改系统环境。
5. 现有 CLI 命令（daily / backtest / screen / dashboard）在任何阶段都必须保持可用。
6. 交易清单只能由规则生成，定性内容只能进报告附注区。
7. 严格按 docs/PROMPTS-etf-weekly.md 一次只做一个 Phase：完成后 git commit（信息前缀 "PhaseN: "），输出变更文件清单和逐条自测结果，然后停下等待人工验收，不许自行开始下一期。
8. 禁止为凑回测指标做参数搜索或修改规则；回测不达标就如实报告。

## 环境

- 依赖已装在 `.venv`（akshare/pandas 等），新增依赖须写入 requirements.txt 并说明理由。
- akshare（东财）容易限流，出现「离线模式」提示是正常降级不是故障。
- 回测/撮合口径见 CLAUDE.md「回测口径」一节，改动撮合逻辑必须同步更新该节。
