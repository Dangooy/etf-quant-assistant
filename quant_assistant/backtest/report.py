import json
import shutil
import datetime
from pathlib import Path
from typing import List, Optional

from ..config import REPORT_DIR
from .models import BacktestResult

_ECHARTS_ASSET = Path(__file__).resolve().parent / "assets" / "echarts.min.js"


def _ensure_echarts(report_dir: Path):
    """把打包在项目内的 echarts.min.js 复制到报告目录，报告离线也能渲染图表"""
    target = report_dir / "echarts.min.js"
    if _ECHARTS_ASSET.exists() and not target.exists():
        shutil.copy2(_ECHARTS_ASSET, target)


def generate_backtest_report(result: BacktestResult,
                             output_path: Optional[Path] = None) -> Path:
    safe_name = result.strategy_name.replace("/", "-").replace("(", "").replace(")", "")
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = output_path or REPORT_DIR / f"backtest_{result.code}_{safe_name}_{ts}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_echarts(output_path.parent)

    m = result.metrics
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    dates_json = []
    closes_json = []
    equity_json = []
    benchmark_json = []

    initial_close = None
    for snap in result.daily_snapshots:
        d = snap.date
        date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
        dates_json.append(date_str)
        closes_json.append(round(snap.close_price, 2))
        equity_json.append(round(snap.total_equity, 2))
        if initial_close is None:
            initial_close = snap.close_price
        bm = result.config.initial_capital * (snap.close_price / initial_close)
        benchmark_json.append(round(bm, 2))

    buy_points = []
    sell_points = []
    for t in result.trades:
        d = t.date
        date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
        if t.direction == "BUY":
            buy_points.append({"date": date_str, "price": round(t.price, 2)})
        else:
            sell_points.append({"date": date_str, "price": round(t.price, 2)})

    pairs_json = []
    for p in m.get("trade_pairs", []):
        pairs_json.append({
            "buy_date": p["buy_date"].strftime("%Y-%m-%d") if hasattr(p["buy_date"], "strftime") else str(p["buy_date"]),
            "sell_date": p["sell_date"].strftime("%Y-%m-%d") if hasattr(p["sell_date"], "strftime") else str(p["sell_date"]),
            "buy_price": round(p["buy_price"], 4),
            "sell_price": round(p["sell_price"], 4),
            "shares": p["shares"],
            "pnl": round(p["pnl"], 2),
            "pnl_pct": round(p["pnl_pct"] * 100, 2),
            "holding_days": p["holding_days"],
        })

    drawdown_json = _calc_drawdown_series(equity_json)

    ret_color = "#2ecc71" if m["total_return"] >= 0 else "#e74c3c"
    ann_color = "#2ecc71" if m["annual_return"] >= 0 else "#e74c3c"

    sharpe = m["sharpe_ratio"]
    sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "N/A"
    sharpe_color = "#2ecc71" if (sharpe or 0) > 0 else "#e74c3c"
    pf = m["profit_factor"]
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"
    ann_label = "年化收益率" + ("（区间过短仅供参考）" if m.get("trading_days", 0) < 60 else "")

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>回测报告 - {result.name}({result.code}) - {result.strategy_name}</title>
<script src="echarts.min.js"></script>
<script>if (typeof echarts === 'undefined') document.write('<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"><\\/script>');</script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #0a0e17; color: #e0e0e0; min-height: 100vh; }}
.header {{ background: linear-gradient(135deg, #1a1f2e 0%, #0d1117 100%); padding: 20px 30px; border-bottom: 1px solid #1e2d3d; display: flex; justify-content: space-between; align-items: center; }}
.header h1 {{ font-size: 20px; color: #fff; }}
.header .sub {{ color: #8b949e; font-size: 13px; margin-top: 4px; }}
.header .time {{ color: #8b949e; font-size: 13px; text-align: right; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
.summary-cards {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 24px; }}
.card {{ background: #161b22; border: 1px solid #21262d; border-radius: 10px; padding: 16px; text-align: center; }}
.card .label {{ color: #8b949e; font-size: 12px; margin-bottom: 6px; }}
.card .value {{ font-size: 22px; font-weight: 700; }}
.section {{ background: #161b22; border: 1px solid #21262d; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}
.section h2 {{ font-size: 15px; color: #c9d1d9; margin-bottom: 14px; padding-bottom: 8px; border-bottom: 1px solid #21262d; }}
.chart-box {{ width: 100%; height: 400px; }}
.chart-box-sm {{ width: 100%; height: 250px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ text-align: left; padding: 8px 10px; color: #8b949e; font-weight: 500; border-bottom: 1px solid #21262d; }}
td {{ padding: 8px 10px; border-bottom: 1px solid #1c2333; }}
tr:hover {{ background: #1c2333; }}
.pos {{ color: #2ecc71; }}
.neg {{ color: #e74c3c; }}
@media (max-width: 900px) {{ .summary-cards {{ grid-template-columns: repeat(3, 1fr); }} }}
@media (max-width: 500px) {{ .summary-cards {{ grid-template-columns: repeat(2, 1fr); }} }}
</style>
</head>
<body>

<div class="header">
    <div>
        <h1>策略回测报告</h1>
        <div class="sub">{result.name}({result.code}) &mdash; {result.strategy_name}</div>
    </div>
    <div class="time">
        <div>{result.start_date} ~ {result.end_date}</div>
        <div>生成于 {now_str}</div>
    </div>
</div>

<div class="container">

<div class="summary-cards">
    <div class="card">
        <div class="label">总收益率</div>
        <div class="value" style="color:{ret_color}">{m["total_return"]:+.2%}</div>
    </div>
    <div class="card">
        <div class="label">{ann_label}</div>
        <div class="value" style="color:{ann_color}">{m["annual_return"]:+.2%}</div>
    </div>
    <div class="card">
        <div class="label">最大回撤</div>
        <div class="value" style="color:#e74c3c">{m["max_drawdown"]:.2%}</div>
    </div>
    <div class="card">
        <div class="label">夏普比率</div>
        <div class="value" style="color:{sharpe_color}">{sharpe_str}</div>
    </div>
    <div class="card">
        <div class="label">胜率</div>
        <div class="value" style="color:#3498db">{m["win_rate"]:.1%}</div>
    </div>
    <div class="card">
        <div class="label">交易次数</div>
        <div class="value" style="color:#f39c12">{m["total_trades"]}</div>
    </div>
</div>

<div class="section">
    <h2>价格走势与买卖点</h2>
    <div id="chart-price" class="chart-box"></div>
</div>

<div class="section">
    <h2>资金曲线</h2>
    <div id="chart-equity" class="chart-box"></div>
</div>

<div class="section">
    <h2>回撤曲线</h2>
    <div id="chart-drawdown" class="chart-box-sm"></div>
</div>

<div class="section">
    <h2>交易明细 ({m["total_trades"]} 笔配对)</h2>
    <table>
        <thead>
            <tr>
                <th>买入日期</th><th>买入价</th><th>卖出日期</th><th>卖出价</th>
                <th>股数</th><th>盈亏</th><th>收益率</th><th>持仓天数</th>
            </tr>
        </thead>
        <tbody id="pairs-table"></tbody>
    </table>
</div>

<div class="section" style="font-size:13px;color:#8b949e;">
    <h2>费用汇总</h2>
    <p>初始资金: ¥{m["initial_capital"]:,.0f} &nbsp;|&nbsp;
       最终权益: ¥{m["final_equity"]:,.0f} &nbsp;|&nbsp;
       总佣金: ¥{m["total_commission"]:.2f} &nbsp;|&nbsp;
       总印花税: ¥{m["total_stamp_tax"]:.2f} &nbsp;|&nbsp;
       盈亏比: {pf_str} &nbsp;|&nbsp;
       平均持仓: {m["avg_holding_days"]:.0f}天（自然日）</p>
    <p style="margin-top:8px">成交假设: 信号日次日开盘价成交（含滑点 {result.config.slippage_pct:.2%}），一字涨跌停顺延；行情为前复权(qfq)，除权后历史价格会整体漂移，不同日期跑同一回测结果可能不同。</p>
</div>

</div>

<script>
const dates = {json.dumps(dates_json)};
const closes = {json.dumps(closes_json)};
const equity = {json.dumps(equity_json)};
const benchmark = {json.dumps(benchmark_json)};
const drawdown = {json.dumps(drawdown_json)};
const buyPoints = {json.dumps(buy_points)};
const sellPoints = {json.dumps(sell_points)};
const pairs = {json.dumps(pairs_json, ensure_ascii=False)};

const darkTheme = {{
    backgroundColor: '#161b22',
    textStyle: {{ color: '#8b949e' }},
    legend: {{ textStyle: {{ color: '#c9d1d9' }} }},
}};

// Price chart
const priceChart = echarts.init(document.getElementById('chart-price'), null, {{renderer:'canvas'}});
priceChart.setOption({{
    ...darkTheme,
    tooltip: {{ trigger: 'axis' }},
    legend: {{ ...darkTheme.legend, data: ['收盘价', '买入', '卖出'], top: 10 }},
    grid: {{ left: 60, right: 40, top: 50, bottom: 40 }},
    xAxis: {{ type: 'category', data: dates, axisLabel: {{ color: '#8b949e' }}, axisLine: {{ lineStyle: {{ color: '#21262d' }} }} }},
    yAxis: {{ type: 'value', scale: true, axisLabel: {{ color: '#8b949e' }}, splitLine: {{ lineStyle: {{ color: '#21262d' }} }} }},
    dataZoom: [{{ type: 'inside', start: 0, end: 100 }}, {{ type: 'slider', bottom: 8, height: 20 }}],
    series: [
        {{
            name: '收盘价', type: 'line', data: closes, symbol: 'none',
            lineStyle: {{ color: '#3498db', width: 1.5 }},
            areaStyle: {{ color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                {{ offset: 0, color: 'rgba(52,152,219,0.15)' }}, {{ offset: 1, color: 'rgba(52,152,219,0)' }}
            ]) }},
        }},
        {{
            name: '买入', type: 'scatter', symbol: 'triangle', symbolSize: 14,
            itemStyle: {{ color: '#e74c3c' }},
            data: buyPoints.map(p => [p.date, p.price]),
        }},
        {{
            name: '卖出', type: 'scatter', symbol: 'pin', symbolSize: 16,
            itemStyle: {{ color: '#2ecc71' }},
            data: sellPoints.map(p => [p.date, p.price]),
        }},
    ]
}});

// Equity chart
const eqChart = echarts.init(document.getElementById('chart-equity'), null, {{renderer:'canvas'}});
eqChart.setOption({{
    ...darkTheme,
    tooltip: {{ trigger: 'axis', formatter: function(ps) {{
        let s = ps[0].axisValue + '<br/>';
        ps.forEach(p => {{ s += p.marker + p.seriesName + ': ¥' + p.data.toLocaleString() + '<br/>'; }});
        return s;
    }} }},
    legend: {{ ...darkTheme.legend, data: ['策略净值', '买入持有'], top: 10 }},
    grid: {{ left: 80, right: 40, top: 50, bottom: 40 }},
    xAxis: {{ type: 'category', data: dates, axisLabel: {{ color: '#8b949e' }}, axisLine: {{ lineStyle: {{ color: '#21262d' }} }} }},
    yAxis: {{ type: 'value', scale: true, axisLabel: {{ color: '#8b949e', formatter: v => '¥' + (v/1000).toFixed(0) + 'k' }}, splitLine: {{ lineStyle: {{ color: '#21262d' }} }} }},
    dataZoom: [{{ type: 'inside' }}, {{ type: 'slider', bottom: 8, height: 20 }}],
    series: [
        {{
            name: '策略净值', type: 'line', data: equity, symbol: 'none',
            lineStyle: {{ color: '#f39c12', width: 2 }},
            areaStyle: {{ color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                {{ offset: 0, color: 'rgba(243,156,18,0.15)' }}, {{ offset: 1, color: 'rgba(243,156,18,0)' }}
            ]) }},
        }},
        {{
            name: '买入持有', type: 'line', data: benchmark, symbol: 'none',
            lineStyle: {{ color: '#8b949e', width: 1.5, type: 'dashed' }},
        }},
    ]
}});

// Drawdown chart
const ddChart = echarts.init(document.getElementById('chart-drawdown'), null, {{renderer:'canvas'}});
ddChart.setOption({{
    ...darkTheme,
    tooltip: {{ trigger: 'axis', formatter: ps => ps[0].axisValue + '<br/>回撤: ' + (ps[0].data * 100).toFixed(2) + '%' }},
    grid: {{ left: 60, right: 40, top: 20, bottom: 40 }},
    xAxis: {{ type: 'category', data: dates, axisLabel: {{ color: '#8b949e' }}, axisLine: {{ lineStyle: {{ color: '#21262d' }} }} }},
    yAxis: {{ type: 'value', axisLabel: {{ color: '#8b949e', formatter: v => (v*100).toFixed(0) + '%' }}, splitLine: {{ lineStyle: {{ color: '#21262d' }} }}, inverse: true }},
    dataZoom: [{{ type: 'inside' }}],
    series: [{{
        type: 'line', data: drawdown, symbol: 'none',
        lineStyle: {{ color: '#e74c3c', width: 1 }},
        areaStyle: {{ color: 'rgba(231,76,60,0.2)' }},
    }}]
}});

// Pairs table
const tbody = document.getElementById('pairs-table');
pairs.forEach(p => {{
    const cls = p.pnl >= 0 ? 'pos' : 'neg';
    const sign = p.pnl >= 0 ? '+' : '';
    tbody.innerHTML += `<tr>
        <td>${{p.buy_date}}</td><td>${{p.buy_price.toFixed(2)}}</td>
        <td>${{p.sell_date}}</td><td>${{p.sell_price.toFixed(2)}}</td>
        <td>${{p.shares}}</td>
        <td class="${{cls}}">${{sign}}${{p.pnl.toFixed(2)}}</td>
        <td class="${{cls}}">${{sign}}${{p.pnl_pct.toFixed(2)}}%</td>
        <td>${{p.holding_days}}</td>
    </tr>`;
}});

window.addEventListener('resize', () => {{
    priceChart.resize();
    eqChart.resize();
    ddChart.resize();
}});
</script>
</body>
</html>'''

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def generate_portfolio_backtest_report(results: List[object],
                                       output_path: Optional[Path] = None) -> Path:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = output_path or REPORT_DIR / f"backtest_portfolio_{ts}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_echarts(output_path.parent)

    full = results[0]
    dates = [row["date"].strftime("%Y-%m-%d") for row in full.equity_curve]
    series = []
    for result in results:
        series.append({
            "name": result.name,
            "data": [round(row["equity"], 2) for row in result.equity_curve],
        })
    benchmark = [round(row["benchmark"], 2) if row["benchmark"] is not None else None
                 for row in full.equity_curve]

    summary_rows = ""
    for result in results:
        m = result.metrics
        calmar = m.get("calmar_ratio")
        calmar_text = "N/A" if calmar is None else f"{calmar:.2f}"
        dd_2018 = _portfolio_annual_drawdown_text(result, 2018)
        dd_2022 = _portfolio_annual_drawdown_text(result, 2022)
        summary_rows += (
            f"<tr><td>{result.name}</td>"
            f"<td>{m.get('annual_return', 0):.2%}</td>"
            f"<td>{m.get('max_drawdown', 0):.2%}</td>"
            f"<td>{calmar_text}</td>"
            f"<td>{dd_2018[0]}</td>"
            f"<td>{dd_2018[1]}</td>"
            f"<td>{dd_2022[0]}</td>"
            f"<td>{dd_2022[1]}</td></tr>"
        )

    annual_rows = ""
    full_by_year = {row["year"]: row for row in full.annual_returns}
    for year in sorted(full_by_year):
        row = full_by_year[year]
        bm = row["benchmark_return"]
        excess = row["excess_return"]
        strategy_dd = row["strategy_max_drawdown"]
        bm_dd = row["benchmark_max_drawdown"]
        annual_rows += (
            f"<tr><td>{year}</td>"
            f"<td>{row['strategy_return']:.2%}</td>"
            f"<td>{strategy_dd:.2%}</td>"
            f"<td>{bm:.2%}</td>"
            f"<td>{bm_dd:.2%}</td>"
            f"<td>{excess:.2%}</td></tr>"
            if bm is not None and excess is not None and bm_dd is not None
            else f"<tr><td>{year}</td><td>{row['strategy_return']:.2%}</td><td>{strategy_dd:.2%}</td><td>N/A</td><td>N/A</td><td>N/A</td></tr>"
        )

    notes = "".join(f"<li>{note}</li>" for note in full.notes)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>组合级回测报告</title>
<script src="echarts.min.js"></script>
<style>
body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; background:#0a0e17; color:#e0e0e0; margin:0; }}
.header {{ padding:20px 30px; background:#111827; border-bottom:1px solid #243044; display:flex; justify-content:space-between; }}
.container {{ max-width:1400px; margin:0 auto; padding:20px; }}
.section {{ background:#161b22; border:1px solid #21262d; border-radius:10px; padding:18px; margin-bottom:18px; }}
h1 {{ font-size:20px; margin:0; }} h2 {{ font-size:15px; color:#c9d1d9; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }} th,td {{ padding:8px 10px; border-bottom:1px solid #273244; text-align:left; }}
th {{ color:#8b949e; }} .chart {{ height:420px; }}
li {{ margin:6px 0; color:#aab4c0; }}
</style>
</head>
<body>
<div class="header">
  <div><h1>ETF 组合级回测报告</h1><div>区间：{full.start_date} ~ {full.end_date}</div></div>
  <div>{now_str}</div>
</div>
<div class="container">
  <div class="section">
    <h2>口径说明</h2>
    <ul>{notes}</ul>
  </div>
  <div class="section">
    <h2>四组对照</h2>
    <table><thead><tr><th>方案</th><th>年化</th><th>最大回撤</th><th>卡玛</th><th>2018策略回撤</th><th>2018沪深300回撤</th><th>2022策略回撤</th><th>2022沪深300回撤</th></tr></thead>
    <tbody>{summary_rows}</tbody></table>
  </div>
  <div class="section">
    <h2>资金曲线</h2>
    <div id="equity" class="chart"></div>
  </div>
  <div class="section">
    <h2>完整规则年度收益 vs 沪深300ETF</h2>
    <table><thead><tr><th>年份</th><th>完整规则</th><th>策略回撤</th><th>沪深300ETF</th><th>沪深300回撤</th><th>超额</th></tr></thead>
    <tbody>{annual_rows}</tbody></table>
  </div>
</div>
<script>
const dates = {json.dumps(dates)};
const variantSeries = {json.dumps(series, ensure_ascii=False)};
const benchmark = {json.dumps(benchmark)};
const chart = echarts.init(document.getElementById('equity'));
chart.setOption({{
  backgroundColor:'#161b22',
  tooltip: {{ trigger:'axis' }},
  legend: {{ textStyle:{{color:'#c9d1d9'}}, data: variantSeries.map(s => s.name).concat(['沪深300ETF']) }},
  grid: {{ left:70, right:30, top:50, bottom:50 }},
  xAxis: {{ type:'category', data:dates, axisLabel:{{color:'#8b949e'}} }},
  yAxis: {{ type:'value', scale:true, axisLabel:{{color:'#8b949e'}}, splitLine:{{lineStyle:{{color:'#273244'}}}} }},
  dataZoom: [{{type:'inside'}}, {{type:'slider', bottom:10, height:20}}],
  series: variantSeries.map(s => ({{name:s.name, type:'line', symbol:'none', data:s.data}})).concat([
    {{name:'沪深300ETF', type:'line', symbol:'none', data:benchmark, lineStyle:{{type:'dashed'}}}}
  ])
}});
</script>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def _portfolio_annual_drawdown_text(result, year):
    for row in result.annual_returns:
        if row["year"] == year:
            strategy_dd = f"{row['strategy_max_drawdown']:.2%}"
            benchmark_dd = row["benchmark_max_drawdown"]
            return strategy_dd, "N/A" if benchmark_dd is None else f"{benchmark_dd:.2%}"
    return "N/A", "N/A"


def _calc_drawdown_series(equity_list):
    dd = []
    peak = equity_list[0] if equity_list else 1
    for eq in equity_list:
        if eq > peak:
            peak = eq
        dd.append(round((peak - eq) / peak, 6) if peak > 0 else 0)
    return dd
