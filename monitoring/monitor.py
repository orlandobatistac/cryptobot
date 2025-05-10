import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger().setLevel(logging.WARNING)

from flask import Flask, render_template, jsonify, Response
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
import krakenex
import sqlite3
import psutil
import platform
import time
import pandas as pd
import plotly.graph_objs as go
import json
import numpy as np

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

def get_bot_start_time(bot_name):
    results_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
    db_path = os.path.join(results_dir, 'cryptobot.db')
    try:
        with sqlite3.connect(db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT start_time FROM bot_status WHERE bot_name=?", (bot_name,))
            row = c.fetchone()
            if row:
                return datetime.fromisoformat(row[0])
    except Exception:
        pass
    return None

def get_live_trading_metrics():
    start_time = get_bot_start_time('live_trading')
    uptime = int((datetime.utcnow() - start_time).total_seconds()) if start_time else 0
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
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    initial_capital = config.get('general', {}).get('initial_capital', 10000)
    results_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
    db_path = os.path.join(results_dir, 'cryptobot.db')
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
    # If there are no trades and the balance is 0, show the initial_capital
    if metrics['total_trades'] == 0 and metrics['balance'] == 0:
        metrics['balance'] = initial_capital
    start_time = get_bot_start_time('live_paper')
    if start_time:
        metrics['uptime'] = (datetime.utcnow() - start_time).total_seconds()
    else:
        metrics['uptime'] = 0
    return metrics

# --- DETAILED STRATEGY EVALUATIONS ---
def get_detailed_strategy_evaluations(limit_per_bot=5):
    results_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
    db_path = os.path.join(results_dir, 'cryptobot.db')
    evaluations = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            # Obtener los últimos N registros por bot
            bots = ['live_trading', 'live_paper']
            for bot in bots:
                c.execute('''
                    SELECT timestamp, decision, reason, indicators_state, strategy_conditions, price_at_evaluation, notes, bot_name
                    FROM strategy_evaluations
                    WHERE bot_name = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (bot, limit_per_bot))
                for row in c.fetchall():
                    eval_data = dict(row)
                    # Parsear campos JSON
                    try:
                        eval_data['indicators_state'] = json.loads(row['indicators_state']) if row['indicators_state'] else {}
                    except json.JSONDecodeError:
                        eval_data['indicators_state'] = {"error": "Invalid JSON in indicators_state", "raw_value": row['indicators_state']}
                    try:
                        eval_data['strategy_conditions'] = json.loads(row['strategy_conditions']) if row['strategy_conditions'] else {}
                    except json.JSONDecodeError:
                        eval_data['strategy_conditions'] = {"error": "Invalid JSON in strategy_conditions", "raw_value": row['strategy_conditions']}
                    evaluations.append(eval_data)
    except sqlite3.Error as e:
        logging.error(f"Database error in get_detailed_strategy_evaluations: {e}")
    except Exception as e:
        logging.error(f"Error fetching detailed evaluations: {e}")
    # Ordenar por bot y timestamp descendente
    evaluations.sort(key=lambda x: (x['bot_name'], x['timestamp']), reverse=True)
    return evaluations

@app.route('/api/strategy_evaluations_detailed')
def strategy_evaluations_detailed_api():
    # Get evaluations as before
    data = get_detailed_strategy_evaluations(limit_per_bot=5)
    
    # --- New: Add status and next evaluation info for each bot ---
    bots = ['live_trading', 'live_paper']
    now = int(time.time())
    status_info = {}
    
    # Use the opening of the daily candle for determining evaluation time
    try:
        # Load the OHLC data to get the daily candle information
        df = pd.read_parquet(os.path.join("data", "ohlc_data_60min_all_years.parquet"))
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        df.set_index('Timestamp', inplace=True)
        # Resample to daily candles
        df_1d = df.resample('1D', closed='left', label='left').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        })
        df_1d = df_1d.dropna()
        # Get the current daily candle's opening time (start of the day candle)
        current_date = datetime.now()
        today_date = current_date.replace(hour=0, minute=0, second=0, microsecond=0)
        # Find the most recent candle opening time
        candle_open_times = df_1d.index
        # Find the current daily candle open time (the most recent one)
        current_candle_open = max([ts for ts in candle_open_times if ts <= pd.Timestamp(current_date)])
        next_candle_open = current_candle_open + pd.Timedelta(days=1)
        # Use the next daily candle opening time as evaluation time
        next_eval_ts = int(next_candle_open.timestamp())
        # If there hasn't been an evaluation yet since the current candle opened,
        # schedule one immediately rather than waiting for the next candle
        current_candle_open_ts = int(current_candle_open.timestamp())
        # Check if we already had an evaluation for the current candle period
        current_candle_evals_exist = False
        for bot_name in bots:
            current_candle_evals = [e for e in data if e['bot_name'] == bot_name and 
                                   int(datetime.fromisoformat(e['timestamp']).timestamp()) >= current_candle_open_ts]
            if current_candle_evals:
                current_candle_evals_exist = True
                break
        # If no evaluations happened yet for the current daily candle, schedule one now
        if not current_candle_evals_exist:
            next_eval_ts = current_candle_open_ts
            logging.info(f"No evaluations found for current candle period, scheduling evaluation immediately")
        # Log the scheduled evaluation time
        logging.info(f"Next evaluation based on daily candle opening will be at: {datetime.fromtimestamp(next_eval_ts)}")
        logging.info(f"Time remaining: {(next_eval_ts - now)//3600}h {((next_eval_ts - now)%3600)//60}m {((next_eval_ts - now)%60)}s")
    except Exception as e:
        logging.error(f"Error calculating next evaluation time using daily candles: {e}")
        # Fallback mechanism if data loading or calculation fails
        try:
            # Get current time
            current_date = datetime.now()
            # Get current day start as fallback
            current_day_start = current_date.replace(hour=0, minute=0, second=0, microsecond=0)
            # Next day start as fallback for next candle
            next_day_start = current_day_start + timedelta(days=1)
            next_eval_ts = int(next_day_start.timestamp())
            logging.warning(f"Using fallback calculation for evaluation time: {datetime.fromtimestamp(next_eval_ts)}")
        except Exception as inner_e:
            logging.error(f"Even fallback calculation failed: {inner_e}")
            # Ultimate fallback - 24 hours from now
            next_eval_ts = now + 86400
    
    for bot in bots:
        # Find last evaluation for this bot (useful for status info)
        last_eval = next((e for e in data if e['bot_name'] == bot), None)
        eval_status = 'Waiting for next evaluation'
        
        # Show more descriptive status if available from last evaluation
        if last_eval:
            last_decision = last_eval.get('decision', '').lower()
            if last_decision == 'buy':
                eval_status = 'Signal: BUY - Waiting for next evaluation'
            elif last_decision == 'sell':
                eval_status = 'Signal: SELL - Waiting for next evaluation'
                
        status_info[bot] = {
            'status': eval_status,
            'next_evaluation_ts': next_eval_ts
        }
    return jsonify({
        'evaluations': data,
        'status_info': status_info,
        'now': now
    })

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
    api_status = 'UNKNOWN'
    try:
        usd_balance = get_account_balance() or 0
        api_status = 'ONLINE' if usd_balance is not None else 'ERROR'
    except Exception:
        usd_balance = 0
        api_status = 'ERROR'
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
        'api_status': api_status,
        'now': server['now']
    })

@app.route("/logs")
def logs_api():
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    # Show live_trading.log instead of debug.log
    log_path = os.path.join(logs_dir, 'live_trading.log')
    if not os.path.exists(log_path):
        os.makedirs(logs_dir, exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write('')
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        # Return last 50 lines for more context
        last_lines = lines[-50:]
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
            'High': 'max',            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        })
        df_1d = df_1d.dropna()
        df_1d['SMA59'] = df_1d['Close'].rolling(window=59).mean()
        df_1d['SMA200'] = df_1d['Close'].rolling(window=200).mean()
        # Current price
        last_close = float(df_1d['Close'].iloc[-1]) if not df_1d.empty else None
        now_price = get_realtime_price(PAIR)
        # --- Buy/Sell signals ---
        buy_signals = []
        sell_signals = []
        try:
            results_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
            db_path = os.path.join(results_dir, 'cryptobot.db')
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
        def safe_list(series):
            return [None if (pd.isna(x) or (isinstance(x, float) and np.isnan(x))) else x for x in series]
        data = {
            'x': df_1d.index.strftime('%Y-%m-%d').tolist(),
            'open': safe_list(df_1d['Open']),
            'high': safe_list(df_1d['High']),
            'low': safe_list(df_1d['Low']),
            'close': safe_list(df_1d['Close']),
            'volume': safe_list(df_1d['Volume']),
            'sma59': safe_list(df_1d['SMA59']),
            'sma200': safe_list(df_1d['SMA200']),
            'now_price': now_price,
            'last_close': last_close,
            'buy_signals': buy_signals,
            'sell_signals': sell_signals
        }
        # Equity de Live Trading
        try:
            equity = []
            results_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
            db_path = os.path.join(results_dir, 'cryptobot.db')
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT timestamp, balance FROM trades WHERE type IN ('buy','sell') ORDER BY timestamp ASC")
            for ts, bal in c.fetchall():
                equity.append({'date': pd.to_datetime(ts).strftime('%Y-%m-%d'), 'balance': bal})
            conn.close()
            data['equity'] = equity
        except Exception:
            data['equity'] = []
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
            // --- Gráfica principal ---
            const traceCandle = {
                x: data.x,
                open: data.open,
                high: data.high,
                low: data.low,
                close: data.close,
                type: 'candlestick',
                name: 'Candles',
                increasing: {line: {color: '#888'}},
                decreasing: {line: {color: '#888'}},
                showlegend: false
            };
            const traceSMA59 = {
                x: data.x,
                y: data.sma59,
                type: 'scatter',
                mode: 'lines',
                name: 'SMA 59',
                line: {color: '#a3c9e2', width: 1.5, dash: 'dot'}
            };
            const traceSMA200 = {
                x: data.x,
                y: data.sma200,
                type: 'scatter',
                mode: 'lines',
                name: 'SMA 200',
                line: {color: '#f7d6b3', width: 1.5, dash: 'dash'}
            };
            // Equity Live Trading
            const traceEquity = {
                x: data.equity.map(e => e.date),
                y: data.equity.map(e => e.balance),
                type: 'scatter',
                mode: 'lines',
                name: 'Equity',
                line: {color: '#b2dfdb', width: 6}, // color suave, más gruesa
                yaxis: 'y2',
                connectgaps: true
            };
            // ---
            const plotData = [traceCandle, traceSMA59, traceSMA200, traceEquity];
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
            // Mostrar todo el rango de los últimos 3 años
            range = undefined;
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
                    title: 'Equity',
                    overlaying: 'y',
                    side: 'left',
                    showgrid: false,
                    position: 0,
                    anchor: 'x',
                    color: '#b2dfdb',
                    tickformat: ',.0f',
                    fixedrange: false,
                    automargin: true,
                    rangemode: 'tozero' // el eje empieza en 0
                },
                template: 'plotly_dark',
                margin: {l:40, r:40, t:40, b:40},
                height: getIframeHeight(),
                legend: {orientation: 'h', yanchor: 'bottom', y: 1.02, xanchor: 'right', x: 1, font: {color: '#e0e0e0'}},
                title: 'BTC/USDT 1D - Updated: ' + new Date().toLocaleString(),
                shapes: shapes,
                annotations: annotations
            };
            Plotly.newPlot('chart', plotData, layout, {responsive:true});
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
    return render_template('index.html',
        usd_balance=usd_balance, position=position, pl=pl,
        paper=paper, server=server, now=server['now']
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
