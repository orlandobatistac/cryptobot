import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

CONFIG_PATH = 'config.json'

def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def send_email(subject, body, recipients=None):
    config = load_config()['notifications']
    smtp_cfg = config['smtp']
    if recipients is None:
        recipients = config['recipients']
    msg = MIMEMultipart()
    msg['From'] = smtp_cfg['user']
    msg['To'] = ', '.join(recipients)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))
    try:
        with smtplib.SMTP(smtp_cfg['host'], smtp_cfg['port']) as server:
            server.starttls()
            server.login(smtp_cfg['user'], smtp_cfg['password'])
            server.sendmail(smtp_cfg['user'], recipients, msg.as_string())
        return True
    except Exception as e:
        print(f"[NOTIFICATIONS] Error sending email: {e}")
        return False

# --- Email Formats ---
def format_critical_error():
    return {
        'subject': '[CryptoBot] Critical Error Test',
        'body': f"""
        <h2>Critical Error Detected</h2>
        <p><b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><b>Error:</b> Exception simulation: ValueError('Test error')</p>
        <p>Stacktrace:<br><pre>Traceback (most recent call last):\n  File 'main.py', line 42, in &lt;module&gt;\n    raise ValueError('Test error')\nValueError: Test error</pre></p>
        """
    }

def format_order(tipo='compra'):
    return {
        'subject': f'[CryptoBot] {"Buy" if tipo=="compra" else "Sell"} Order Executed (Test)',
        'body': f"""
        <h2>{'Buy' if tipo=='compra' else 'Sell'} Order Executed</h2>
        <ul>
            <li><b>Type:</b> {tipo.capitalize() if tipo=='compra' else 'Sell'}</li>
            <li><b>Pair:</b> BTC/USD</li>
            <li><b>Amount:</b> 0.01</li>
            <li><b>Price:</b> $62,000.00</li>
            <li><b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</li>
            <li><b>Reason:</b> Test signal</li>
        </ul>
        """
    }

def format_daily_summary():
    return {
        'subject': '[CryptoBot] Daily Summary (Test)',
        'body': f"""
        <h2>Daily Summary (Test)</h2>
        <h3>Live Trading</h3>
        <ul>
            <li><b>Balance:</b> $1,200.00</li>
            <li><b>Profit:</b> $200.00</li>
            <li><b>Trades:</b> 5</li>
        </ul>
        <h3>Live Paper</h3>
        <ul>
            <li><b>Balance:</b> $1,050.00</li>
            <li><b>Profit:</b> $50.00</li>
            <li><b>Trades:</b> 2</li>
        </ul>
        <h3>Server</h3>
        <ul>
            <li><b>CPU:</b> 12%</li>
            <li><b>RAM:</b> 45%</li>
            <li><b>Uptime:</b> 3h 22m</li>
        </ul>
        """
    }

def format_monthly_summary():
    return {
        'subject': '[CryptoBot] Monthly Summary (Test)',
        'body': f"""
        <h2>Monthly Summary (Test)</h2>
        <ul>
            <li><b>Initial balance:</b> $1,000.00</li>
            <li><b>Final balance:</b> $1,300.00</li>
            <li><b>Total profit:</b> $300.00</li>
            <li><b>Total trades:</b> 20</li>
        </ul>
        """
    }

def format_analysis():
    return {
        'subject': '[CryptoBot] Daily Analysis (Test)',
        'body': f"""
        <h2>Daily Analysis (Test)</h2>
        <ul>
            <li><b>Candle:</b> 2025-05-03</li>
            <li><b>Signal:</b> Buy</li>
            <li><b>Indicators:</b> RSI=70, MACD=1.2</li>
        </ul>
        <h3>Open Position</h3>
        <ul>
            <li><b>Entry price:</b> $61,500.00</li>
            <li><b>Current PnL:</b> $100.00</li>
            <li><b>Duration:</b> 2h 10m</li>
        </ul>
        """
    }

def format_status_change(enabled):
    return {
        'subject': f'[CryptoBot] Notifications {"Enabled" if enabled else "Disabled"}',
        'body': f"""
        <h2>Notifications {"Enabled" if enabled else "Disabled"}</h2>
        <p>Notifications have been {"enabled" if enabled else "disabled"} successfully on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.</p>
        """
    }

