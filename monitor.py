from flask import Flask, render_template_string
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
        c.execute("SELECT type, price, volume, timestamp FROM trades ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
        if row:
            metrics['last_trade'] = {
                'type': row[0], 'price': row[1], 'volume': row[2], 'time': row[3]
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
        .card { background: #23272b; color: #f8f9fa; }
        .table-dark { --bs-table-bg: #23272b; }
        .navbar { background: #23272b; }
        .section-title { margin-top: 2rem; margin-bottom: 1rem; font-size: 1.3rem; color: #f8f9fa; }
    </style>
</head>
<body>
<nav class="navbar navbar-dark">
  <div class="container-fluid">
    <span class="navbar-brand mb-0 h1">CryptoBot Dashboard</span>
    <span class="text-secondary">{{ now }}</span>
  </div>
</nav>
<div class="container py-4">
  <!-- LIVE TRADING METRICS -->
  <div class="section-title">Live Trading Metrics</div>
  <div class="row g-4">
    <div class="col-md-4">
      <div class="card shadow">
        <div class="card-body">
          <h5 class="card-title">USD Balance</h5>
          <p class="card-text display-6">${{ usd_balance | round(2) }}</p>
        </div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card shadow">
        <div class="card-body">
          <h5 class="card-title">BTC Balance</h5>
          <p class="card-text display-6">{{ btc_balance | round(6) }} BTC</p>
        </div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card shadow">
        <div class="card-body">
          <h5 class="card-title">BTC/USD Price</h5>
          <p class="card-text display-6">${{ price | round(2) }}</p>
        </div>
      </div>
    </div>
  </div>
  <div class="row mt-4">
    <div class="col">
      <div class="card shadow">
        <div class="card-body">
          <h5 class="card-title">Current Position</h5>
          {% if position %}
            <table class="table table-dark table-striped">
              <tr><th>Type</th><td>{{ position['type'] if position['type'] else 'auto' }}</td></tr>
              <tr><th>Volume</th><td>{{ position['volume'] }}</td></tr>
              <tr><th>Entry Price</th><td>${{ position['entry_price'] }}</td></tr>
              <tr><th>P/L</th><td>{% if pl >= 0 %}<span class="text-success">${{ pl | round(2) }}</span>{% else %}<span class="text-danger">${{ pl | round(2) }}</span>{% endif %}</td></tr>
            </table>
          {% else %}
            <p class="text-secondary">No open position</p>
          {% endif %}
        </div>
      </div>
    </div>
  </div>
  <!-- LIVE PAPER METRICS -->
  <div class="section-title">Live Paper Metrics</div>
  <div class="row g-4">
    <div class="col-md-4">
      <div class="card shadow">
        <div class="card-body">
          <h5 class="card-title">Balance</h5>
          <p class="card-text display-6">${{ paper.balance | round(2) }}</p>
        </div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card shadow">
        <div class="card-body">
          <h5 class="card-title">Executed Trades</h5>
          <p class="card-text display-6">{{ paper.total_trades }}</p>
        </div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card shadow">
        <div class="card-body">
          <h5 class="card-title">Total Profit</h5>
          <p class="card-text display-6">${{ paper.total_profit | round(2) }}</p>
        </div>
      </div>
    </div>
  </div>
  <div class="row mt-4">
    <div class="col">
      <div class="card shadow">
        <div class="card-body">
          <h5 class="card-title">Current Position</h5>
          {% if paper.open_position %}
            <table class="table table-dark table-striped">
              <tr><th>Volume</th><td>{{ paper.open_position.volume }}</td></tr>
              <tr><th>Entry Price</th><td>${{ paper.open_position.entry_price }}</td></tr>
              <tr><th>P/L</th><td>{% if paper.pl_unrealized >= 0 %}<span class="text-success">${{ paper.pl_unrealized | round(2) }}</span>{% else %}<span class="text-danger">${{ paper.pl_unrealized | round(2) }}</span>{% endif %}</td></tr>
            </table>
          {% else %}
            <p class="text-secondary">No open position</p>
          {% endif %}
          <div class="mt-3">
            <strong>Last trade:</strong>
            {% if paper.last_trade %}
              {{ paper.last_trade.type | upper }} {{ paper.last_trade.volume }} @ ${{ paper.last_trade.price }} ({{ paper.last_trade.time }})
            {% else %}
              N/A
            {% endif %}
          </div>
          <div class="mt-2">
            <strong>Win rate:</strong> {{ paper.win_rate | round(2) }}%
          </div>
          <div class="mt-2">
            <strong>Uptime:</strong> {{ (paper.uptime // 3600)|int }}h {{ ((paper.uptime % 3600) // 60)|int }}m
          </div>
        </div>
      </div>
    </div>
  </div>
  <!-- SERVER/BOT METRICS -->
  <div class="section-title">Server & Bot Status Metrics</div>
  <div class="row g-4">
    <div class="col-md-4">
      <div class="card shadow">
        <div class="card-body">
          <h5 class="card-title">Flask Uptime</h5>
          <p class="card-text display-6">{{ (server.flask_uptime // 3600)|int }}h {{ ((server.flask_uptime % 3600) // 60)|int }}m</p>
        </div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card shadow">
        <div class="card-body">
          <h5 class="card-title">CPU</h5>
          <p class="card-text display-6">{{ server.cpu_percent }}%</p>
        </div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card shadow">
        <div class="card-body">
          <h5 class="card-title">RAM</h5>
          <p class="card-text display-6">{{ server.ram_percent }}%</p>
        </div>
      </div>
    </div>
  </div>
  <div class="row mt-4">
    <div class="col">
      <div class="card shadow">
        <div class="card-body">
          <h5 class="card-title">System</h5>
          <p class="card-text">{{ server.platform }}</p>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
'''

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
