from flask import Flask, render_template_string, jsonify
import os
import sys
from datetime import datetime
from decimal import Decimal
import krakenex
import sqlite3
import psutil
import platform
import time

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
    # TODO: Replace with real data source if available
    # Dummy example for last 5 trades
    return {
        'last_trade': 'N/A',
        'win_rate': 0,
        'uptime': 0,
        'last_5_trades': []
    }

# --- LIVE_PAPER METRICS ---
def get_live_paper_metrics():
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
    return metrics

# --- SYSTEM METRICS ---
def get_server_metrics():
    return {
        'flask_uptime': int(time.time() - SERVER_START),
        'cpu_percent': psutil.cpu_percent(),
        'ram_percent': psutil.virtual_memory().percent,
        'platform': platform.platform(),
        'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

@app.route("/metrics")
def metrics_api():
    usd_balance = get_account_balance() or 0
    btc_balance = get_asset_balance() or 0
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
        'btc_balance': btc_balance,
        'price': price,
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

@app.route("/btc_chart")
def btc_chart():
    chart_path = os.path.join("metrics", "charts", "btc_chart_live.html")
    if not os.path.exists(chart_path):
        return "<div style='color:red'>No chart available. Run save_btc_chart_live.py first.</div>"
    with open(chart_path, "r", encoding="utf-8") as f:
        return f.read()

@app.route("/")
def dashboard():
    usd_balance = get_account_balance() or 0
    btc_balance = get_asset_balance() or 0
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
        usd_balance=usd_balance, btc_balance=btc_balance, price=price, position=position, pl=pl,
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
      <td>$${Number(t.price).toFixed(2)}</td>
      <td>${t.volume}</td>
      <td>${t.time ? t.time.replace('T',' ').slice(0,19) : ''}</td>
      <td>${t.profit !== undefined ? (t.profit >= 0 ? `<span class='icon icon-profit'>&#x1F4B0;</span> <span class='text-success'>$${Number(t.profit).toFixed(2)}</span>` : `<span class='icon icon-loss'>&#x1F4B8;</span> <span class='text-danger'>$${Number(t.profit).toFixed(2)}</span>`) : ''}</td>
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
        <p class="card-text display-6">$${data.usd_balance.toFixed(2)}</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-btc">&#x20BF;</span>BTC Balance</h5>
        <p class="card-text display-6">${data.btc_balance.toFixed(6)} BTC</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-btc">&#128176;</span>BTC/USD Price</h5>
        <p class="card-text display-6">$${data.price.toFixed(2)}</p>
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
      <tr><th>Entry Price</th><td>$${data.position.entry_price}</td></tr>
      <tr><th>P/L</th><td>${data.pl >= 0 ? `<span class='icon icon-profit'>&#x1F4B0;</span> <span class='text-success'>$${data.pl.toFixed(2)}</span>` : `<span class='icon icon-loss'>&#x1F4B8;</span> <span class='text-danger'>$${data.pl.toFixed(2)}</span>`}</td></tr>
    </table>`;
  } else {
    html += `<p class="text-secondary">No open position</p>`;
  }
  html += `<div class="mt-3"><strong>Last trade:</strong> ${data.live_trading.last_trade}</div>`;
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
        <h5 class="card-title"><span class="icon icon-usd">&#36;</span>Balance</h5>
        <p class="card-text display-6">$${data.paper.balance.toFixed(2)}</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-trade">&#128200;</span>Executed Trades</h5>
        <p class="card-text display-6">${data.paper.total_trades}</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-profit">&#x1F4B0;</span>Total Profit</h5>
        <p class="card-text display-6">$${data.paper.total_profit.toFixed(2)}</p>
      </div></div>
    </div>
  </div>
  <div class="row mt-4"><div class="col"><div class="card shadow"><div class="card-body">
    <h5 class="card-title"><span class="icon icon-trade">&#128200;</span>Current Position</h5>
    `;
  if (data.paper.open_position) {
    html += `<table class="table table-dark table-striped">
      <tr><th>Volume</th><td>${data.paper.open_position.volume}</td></tr>
      <tr><th>Entry Price</th><td>$${data.paper.open_position.entry_price}</td></tr>
      <tr><th>P/L</th><td>${data.paper.pl_unrealized >= 0 ? `<span class='icon icon-profit'>&#x1F4B0;</span> <span class='text-success'>$${data.paper.pl_unrealized.toFixed(2)}</span>` : `<span class='icon icon-loss'>&#x1F4B8;</span> <span class='text-danger'>$${data.paper.pl_unrealized.toFixed(2)}</span>`}</td></tr>
    </table>`;
  } else {
    html += `<p class="text-secondary">No open position</p>`;
  }
  html += `<div class="mt-3"><strong>Last trade:</strong> `;
  if (data.paper.last_trade) {
    html += `${data.paper.last_trade.type.toUpperCase()} ${data.paper.last_trade.volume} @ $${data.paper.last_trade.price} (${data.paper.last_trade.time}) | P/L: ${data.paper.last_trade.profit >= 0 ? `<span class='icon icon-profit'>&#x1F4B0;</span> <span class='text-success'>$${Number(data.paper.last_trade.profit).toFixed(2)}</span>` : `<span class='icon icon-loss'>&#x1F4B8;</span> <span class='text-danger'>$${Number(data.paper.last_trade.profit).toFixed(2)}</span>`}`;
  } else {
    html += `N/A`;
  }
  html += `</div><div class="mt-2"><strong>Win rate:</strong> ${data.paper.win_rate.toFixed(2)}%</div>`;
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
