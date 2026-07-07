# ETF 周报 launchd 安装说明

本文件只记录安装命令，不替用户执行。

```bash
cd /Users/ethan/projects/quant-assistant
plutil -lint scripts/com.quant.weekly.plist
cp scripts/com.quant.weekly.plist ~/Library/LaunchAgents/com.quant.weekly.plist
launchctl load ~/Library/LaunchAgents/com.quant.weekly.plist
```

定时任务每周五 16:30 执行：

```bash
/Users/ethan/projects/quant-assistant/.venv/bin/python -m quant_assistant weekly
```

日志写入：

```text
/Users/ethan/projects/quant-assistant/data/reports/launchd.log
```
