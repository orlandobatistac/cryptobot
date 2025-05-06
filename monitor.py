import logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger().setLevel(logging.WARNING)

from flask import Flask, render_template_string, jsonify, Response
import os
import sys
from datetime import datetime
from decimal import Decimal
import krakenex
import sqlite3
import psutil
import platform
import time
import pandas as pd
import plotly.graph_objs as go
import json

# Basic configuration
app = Flask(__name__)

API_KEY = os.getenv('KRAKEN_API_KEY')
API_SECRET = os.getenv('KRAKEN_API_SECRET')

k = krakenex.API(key=API_KEY, secret=API_SECRET)
PAIR = "XXBTZUSD"

SERVER_START = time.time()

# Functions to get metrics

def get_account_balance(asset="ZUSD"):
    try:
        resp = k.query_private('Balance')
        if resp.get('error'):
            return None
        return float(resp['result'].get(asset, 0))
    except Exception:
        return None

def get_asset_balance(asset="XXBT"):
    try:
        resp = k.query_private('Balance')
        if resp.get('error'):
            return None
        return float(resp['result'].get(asset, 0))
    except Exception:
        return None

def get_realtime_price(pair):
    try:
        resp = k.query_public('Ticker', {'pair': pair})
        if resp.get('error'):
            return None
        ticker = resp['result'][list(resp['result'].keys())[0]]
        return float(ticker['c'][0])
    except Exception:
        return None

def get_position():
    # Example: no open position
    return None

def get_live_trading_metrics():
    uptime = int(time.time() - SERVER_START)
    return {
        'total_profit': 0.0,
        'pl_unrealized': 0.0,
        'last_trade': 'N/A',
        'win_rate': 0,
        'uptime': uptime,
        'last_5_trades': []
    }

