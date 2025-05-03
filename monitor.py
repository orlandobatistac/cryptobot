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
    # Example: you can expand this to read from a file, database, or shared memory if needed
    # For now, just return N/A or dummy values
    return {
        'last_trade': 'N/A',
        'win_rate': 0,
        'uptime': 0
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
        'uptime': 0
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
        body { background: #181a1b; color: #f8f9fa; }
        .card { background: #23272b; color: #f8f9fa; border: none; }
        .table-dark { --bs-table-bg: #23272b; }
        .navbar { background: linear-gradient(90deg, #1e2326 0%, #007ACC 100%); }
        .section-title { margin-top: 2rem; margin-bottom: 1rem; font-size: 1.3rem; color: #FFD700; letter-spacing: 1px; text-shadow: 0 1px 8px #000; }
        .card-title { color: #00e676; font-weight: bold; letter-spacing: 0.5px; }
        .display-6 { font-weight: bold; }
        .text-success { color: #00e676 !important; }
        .text-danger { color: #ff1744 !important; }
        .text-secondary { color: #90caf9 !important; }
        .badge.bg-success { background: linear-gradient(90deg, #00e676 0%, #388e3c 100%); color: #181a1b; }
        pre { background: #181a1b; color: #FFD700; border: 1px solid #23272b; }
        .card.shadow { box-shadow: 0 0 16px 0 #007ACC33, 0 2px 4px 0 #000a; }
        .navbar-brand { color: #FFD700 !important; font-weight: bold; letter-spacing: 1px; }
        .highlight { color: #FFD700; font-weight: bold; }
    </style>
</head>
<body>
<nav class="navbar navbar-dark">
  <div class="container-fluid">
    <span class="navbar-brand mb-0 h1">CryptoBot Dashboard</span>
    <span class="text-secondary" id="now">{{ now }}</span>
  </div>
</nav>
<div class="container py-4" id="metrics-root">
  <!-- All metrics content will be rendered here by JS -->
</div>
<div class="container py-4" id="logs-root">
  <!-- Logs will be rendered here by JS -->
</div>
<script>
function renderMetrics(data) {
  // Live Trading Metrics
  let html = `
  <div class="section-title">Live Trading Metrics</div>
  <div class="row g-4">
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title">USD Balance</h5>
        <p class="card-text display-6">$${data.usd_balance.toFixed(2)}</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title">BTC Balance</h5>
        <p class="card-text display-6">${data.btc_balance.toFixed(6)} BTC</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title">BTC/USD Price</h5>
        <p class="card-text display-6">$${data.price.toFixed(2)}</p>
      </div></div>
    </div>
  </div>
  <div class="row mt-4"><div class="col"><div class="card shadow"><div class="card-body">
    <h5 class="card-title">Current Position</h5>
    `;
  if (data.position) {
    html += `<table class="table table-dark table-striped">
      <tr><th>Type</th><td>${data.position.type || 'auto'}</td></tr>
      <tr><th>Volume</th><td>${data.position.volume}</td></tr>
      <tr><th>Entry Price</th><td>$${data.position.entry_price}</td></tr>
      <tr><th>P/L</th><td>${data.pl >= 0 ? `<span class='text-success'>$${data.pl.toFixed(2)}</span>` : `<span class='text-danger'>$${data.pl.toFixed(2)}</span>`}</td></tr>
    </table>`;
  } else {
    html += `<p class="text-secondary">No open position</p>`;
  }
  html += `<div class="mt-3"><strong>Last trade:</strong> ${data.live_trading.last_trade}</div>`;
  html += `<div class="mt-2"><strong>Win rate:</strong> ${data.live_trading.win_rate}%</div>`;
  html += `<div class="mt-2"><strong>Uptime:</strong> ${Math.floor(data.live_trading.uptime/3600)}h ${Math.floor((data.live_trading.uptime%3600)/60)}m</div>`;
  html += `</div></div></div></div>`;

  // Live Paper Metrics
  html += `<div class="section-title">Live Paper Metrics</div>
  <div class="row g-4">
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title">Balance</h5>
        <p class="card-text display-6">$${data.paper.balance.toFixed(2)}</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title">Executed Trades</h5>
        <p class="card-text display-6">${data.paper.total_trades}</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title">Total Profit</h5>
        <p class="card-text display-6">$${data.paper.total_profit.toFixed(2)}</p>
      </div></div>
    </div>
  </div>
  <div class="row mt-4"><div class="col"><div class="card shadow"><div class="card-body">
    <h5 class="card-title">Current Position</h5>
    `;
  if (data.paper.open_position) {
    html += `<table class="table table-dark table-striped">
      <tr><th>Volume</th><td>${data.paper.open_position.volume}</td></tr>
      <tr><th>Entry Price</th><td>$${data.paper.open_position.entry_price}</td></tr>
      <tr><th>P/L</th><td>${data.paper.pl_unrealized >= 0 ? `<span class='text-success'>$${data.paper.pl_unrealized.toFixed(2)}</span>` : `<span class='text-danger'>$${data.paper.pl_unrealized.toFixed(2)}</span>`}</td></tr>
    </table>`;
  } else {
    html += `<p class="text-secondary">No open position</p>`;
  }
  html += `<div class="mt-3"><strong>Last trade:</strong> `;
  if (data.paper.last_trade) {
    html += `${data.paper.last_trade.type.toUpperCase()} ${data.paper.last_trade.volume} @ $${data.paper.last_trade.price} (${data.paper.last_trade.time}) | P/L: ${data.paper.last_trade.profit >= 0 ? `<span class='text-success'>$${Number(data.paper.last_trade.profit).toFixed(2)}</span>` : `<span class='text-danger'>$${Number(data.paper.last_trade.profit).toFixed(2)}</span>`}`;
  } else {
    html += `N/A`;
  }
  html += `</div><div class="mt-2"><strong>Win rate:</strong> ${data.paper.win_rate.toFixed(2)}%</div>`;
  html += `<div class="mt-2"><strong>Uptime:</strong> ${Math.floor(data.paper.uptime/3600)}h ${Math.floor((data.paper.uptime%3600)/60)}m</div>`;
  html += `</div></div></div></div>`;

  // Server/Bot Metrics
  html += `<div class="section-title">Server & Bot Status Metrics</div>
  <div class="row g-4">
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title">Flask Uptime</h5>
        <p class="card-text display-6">${Math.floor(data.server.flask_uptime/3600)}h ${Math.floor((data.server.flask_uptime%3600)/60)}m</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title">CPU</h5>
        <p class="card-text display-6">${data.server.cpu_percent}%</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title">RAM</h5>
        <p class="card-text display-6">${data.server.ram_percent}%</p>
      </div></div>
    </div>
  </div>
  <div class="row mt-4"><div class="col"><div class="card shadow"><div class="card-body">
    <h5 class="card-title">System</h5>
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
  let html = `<div class='section-title'>Last Logs</div><pre style='background:#181a1b;color:#f8f9fa;padding:1em;border-radius:8px;max-height:350px;overflow:auto;font-size:0.95em;'>${logs}</pre>`;
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
