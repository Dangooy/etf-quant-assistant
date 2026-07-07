import datetime
import json
from pathlib import Path
from typing import List, Optional

from .models import Market
from .portfolio.holdings import PortfolioManager
from .portfolio.analyzer import PortfolioAnalyzer
from .portfolio.risk_engine import RiskEngine
from .config import REPORT_DIR


def generate_dashboard(pm: PortfolioManager, stock_data: Optional[dict] = None,
                       output_path: Optional[Path] = None,
                       top_alerts: Optional[List[str]] = None) -> Path:
    output_path = output_path or REPORT_DIR / "dashboard.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    analyzer = PortfolioAnalyzer(pm)
    engine = RiskEngine()
    alerts = engine.run_all_checks(pm)

    total_mv = pm.total_market_value
    total_assets = pm.total_assets
    total_cost = pm.total_cost
    total_pnl = total_mv - total_cost
    total_pnl_pct = total_pnl / total_cost if total_cost > 0 else 0

    conc = analyzer.concentration_analysis()
    market_dist = analyzer.market_distribution()
    sector_dist = analyzer.sector_distribution()
    pnl_summary = analyzer.profit_loss_summary()

    positions_json = []
    for pos in sorted(pm.positions, key=lambda p: p.market_value, reverse=True):
        weight = pos.market_value / total_assets * 100 if total_assets > 0 else 0
        positions_json.append({
            "code": pos.code,
            "name": pos.name,
            "market": pos.market.value,
            "shares": pos.shares,
            "cost_price": round(pos.cost_price, 4),
            "current_price": round(pos.current_price, 4),
            "pnl_pct": round(pos.profit_loss_pct * 100, 2),
            "pnl_amount": round(pos.profit_loss_amount, 0),
            "weight": round(weight, 1),
            "market_value": round(pos.market_value, 0),
        })

    market_dist_json = [{"name": k, "value": round(v * 100, 1)} for k, v in market_dist.items()]
    sector_dist_json = [{"name": k, "value": round(v * 100, 1)} for k, v in sector_dist.items()]

    alerts_json = []
    for a in alerts:
        alerts_json.append({
            "level": a.level,
            "rule": a.rule_name,
            "message": a.message,
            "code": a.stock_code,
        })

    kline_data_json = {}
    if stock_data:
        for code, df in stock_data.items():
            if df is None or df.empty:
                continue
            records = []
            for _, row in df.tail(60).iterrows():
                date_str = row["日期"].strftime("%m-%d") if hasattr(row["日期"], "strftime") else str(row["日期"])[-5:]
                rec = {
                    "date": date_str,
                    "open": round(float(row.get("开盘", 0)), 2),
                    "close": round(float(row.get("收盘", 0)), 2),
                    "high": round(float(row.get("最高", 0)), 2),
                    "low": round(float(row.get("最低", 0)), 2),
                }
                if "MA5" in row and not _isnan(row["MA5"]):
                    rec["ma5"] = round(float(row["MA5"]), 2)
                if "MA20" in row and not _isnan(row["MA20"]):
                    rec["ma20"] = round(float(row["MA20"]), 2)
                records.append(rec)
            name = ""
            for p in pm.positions:
                if p.code == code:
                    name = p.name
                    break
            kline_data_json[code] = {"name": name, "data": records}

    signals_json = {}
    if stock_data:
        from .analysis.indicators import get_signals
        for code, df in stock_data.items():
            if df is not None and not df.empty:
                sigs = get_signals(df)
                if sigs:
                    name = ""
                    for p in pm.positions:
                        if p.code == code:
                            name = p.name
                            break
                    signals_json[code] = {"name": name, "signals": sigs}

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    html = _build_html(
        now_str=now_str,
        total_mv=total_mv,
        total_assets=total_assets,
        cash=pm.cash,
        total_cost=total_cost,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        hhi=conc["hhi_index"],
        positions=json.dumps(positions_json, ensure_ascii=False),
        market_dist=json.dumps(market_dist_json, ensure_ascii=False),
        sector_dist=json.dumps(sector_dist_json, ensure_ascii=False),
        alerts=json.dumps(alerts_json, ensure_ascii=False),
        kline_data=json.dumps(kline_data_json, ensure_ascii=False),
        signals=json.dumps(signals_json, ensure_ascii=False),
        num_danger=sum(1 for a in alerts if a.level == "DANGER"),
        num_warning=sum(1 for a in alerts if a.level == "WARNING"),
        num_critical=sum(1 for a in alerts if a.level == "CRITICAL"),
        top_alerts=json.dumps(top_alerts or [], ensure_ascii=False),
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def _isnan(v):
    try:
        import math
        return math.isnan(float(v))
    except (ValueError, TypeError):
        return True


def _build_html(**ctx) -> str:
    pnl_color = "#e74c3c" if ctx["total_pnl"] < 0 else "#2ecc71"
    pnl_sign = "+" if ctx["total_pnl"] >= 0 else ""
    hhi_label = "高度集中" if ctx["hhi"] > 2500 else ("中度集中" if ctx["hhi"] > 1500 else "分散")
    hhi_color = "#e74c3c" if ctx["hhi"] > 2500 else ("#f39c12" if ctx["hhi"] > 1500 else "#2ecc71")

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>持仓仪表盘</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #0a0e17; color: #e0e0e0; min-height: 100vh; }}
.header {{ background: linear-gradient(135deg, #1a1f2e 0%, #0d1117 100%); padding: 20px 30px; border-bottom: 1px solid #1e2d3d; display: flex; justify-content: space-between; align-items: center; }}
.header h1 {{ font-size: 22px; color: #fff; }}
.header .time {{ color: #8b949e; font-size: 14px; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}

.summary-cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
.card {{ background: #161b22; border: 1px solid #21262d; border-radius: 12px; padding: 20px; }}
.card .label {{ color: #8b949e; font-size: 13px; margin-bottom: 8px; }}
.card .value {{ font-size: 26px; font-weight: 700; }}
.card .sub {{ font-size: 13px; margin-top: 4px; }}

.grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }}
.grid-3 {{ display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-bottom: 24px; }}

.section {{ background: #161b22; border: 1px solid #21262d; border-radius: 12px; padding: 20px; margin-bottom: 24px; }}
.section h2 {{ font-size: 16px; color: #c9d1d9; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid #21262d; }}

table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th {{ text-align: left; padding: 10px 12px; color: #8b949e; font-weight: 500; border-bottom: 1px solid #21262d; }}
td {{ padding: 10px 12px; border-bottom: 1px solid #161b22; }}
tr:hover {{ background: #1c2333; }}
.pos {{ color: #2ecc71; }}
.neg {{ color: #e74c3c; }}

.alert-item {{ padding: 12px 16px; margin-bottom: 8px; border-radius: 8px; font-size: 14px; }}
.alert-CRITICAL {{ background: rgba(231,76,60,0.15); border-left: 4px solid #e74c3c; }}
.alert-DANGER {{ background: rgba(243,156,18,0.15); border-left: 4px solid #f39c12; }}
.alert-WARNING {{ background: rgba(52,152,219,0.15); border-left: 4px solid #3498db; }}
.alert-level {{ font-weight: 700; margin-right: 8px; }}

.pie-container {{ display: flex; justify-content: center; align-items: center; gap: 20px; }}
.pie-legend {{ font-size: 13px; }}
.pie-legend-item {{ display: flex; align-items: center; margin-bottom: 6px; }}
.pie-legend-dot {{ width: 12px; height: 12px; border-radius: 3px; margin-right: 8px; }}

.bar {{ height: 24px; border-radius: 4px; margin-bottom: 6px; display: flex; align-items: center; padding-left: 8px; font-size: 12px; color: #fff; min-width: 30px; }}

.weight-bar-container {{ margin-bottom: 4px; }}
.weight-label {{ font-size: 13px; display: flex; justify-content: space-between; margin-bottom: 2px; }}

.signal-item {{ padding: 8px 12px; margin-bottom: 6px; border-radius: 6px; font-size: 13px; }}
.signal-buy {{ background: rgba(46,204,113,0.12); border-left: 3px solid #2ecc71; }}
.signal-sell {{ background: rgba(231,76,60,0.12); border-left: 3px solid #e74c3c; }}
.signal-neutral {{ background: rgba(149,165,166,0.12); border-left: 3px solid #95a5a6; }}

.kline-section {{ margin-bottom: 16px; }}
.kline-title {{ font-size: 14px; color: #c9d1d9; margin-bottom: 8px; }}
canvas {{ display: block; }}

.badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }}
.badge-danger {{ background: rgba(243,156,18,0.2); color: #f39c12; }}
.badge-warning {{ background: rgba(52,152,219,0.2); color: #3498db; }}
.badge-critical {{ background: rgba(231,76,60,0.2); color: #e74c3c; }}

@media (max-width: 768px) {{
    .summary-cards {{ grid-template-columns: repeat(2, 1fr); }}
    .grid-2, .grid-3 {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>

<div class="header">
    <h1>持仓量化仪表盘</h1>
    <div class="time">更新时间: {ctx["now_str"]}</div>
</div>

<div class="container">

<div class="summary-cards">
    <div class="card">
        <div class="label">总资产</div>
        <div class="value" style="color:#fff">¥{ctx["total_assets"]:,.0f}</div>
        <div class="sub">持仓 ¥{ctx["total_mv"]:,.0f} / 现金 ¥{ctx["cash"]:,.0f}</div>
    </div>
    <div class="card">
        <div class="label">总盈亏</div>
        <div class="value" style="color:{pnl_color}">{pnl_sign}¥{ctx["total_pnl"]:,.0f}</div>
        <div class="sub" style="color:{pnl_color}">{pnl_sign}{ctx["total_pnl_pct"]:.2%}</div>
    </div>
    <div class="card">
        <div class="label">HHI集中度</div>
        <div class="value" style="color:{hhi_color}">{ctx["hhi"]:.0f}</div>
        <div class="sub" style="color:{hhi_color}">{hhi_label}</div>
    </div>
    <div class="card">
        <div class="label">风控告警</div>
        <div class="value" style="color:{"#e74c3c" if ctx["num_danger"] > 0 else "#2ecc71"}">{ctx["num_critical"] + ctx["num_danger"] + ctx["num_warning"]}</div>
        <div class="sub">
            <span class="badge badge-critical">{ctx["num_critical"]} 严重</span>
            <span class="badge badge-danger">{ctx["num_danger"]} 危险</span>
            <span class="badge badge-warning">{ctx["num_warning"]} 预警</span>
        </div>
    </div>
</div>

<div class="section">
    <h2>持仓明细</h2>
    <table>
        <thead>
            <tr>
                <th>代码</th><th>名称</th><th>市场</th><th>持股</th>
                <th>成本</th><th>现价</th><th>盈亏%</th><th>盈亏额</th><th>仓位</th>
            </tr>
        </thead>
        <tbody id="positions-table"></tbody>
    </table>
</div>

<div class="grid-2">
    <div class="section">
        <h2>市场分布</h2>
        <div id="market-bars"></div>
    </div>
    <div class="section">
        <h2>行业分布</h2>
        <div id="sector-bars"></div>
    </div>
</div>

<div class="section">
    <h2>仓位分布</h2>
    <div id="weight-bars"></div>
</div>

<div class="section" id="alerts-section">
    <h2>风控告警</h2>
    <div id="alerts-container"></div>
</div>

<div class="section" id="signals-section" style="display:none">
    <h2>技术信号</h2>
    <div id="signals-container"></div>
</div>

<div class="section" id="kline-section" style="display:none">
    <h2>K线走势 (近60日)</h2>
    <div id="kline-container"></div>
</div>

</div>

<script>
const positions = {ctx["positions"]};
const marketDist = {ctx["market_dist"]};
const sectorDist = {ctx["sector_dist"]};
const alerts = {ctx["alerts"]};
const klineData = {ctx["kline_data"]};
const signals = {ctx["signals"]};
const topAlerts = {ctx["top_alerts"]};

const COLORS = ["#3498db","#2ecc71","#e74c3c","#f39c12","#9b59b6","#1abc9c","#e67e22","#34495e"];

if (topAlerts.length > 0) {{
    const container = document.querySelector(".container");
    const alertBox = document.createElement("div");
    alertBox.className = "section";
    alertBox.style.borderColor = "#e74c3c";
    alertBox.style.background = "rgba(231,76,60,0.12)";
    alertBox.innerHTML = "<h2>断路器告警</h2>" + topAlerts.map(a => `<div class="alert-item alert-CRITICAL">${{a}}</div>`).join("");
    container.prepend(alertBox);
}}

// Positions table
const tbody = document.getElementById("positions-table");
positions.forEach(p => {{
    const pnlClass = p.pnl_pct >= 0 ? "pos" : "neg";
    const sign = p.pnl_pct >= 0 ? "+" : "";
    tbody.innerHTML += `<tr>
        <td>${{p.code}}</td><td>${{p.name}}</td><td>${{p.market}}</td>
        <td>${{p.shares.toLocaleString()}}</td>
        <td>${{p.cost_price.toFixed(4)}}</td><td>${{p.current_price.toFixed(4)}}</td>
        <td class="${{pnlClass}}">${{sign}}${{p.pnl_pct.toFixed(2)}}%</td>
        <td class="${{pnlClass}}">${{sign}}${{p.pnl_amount.toLocaleString()}}</td>
        <td>${{p.weight.toFixed(1)}}%</td>
    </tr>`;
}});

// Bar charts
function renderBars(containerId, data) {{
    const el = document.getElementById(containerId);
    const max = Math.max(...data.map(d => d.value));
    data.sort((a, b) => b.value - a.value);
    data.forEach((d, i) => {{
        const pct = (d.value / max) * 100;
        el.innerHTML += `
            <div class="weight-label"><span>${{d.name}}</span><span>${{d.value.toFixed(1)}}%</span></div>
            <div class="bar" style="width:${{Math.max(pct, 8)}}%;background:${{COLORS[i % COLORS.length]}}">${{d.value.toFixed(1)}}%</div>`;
    }});
}}
renderBars("market-bars", marketDist);
renderBars("sector-bars", sectorDist);

// Weight bars (positions)
const weightEl = document.getElementById("weight-bars");
positions.forEach((p, i) => {{
    const color = p.pnl_pct >= 0 ? "#2ecc71" : "#e74c3c";
    weightEl.innerHTML += `
        <div class="weight-label"><span>${{p.name}} (${{p.code}})</span><span>${{p.weight.toFixed(1)}}%</span></div>
        <div class="bar" style="width:${{Math.max(p.weight, 2)}}%;background:${{color}}">${{p.weight.toFixed(1)}}%</div>`;
}});

// Alerts
const alertsEl = document.getElementById("alerts-container");
if (alerts.length === 0) {{
    alertsEl.innerHTML = '<div style="color:#2ecc71;padding:12px">✓ 风控检查通过，无告警</div>';
}} else {{
    alerts.forEach(a => {{
        const levelLabels = {{"CRITICAL":"严重","DANGER":"危险","WARNING":"预警"}};
        alertsEl.innerHTML += `
            <div class="alert-item alert-${{a.level}}">
                <span class="alert-level">[${{levelLabels[a.level] || a.level}}]</span>
                <span>${{a.rule}}: ${{a.message}}</span>
            </div>`;
    }});
}}

// Signals
const sigKeys = Object.keys(signals);
if (sigKeys.length > 0) {{
    document.getElementById("signals-section").style.display = "block";
    const sigEl = document.getElementById("signals-container");
    sigKeys.forEach(code => {{
        const s = signals[code];
        sigEl.innerHTML += `<div style="font-weight:600;margin:12px 0 6px;color:#c9d1d9">${{s.name}} (${{code}})</div>`;
        s.signals.forEach(sig => {{
            let cls = "signal-neutral";
            if (sig.includes("买入") || sig.includes("金叉") || sig.includes("超卖") || sig.includes("反弹")) cls = "signal-buy";
            if (sig.includes("卖出") || sig.includes("死叉") || sig.includes("超买") || sig.includes("回调")) cls = "signal-sell";
            sigEl.innerHTML += `<div class="signal-item ${{cls}}">${{sig}}</div>`;
        }});
    }});
}}

// K-line
const klKeys = Object.keys(klineData);
if (klKeys.length > 0) {{
    document.getElementById("kline-section").style.display = "block";
    const klEl = document.getElementById("kline-container");
    klKeys.forEach(code => {{
        const info = klineData[code];
        const canvasId = `kline-${{code}}`;
        klEl.innerHTML += `
            <div class="kline-section">
                <div class="kline-title">${{info.name}} (${{code}})</div>
                <canvas id="${{canvasId}}" width="1200" height="300"></canvas>
            </div>`;
    }});

    klKeys.forEach(code => {{
        const info = klineData[code];
        drawKline(`kline-${{code}}`, info.data);
    }});
}}

function drawKline(canvasId, data) {{
    const canvas = document.getElementById(canvasId);
    if (!canvas || !data || data.length === 0) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    const pad = {{top: 20, right: 60, bottom: 30, left: 10}};
    const chartW = W - pad.left - pad.right;
    const chartH = H - pad.top - pad.bottom;

    const allPrices = data.flatMap(d => [d.high, d.low]);
    const minP = Math.min(...allPrices) * 0.998;
    const maxP = Math.max(...allPrices) * 1.002;
    const range = maxP - minP || 1;

    const barW = chartW / data.length;
    const bodyW = barW * 0.7;

    function y(price) {{ return pad.top + chartH * (1 - (price - minP) / range); }}
    function x(i) {{ return pad.left + i * barW + barW / 2; }}

    ctx.fillStyle = "#161b22";
    ctx.fillRect(0, 0, W, H);

    // Grid
    ctx.strokeStyle = "#21262d";
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {{
        const py = pad.top + chartH * i / 4;
        ctx.beginPath(); ctx.moveTo(pad.left, py); ctx.lineTo(W - pad.right, py); ctx.stroke();
        const price = maxP - range * i / 4;
        ctx.fillStyle = "#8b949e"; ctx.font = "11px sans-serif"; ctx.textAlign = "left";
        ctx.fillText(price.toFixed(2), W - pad.right + 5, py + 4);
    }}

    // Candles
    data.forEach((d, i) => {{
        const cx = x(i);
        const isUp = d.close >= d.open;
        const color = isUp ? "#2ecc71" : "#e74c3c";

        ctx.strokeStyle = color; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(cx, y(d.high)); ctx.lineTo(cx, y(d.low)); ctx.stroke();

        const top = y(Math.max(d.open, d.close));
        const bot = y(Math.min(d.open, d.close));
        const h = Math.max(bot - top, 1);
        if (isUp) {{
            ctx.strokeStyle = color; ctx.lineWidth = 1;
            ctx.strokeRect(cx - bodyW/2, top, bodyW, h);
        }} else {{
            ctx.fillStyle = color;
            ctx.fillRect(cx - bodyW/2, top, bodyW, h);
        }}
    }});

    // MA lines
    function drawLine(key, color) {{
        ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.beginPath();
        let started = false;
        data.forEach((d, i) => {{
            if (d[key] != null) {{
                if (!started) {{ ctx.moveTo(x(i), y(d[key])); started = true; }}
                else ctx.lineTo(x(i), y(d[key]));
            }}
        }});
        ctx.stroke();
    }}
    if (data[0].ma5 != null) drawLine("ma5", "#f39c12");
    if (data[0].ma20 != null || data.some(d => d.ma20 != null)) drawLine("ma20", "#3498db");

    // Date labels
    ctx.fillStyle = "#8b949e"; ctx.font = "11px sans-serif"; ctx.textAlign = "center";
    const step = Math.max(Math.floor(data.length / 8), 1);
    data.forEach((d, i) => {{
        if (i % step === 0) ctx.fillText(d.date, x(i), H - 8);
    }});
}}
</script>
</body>
</html>'''