# --- LIVE_PAPER METRICS ---
def get_live_paper_metrics():
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    initial_capital = config.get('general', {}).get('initial_capital', 10000)
    db_path = os.path.join(os.path.dirname(__file__), 'paper_trades.db')
    metrics = {
        'total_trades': 0,
        'total_profit': 0.0,
        'win_rate': 0.0,
        'last_trade': None,
        'balance': 0.0,
        'open_position': None,
        'pl_unrealized': 0.0,
        'uptime': 0,
        'last_5_trades': []
    }
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(SUM(profit),0) FROM trades")
        metrics['total_trades'], metrics['total_profit'] = c.fetchone()
        c.execute("SELECT COUNT(*) FROM trades WHERE profit>0")
        wins = c.fetchone()[0]
        metrics['win_rate'] = (wins/metrics['total_trades']*100) if metrics['total_trades'] else 0
        c.execute("SELECT type, price, volume, timestamp, profit FROM trades ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
        if row:
            metrics['last_trade'] = {
                'type': row[0], 'price': row[1], 'volume': row[2], 'time': row[3], 'profit': row[4]
            }
        c.execute("SELECT balance FROM trades ORDER BY id DESC LIMIT 1")
        last_balance = c.fetchone()
        if last_balance:
            metrics['balance'] = last_balance[0]
        # Open position
        c.execute("SELECT type, price, volume, timestamp FROM trades WHERE type='buy' ORDER BY id DESC LIMIT 1")
        buy = c.fetchone()
        if buy:
            c.execute("SELECT id FROM trades WHERE type='sell' AND id>(SELECT id FROM trades WHERE type='buy' ORDER BY id DESC LIMIT 1) ORDER BY id ASC LIMIT 1")
            sell = c.fetchone()
            if not sell:
                metrics['open_position'] = {
                    'entry_price': buy[1],
                    'volume': buy[2],
                    'entry_time': buy[3]
                }
        # Unrealized P/L
        if metrics['open_position']:
            price = get_realtime_price(PAIR)
            if price:
                metrics['pl_unrealized'] = (price - metrics['open_position']['entry_price']) * metrics['open_position']['volume']
        # Uptime: since first trade
        c.execute("SELECT timestamp FROM trades ORDER BY id ASC LIMIT 1")
        first = c.fetchone()
        if first:
            t0 = datetime.fromisoformat(first[0])
            metrics['uptime'] = (datetime.utcnow() - t0).total_seconds()
        # Last 5 trades
        c.execute("SELECT type, price, volume, timestamp, profit FROM trades ORDER BY id DESC LIMIT 5")
        rows = c.fetchall()
        metrics['last_5_trades'] = [
            {'type': r[0], 'price': r[1], 'volume': r[2], 'time': r[3], 'profit': r[4]} for r in rows
        ]
        conn.close()
    except Exception:
        pass
    # Si no hay trades y el balance es 0, mostrar el initial_capital
    if metrics['total_trades'] == 0 and metrics['balance'] == 0:
        metrics['balance'] = initial_capital
    return metrics

# --- SYSTEM METRICS ---
def get_server_metrics():
    disk_percent = psutil.disk_usage('/').percent
    return {
        'flask_uptime': int(time.time() - SERVER_START),
        'cpu_percent': psutil.cpu_percent(),
        'ram_percent': psutil.virtual_memory().percent,
        'disk_percent': disk_percent,
        'platform': platform.platform(),
        'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

@app.route("/metrics")
def metrics_api():
    usd_balance = get_account_balance() or 0
    price = get_realtime_price(PAIR) or 0
    position = get_position()
    pl = 0
    if position and price:
        pl = (price - position['entry_price']) * position['volume']
    paper = get_live_paper_metrics()
    server = get_server_metrics()
    live_trading = get_live_trading_metrics()
    return jsonify({
        'usd_balance': usd_balance,
        'position': position,
        'pl': pl,
        'paper': paper,
        'server': server,
        'live_trading': live_trading,
        'now': server['now']
    })

@app.route("/logs")
def logs_api():
    log_path = os.path.join(os.path.dirname(__file__), 'debug.log')
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        # Return last 20 lines
        last_lines = lines[-20:]
        return jsonify({'logs': ''.join(last_lines)})
    except Exception as e:
        return jsonify({'logs': f'Error reading log file: {e}'})

@app.route("/btc_chart_data")
def btc_chart_data():
    try:
        df = pd.read_parquet(os.path.join("data", "ohlc_data_60min_all_years.parquet"))
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        df.set_index('Timestamp', inplace=True)
        df_1d = df.resample('1D', closed='left', label='left').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        })
        df_1d = df_1d.dropna()
        df_1d['EMA9'] = df_1d['Close'].ewm(span=9, adjust=False).mean()
        df_1d['EMA21'] = df_1d['Close'].ewm(span=21, adjust=False).mean()
        # Current price
        last_close = float(df_1d['Close'].iloc[-1]) if not df_1d.empty else None
        now_price = get_realtime_price(PAIR)
        # --- Buy/Sell signals ---
        buy_signals = []
        sell_signals = []
        try:
            db_path = os.path.join(os.path.dirname(__file__), 'paper_trades.db')
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT type, price, timestamp FROM trades WHERE type IN ('buy', 'sell') ORDER BY timestamp ASC")
            for ttype, price, ts in c.fetchall():
                dt = pd.to_datetime(ts).strftime('%Y-%m-%d')
                if ttype == 'buy':
                    buy_signals.append({'date': dt, 'price': price})
                elif ttype == 'sell':
                    sell_signals.append({'date': dt, 'price': price})
            conn.close()
        except Exception as e:
            pass
        # Serialize data for Plotly
        data = {
            'x': df_1d.index.strftime('%Y-%m-%d').tolist(),
            'open': df_1d['Open'].tolist(),
            'high': df_1d['High'].tolist(),
            'low': df_1d['Low'].tolist(),
            'close': df_1d['Close'].tolist(),
            'volume': df_1d['Volume'].tolist(),
            'ema9': df_1d['EMA9'].tolist(),
            'ema21': df_1d['EMA21'].tolist(),
            'now_price': now_price,
            'last_close': last_close,
            'buy_signals': buy_signals,
            'sell_signals': sell_signals
        }
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route("/btc_chart")
def btc_chart():
    return '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>BTC/USDT Chart</title>
        <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
        <style>
            html, body {height: 100%; margin: 0; padding: 0; background: #111111;}
            #chart {position: absolute; top: 0; left: 0; right: 0; bottom: 0; width: 100vw; height: 100vh; background: #111111;}
        </style>
    </head>
    <body>
        <div id="chart"></div>
        <script>
        function getIframeHeight() {
            try {
                if (window.parent !== window && window.frameElement) {
                    return window.frameElement.clientHeight;
                }
            } catch (e) {}
            return window.innerHeight;
        }
        async function fetchDataAndPlot() {
            const res = await fetch('/btc_chart_data');
            const data = await res.json();
            if(data.error) {
                document.getElementById('chart').innerHTML = '<div style="color:red">'+data.error+'</div>';
                return;
            }
            const traceCandle = {
                x: data.x,
                open: data.open,
                high: data.high,
                low: data.low,
                close: data.close,
                type: 'candlestick',
                name: 'Candles',
                increasing: {line: {color: '#26a69a'}},
                decreasing: {line: {color: '#ef5350'}},
                showlegend: false
            };
            const traceEMA9 = {
                x: data.x,
                y: data.ema9,
                type: 'scatter',
                mode: 'lines',
                name: 'EMA 9',
                line: {color: '#ffd600', width: 1.5}
            };
            const traceEMA21 = {
                x: data.x,
                y: data.ema21,
                type: 'scatter',
                mode: 'lines',
                name: 'EMA 21',
                line: {color: '#00b0ff', width: 1.5}
            };
            const traceVol = {
                x: data.x,
                y: data.volume,
                type: 'bar',
                name: 'Volume',
                marker: {color: '#757575'},
                yaxis: 'y2',
                opacity: 0.3
            };
            const traceBuy = {
                x: data.buy_signals.map(s => s.date),
                y: data.buy_signals.map(s => s.price),
                mode: 'markers',
                name: 'BUY',
                marker: {
                    symbol: 'arrow-up',
                    color: '#00e676',
                    size: 18,
                    line: {width: 2, color: '#111'}
                },
                type: 'scatter',
                hovertemplate: 'BUY<br>Date: %{x}<br>Price: $%{y:.2f}<extra></extra>'
            };
            const traceSell = {
                x: data.sell_signals.map(s => s.date),
                y: data.sell_signals.map(s => s.price),
                mode: 'markers',
                name: 'SELL',
                marker: {
                    symbol: 'arrow-down',
                    color: '#ff1744',
                    size: 18,
                    line: {width: 2, color: '#111'}
                },
                type: 'scatter',
                hovertemplate: 'SELL<br>Date: %{x}<br>Price: $%{y:.2f}<extra></extra>'
            };
            let shapes = [];
            let annotations = [];
            if(data.now_price) {
                shapes.push({
                    type: 'line',
                    xref: 'paper',
                    x0: 0, x1: 1,
                    y0: data.now_price, y1: data.now_price,
                    line: {color: '#ff1744', width: 2, dash: 'dot'},
                });
                annotations.push({
                    xref: 'paper',
                    x: 1.01,
                    y: data.now_price,
                    xanchor: 'left',
                    yanchor: 'middle',
                    text: '$' + data.now_price.toLocaleString(undefined, {maximumFractionDigits:2}),
                    font: {color: '#ff1744', size: 14, family: 'monospace'},
                    showarrow: false,
                    bgcolor: '#181a1b',
                    bordercolor: '#ff1744',
                    borderpad: 4,
                    borderwidth: 2
                });
            }
            let range = undefined;
            if(data.x && data.x.length > 400) {
                range = [data.x[data.x.length-400], data.x[data.x.length-1]];
            }
            const layout = {
                plot_bgcolor: '#111111',
                paper_bgcolor: '#111111',
                autosize: true,
                xaxis: {
                    rangeslider: {visible: false},
                    color: '#e0e0e0',
                    range: range,
                    fixedrange: false,
                    automargin: true
                },
                yaxis: {title: 'Price', side: 'right', color: '#e0e0e0', tickformat: ',.0f', fixedrange: false, automargin: true},
                yaxis2: {
                    title: 'Volume',
                    overlaying: 'y',
                    side: 'left',
                    showgrid: false,
                    position: 0.05,
                    anchor: 'x',
                    layer: 'below traces',
                    color: '#e0e0e0',
                    tickformat: ',.0f',
                    fixedrange: false,
                    automargin: true
                },
                template: 'plotly_dark',
                margin: {l:40, r:40, t:40, b:40},
                height: getIframeHeight(),
                legend: {orientation: 'h', yanchor: 'bottom', y: 1.02, xanchor: 'right', x: 1, font: {color: '#e0e0e0'}},
                title: 'BTC/USDT 1D - Updated: ' + new Date().toLocaleString(),
                shapes: shapes,
                annotations: annotations
            };
            Plotly.newPlot('chart', [traceCandle, traceEMA9, traceEMA21, traceVol, traceBuy, traceSell], layout, {responsive:true});
        }
        fetchDataAndPlot();
        setInterval(fetchDataAndPlot, 5000);
        window.addEventListener('resize', () => {
            Plotly.Plots.resize('chart');
        });
        </script>
    </body>
    </html>
    '''

@app.route("/")
def dashboard():
    usd_balance = get_account_balance() or 0
    price = get_realtime_price(PAIR) or 0
    position = get_position()
    pl = 0
    if position and price:
        pl = (price - position['entry_price']) * position['volume']
    # Live paper metrics
    paper = get_live_paper_metrics()
    # Server metrics
    server = get_server_metrics()
    return render_template_string(TEMPLATE, 
        usd_balance=usd_balance, position=position, pl=pl,
        paper=paper, server=server, now=server['now']
    )

TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CryptoBot Monitor</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #181a1b; color: #f3f6fa; }
        .card { background: #23272f; color: #f3f6fa; border: none; }
        .table-dark { --bs-table-bg: #23272f; }
        .navbar { background: linear-gradient(90deg, #181a1b 0%, #23272f 100%); border-bottom: 1px solid #2d323c; }
        .section-title {
            margin-top: 2rem;
            margin-bottom: 1rem;
            font-size: 1.7rem;
            color: #fff;
            font-weight: 900;
            letter-spacing: 1px;
            text-shadow: 0 2px 12px #007acc99, 0 1px 8px #000;
            text-transform: uppercase;
            display: flex;
            align-items: center;
            gap: 0.5em;
        }
        .section-title .icon {
            font-size: 1.5em;
            margin-right: 0.3em;
        }
        .card-title {
            color: #7fd7ff;
            font-weight: bold;
            letter-spacing: 0.5px;
            font-size: 1.2rem;
            text-shadow: 0 1px 8px #007acc44;
            display: flex;
            align-items: center;
            gap: 0.4em;
        }
        .card-title .icon {
            font-size: 1.1em;
        }
        .display-6 { font-weight: bold; color: #fff; }
        .text-success { color: #4ade80 !important; }
        .text-danger { color: #f87171 !important; }
        .text-secondary { color: #a5b4fc !important; }
        .badge.bg-success { background: linear-gradient(90deg, #4ade80 0%, #256d4f 100%); color: #181a1b; }
        pre { background: #181a1b; color: #7fd7ff; border: 1px solid #23272f; }
        .card.shadow { box-shadow: 0 0 16px 0 #7fd7ff22, 0 2px 4px 0 #000a; }
        .navbar-brand { color: #7fd7ff !important; font-weight: bold; letter-spacing: 1px; }
        .highlight { color: #7fd7ff; font-weight: bold; }
        .card-body { border-radius: 0.5rem; }
        .card { border-radius: 1rem; }
        .table-dark th, .table-dark td { border-color: #2d323c; }
        .card-title, .section-title { text-shadow: 0 2px 8px #181a1b; }
        .card .card-title { font-size: 1.1rem; }
        .card .card-text { font-size: 1.3rem; }
        .badge.bg-success { font-size: 1em; }
        .row.g-4 { row-gap: 1.5rem; }
        .table-dark { color: #f3f6fa; }
        .table-dark tr { background: #23272f; }
        .table-dark th { color: #7fd7ff; font-size: 1.1em; font-weight: 700; }
        .table-dark td { color: #f3f6fa; }
        .alert-danger { background: #2d323c; color: #f87171; border: none; }
        .icon-btc { color: #f7931a; }
        .icon-usd { color: #4ade80; }
        .icon-profit { color: #4ade80; }
        .icon-loss { color: #f87171; }
        .icon-trade { color: #7fd7ff; }
        .icon-server { color: #a5b4fc; }
        .icon-paper { color: #ffd700; }
        .icon-logs { color: #ffb300; }
    </style>
</head>
<body>
<nav class="navbar navbar-dark">
  <div class="container-fluid">
    <span class="navbar-brand mb-0 h1">CryptoBot Dashboard</span>
    <span class="text-secondary" id="now">{{ now }}</span>
  </div>
</nav>
<div class="container py-4">
  <div class="row">
    <div class="col">
      <div class="card shadow mb-4">
        <div class="card-body">
          <iframe src="/btc_chart" width="100%" height="750" style="border:none;background:#181a1b;"></iframe>
        </div>
      </div>
    </div>
  </div>
</div>
<div class="container py-4" id="metrics-root">
  <!-- All metrics content will be rendered here by JS -->
</div>
<div class="container py-4" id="logs-root">
  <!-- Logs will be rendered here by JS -->
</div>
<script>
function renderTradeTable(trades) {
  if (!trades || trades.length === 0) return '<p class="text-secondary">No recent trades</p>';
  let html = '<table class="table table-dark table-striped"><thead><tr><th>Type</th><th>Price</th><th>Volume</th><th>Time</th><th>P/L</th></tr></thead><tbody>';
  for (const t of trades) {
    html += `<tr>
      <td>${t.type ? (t.type.toLowerCase() === 'buy' ? '<span class="icon icon-trade">&#128200;</span> ' : '<span class="icon icon-trade">&#128201;</span> ') + t.type.toUpperCase() : ''}</td>
      <td>$${Number(t.price).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</td>
      <td>${t.volume}</td>
      <td>${t.time ? t.time.replace('T',' ').slice(0,19) : ''}</td>
      <td>${t.profit !== undefined ? (t.profit >= 0 ? `<span class='icon icon-profit'>&#x1F4B0;</span> <span class='text-success'>$${Number(t.profit).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</span>` : `<span class='icon icon-loss'>&#x1F4B8;</span> <span class='text-danger'>$${Number(t.profit).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</span>`) : ''}</td>
    </tr>`;
  }
  html += '</tbody></table>';
  return html;
}
function renderMetrics(data) {
  // Live Trading Metrics
  let html = `
  <div class="section-title"><span class="icon icon-btc">&#128181;</span>Live Trading Metrics</div>
  <div class="row g-4">
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-usd">&#36;</span>USD Balance</h5>
        <p class="card-text display-6">$${Number(data.usd_balance).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-profit">&#x1F4B0;</span>Total Profit</h5>
        <p class="card-text display-6">$${Number(data.live_trading.total_profit).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-trade">&#128200;</span>P/L</h5>
        <p class="card-text display-6">$${Number(data.live_trading.pl_unrealized).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</p>
      </div></div>
    </div>
  </div>
  <div class="row mt-4"><div class="col"><div class="card shadow"><div class="card-body">
    <h5 class="card-title"><span class="icon icon-trade">&#128200;</span>Current Position</h5>
    `;
  if (data.position) {
    html += `<table class="table table-dark table-striped">
      <tr><th>Type</th><td>${data.position.type || 'auto'}</td></tr>
      <tr><th>Volume</th><td>${data.position.volume}</td></tr>
      <tr><th>Entry Price</th><td>$${Number(data.position.entry_price).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</td></tr>
      <tr><th>P/L</th><td>${data.pl >= 0 ? `<span class='icon icon-profit'>&#x1F4B0;</span> <span class='text-success'>$${Number(data.pl).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</span>` : `<span class='icon icon-loss'>&#x1F4B8;</span> <span class='text-danger'>$${Number(data.pl).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</span>`}</td></tr>
    </table>`;
  } else {
    html += `<p class="text-secondary">No open position</p>`;
  }
  html += `<div class="mt-3"><strong>Trades:</strong> ${data.live_trading.total_profit !== undefined ? (data.live_trading.total_trades || 0) : 0}</div>`;
  html += `<div class="mt-2"><strong>Win rate:</strong> ${data.live_trading.win_rate}%</div>`;
  html += `<div class="mt-2"><strong>Uptime:</strong> ${Math.floor(data.live_trading.uptime/3600)}h ${Math.floor((data.live_trading.uptime%3600)/60)}m</div>`;
  html += `<div class=\"mt-4\"><strong>Last 5 Trades:</strong></div>`;
  html += renderTradeTable(data.live_trading.last_5_trades);
  html += `</div></div></div></div>`;

  // Live Paper Metrics
  html += `<div class="section-title"><span class="icon icon-paper">&#128196;</span>Live Paper Metrics</div>
  <div class="row g-4">
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-usd">&#36;</span>USD Balance</h5>
        <p class="card-text display-6">$${Number(data.paper.balance).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-profit">&#x1F4B0;</span>Total Profit</h5>
        <p class="card-text display-6">$${Number(data.paper.total_profit).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-trade">&#128200;</span>P/L</h5>
        <p class="card-text display-6">$${Number(data.paper.pl_unrealized).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</p>
      </div></div>
    </div>
  </div>
  <div class="row mt-4"><div class="col"><div class="card shadow"><div class="card-body">
    <h5 class="card-title"><span class="icon icon-trade">&#128200;</span>Current Position</h5>
    `;
  if (data.paper.open_position) {
    html += `<table class="table table-dark table-striped">
      <tr><th>Volume</th><td>${data.paper.open_position.volume}</td></tr>
      <tr><th>Entry Price</th><td>$${Number(data.paper.open_position.entry_price).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</td></tr>
      <tr><th>P/L</th><td>${data.paper.pl_unrealized >= 0 ? `<span class='icon icon-profit'>&#x1F4B0;</span> <span class='text-success'>$${Number(data.paper.pl_unrealized).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</span>` : `<span class='icon icon-loss'>&#x1F4B8;</span> <span class='text-danger'>$${Number(data.paper.pl_unrealized).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</span>`}</td></tr>
    </table>`;
  } else {
    html += `<p class="text-secondary">No open position</p>`;
  }
  html += `<div class="mt-3"><strong>Trades:</strong> ${data.paper.total_trades || 0}</div>`;
  html += `<div class="mt-2"><strong>Win rate:</strong> ${data.paper.win_rate.toFixed(2)}%</div>`;
  html += `<div class="mt-2"><strong>Uptime:</strong> ${Math.floor(data.paper.uptime/3600)}h ${Math.floor((data.paper.uptime%3600)/60)}m</div>`;
  html += `<div class=\"mt-4\"><strong>Last 5 Trades:</strong></div>`;
  html += renderTradeTable(data.paper.last_5_trades);
  html += `</div></div></div></div>`;

  // Server/Bot Metrics
  html += `<div class="section-title"><span class="icon icon-server">&#128187;</span>Server & Bot Status Metrics</div>
  <div class="row g-4">
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-server">&#9200;</span>Flask Uptime</h5>
        <p class="card-text display-6">${Math.floor(data.server.flask_uptime/3600)}h ${Math.floor((data.server.flask_uptime%3600)/60)}m</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-server">&#9881;&#65039;</span>CPU</h5>
        <p class="card-text display-6">${data.server.cpu_percent}%</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-server">&#128421;&#65039;</span>RAM</h5>
        <p class="card-text display-6">${data.server.ram_percent}%</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-server">&#128190;</span>Disk</h5>
        <p class="card-text display-6">${data.server.disk_percent}%</p>
      </div></div>
    </div>
  </div>
  <div class="row mt-4"><div class="col"><div class="card shadow"><div class="card-body">
    <h5 class="card-title"><span class="icon icon-server">&#128187;</span>System</h5>
    <p class="card-text">${data.server.platform}</p>
    <div class="mt-2"><strong>Bot Status:</strong> <span class="badge bg-success">Running</span></div>
  </div></div></div></div>`;

  document.getElementById('metrics-root').innerHTML = html;
  document.getElementById('now').textContent = data.now;
}
async function fetchMetrics() {
  try {
    const res = await fetch('/metrics');
    const data = await res.json();
    renderMetrics(data);
  } catch (e) {
    document.getElementById('metrics-root').innerHTML = '<div class="alert alert-danger">Error loading metrics.</div>';
  }
}
function renderLogs(logs) {
  let html = `<div class='section-title'><span class='icon icon-logs'>&#128221;</span>Last Logs</div><pre style='background:#181a1b;color:#f8e6ed;padding:1em;border-radius:8px;max-height:350px;overflow:auto;font-size:0.95em;'>${logs}</pre>`;
  document.getElementById('logs-root').innerHTML = html;
}
async function fetchLogs() {
  try {
    const res = await fetch('/logs');
    const data = await res.json();
    renderLogs(data.logs);
  } catch (e) {
    document.getElementById('logs-root').innerHTML = '<div class="alert alert-danger">Error loading logs.</div>';
  }
}
fetchMetrics();
setInterval(fetchMetrics, 5000);
fetchLogs();
setInterval(fetchLogs, 5000);
</script>
</body>
</html>
'''

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