def format_dashboard_email(metrics, is_test=False):
    live_trading = metrics.get('live_trading', {})
    paper = metrics.get('paper', {})
    server = metrics.get('server', {})
    usd_balance = metrics.get('usd_balance', 0)
    position = metrics.get('position', None)
    pl = metrics.get('pl', 0)
    now = metrics.get('now', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    def fmt(val, dec=2):
        try:
            return f"${float(val):,.{dec}f}"
        except:
            return str(val)
    html = f"""
    <h2>CryptoBot - Summary {'(Test)' if is_test else ''}</h2>
    <h3>Live Trading</h3>
    <ul>
        <li><b>USD Balance:</b> {fmt(usd_balance)}</li>
        <li><b>Total Profit:</b> {fmt(live_trading.get('total_profit', 0))}</li>
        <li><b>P/L:</b> {fmt(live_trading.get('pl_unrealized', 0))}</li>
        <li><b>Trades:</b> {live_trading.get('total_trades', 0)}</li>
        <li><b>Win rate:</b> {live_trading.get('win_rate', 0)}%</li>
        <li><b>Uptime:</b> {int(live_trading.get('uptime', 0)//3600)}h {int((live_trading.get('uptime', 0)%3600)//60)}m</li>
    </ul>
    <h4>Last 5 trades:</h4>
    <ul>"""
    for t in live_trading.get('last_5_trades', []):
        html += f"<li>{t.get('type','').upper()} {fmt(t.get('price'))} x {t.get('volume')} ({t.get('time','')}) P/L: {fmt(t.get('profit'))}</li>"
    if not live_trading.get('last_5_trades'):
        html += "<li>No recent trades</li>"
    html += "</ul>"
    html += f"""
    <h3>Live Paper</h3>
    <ul>
        <li><b>USD Balance:</b> {fmt(paper.get('balance', 0))}</li>
        <li><b>Total Profit:</b> {fmt(paper.get('total_profit', 0))}</li>
        <li><b>P/L:</b> {fmt(paper.get('pl_unrealized', 0))}</li>
        <li><b>Trades:</b> {paper.get('total_trades', 0)}</li>
        <li><b>Win rate:</b> {paper.get('win_rate', 0):.2f}%</li>
        <li><b>Uptime:</b> {int(paper.get('uptime', 0)//3600)}h {int((paper.get('uptime', 0)%3600)//60)}m</li>
    </ul>
    <h4>Last 5 trades:</h4>
    <ul>"""
    for t in paper.get('last_5_trades', []):
        html += f"<li>{t.get('type','').upper()} {fmt(t.get('price'))} x {t.get('volume')} ({t.get('time','')}) P/L: {fmt(t.get('profit'))}</li>"
    if not paper.get('last_5_trades'):
        html += "<li>No recent trades</li>"
    html += "</ul>"
    html += f"""
    <h3>Server</h3>
    <ul>
        <li><b>CPU:</b> {server.get('cpu_percent', 0)}%</li>
        <li><b>RAM:</b> {server.get('ram_percent', 0)}%</li>
        <li><b>Uptime:</b> {int(server.get('flask_uptime', 0)//3600)}h {int((server.get('flask_uptime', 0)%3600)//60)}m</li>
        <li><b>Platform:</b> {server.get('platform', '')}</li>
        <li><b>Date/Time:</b> {now}</li>
    </ul>
    """
    return {
        'subject': f'[CryptoBot] Daily Summary {"(Test)" if is_test else ""}',
        'body': html
    }

def send_test_emails():
    # Simulate test metrics
    metrics = {
        'usd_balance': 0,
        'position': None,
        'pl': 0,
        'live_trading': {
            'total_profit': 0,
            'pl_unrealized': 0,
            'last_trade': 'N/A',
            'win_rate': 0,
            'uptime': 0,
            'total_trades': 0,
            'last_5_trades': []
        },
        'paper': {
            'balance': 0,
            'total_profit': 0,
            'pl_unrealized': 0,
            'total_trades': 0,
            'win_rate': 0,
            'uptime': 0,
            'last_5_trades': []
        },
        'server': {
            'flask_uptime': 0,
            'cpu_percent': 0,
            'ram_percent': 0,
            'platform': 'Windows',
            'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        },
        'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    send_email(**format_status_change(True))
    send_email(**format_critical_error())
    send_email(**format_order('compra'))
    send_email(**format_order('venta'))
    send_email(**format_dashboard_email(metrics, is_test=True))
    send_email(**format_monthly_summary())
    send_email(**format_analysis())
