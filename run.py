import os
import signal
import subprocess
import sys
import time
import platform
import logging
import json
from notifications import send_test_emails, load_config, send_email, format_status_change, format_daily_summary, format_monthly_summary, format_dashboard_email
import monitor
from datetime import datetime, timedelta
import threading

# Kill only python processes related to cryptobot before starting the orchestrator
if platform.system() == 'Linux':
    os.system("pkill -f 'python.*cryptobot'")
    time.sleep(2)
elif platform.system() == 'Windows':
    # Find processes that include 'cryptobot' in the command line
    import psutil
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['name'] and 'python' in proc.info['name'].lower():
                cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                if 'cryptobot' in cmdline:
                    print(f"Killing process PID {proc.info['pid']} ({cmdline})")
                    proc.kill()
        except Exception:
            pass
    time.sleep(2)

logging.basicConfig(level=logging.WARNING)
logging.getLogger().setLevel(logging.WARNING)

# Configuration of routes
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPDATE_DATA_SCRIPT = os.path.join(BASE_DIR, 'data', 'update_data.py')

# Function to free port 5000
def kill_port_5000():
    try:
        if platform.system() == 'Windows':
            import subprocess
            # Find the PID using port 5000
            result = subprocess.check_output('netstat -ano | findstr :5000', shell=True).decode()
            for line in result.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(':5000'):
                    pid = parts[-1]
                    print(f"[RUN] Killing process on port 5000 (PID {pid}) [Windows]")
                    subprocess.call(f'taskkill /PID {pid} /F', shell=True)
        else:
            import subprocess
            # Find the PID using port 5000
            result = subprocess.check_output('lsof -i :5000 | grep LISTEN', shell=True).decode()
            for line in result.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 2:
                    pid = parts[1]
                    print(f"[RUN] Killing process on port 5000 (PID {pid}) [Linux]")
                    subprocess.call(f'kill -9 {pid}', shell=True)
    except Exception as e:
        print(f"[RUN] Could not automatically free port 5000: {e}")

# Function to launch subprocesses and restart them if they crash
def run_subprocess(cmd, name):
    while True:
        if name == 'monitor':
            kill_port_5000()
        print(f"[RUN] Launching {name}...")
        p = subprocess.Popen([sys.executable, cmd])
        p.wait()
        print(f"[WARN] {name} finished. Restarting in 5s...")
        time.sleep(5)

def activate_notifications():
    config = load_config()
    if not config['notifications']['enabled']:
        config['notifications']['enabled'] = True
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print('[RUN] Notifications enabled. Sending test emails...')
        send_test_emails()
    else:
        print('[RUN] Notifications were already enabled.')

def deactivate_notifications():
    config = load_config()
    if config['notifications']['enabled']:
        config['notifications']['enabled'] = False
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print('[RUN] Notifications disabled.')
        send_email(**format_status_change(False))
    else:
        print('[RUN] Notifications were already disabled.')

def send_daily_summary():
    config = load_config()
    notif = config.get('notifications', {})
    if not (notif.get('enabled', False) and notif.get('types', {}).get('daily_summary', False)):
        return
    # Get real metrics from monitor.py
    try:
        metrics = monitor.metrics_api().get_json() if hasattr(monitor.metrics_api(), 'get_json') else monitor.metrics_api().json
    except Exception:
        metrics = None
    if not metrics:
        # If they cannot be obtained, use zeros
        metrics = {
            'usd_balance': 0,
            'position': None,
            'pl': 0,
            'live_trading': {'total_profit': 0, 'pl_unrealized': 0, 'last_trade': 'N/A', 'win_rate': 0, 'uptime': 0, 'total_trades': 0, 'last_5_trades': []},
            'paper': {'balance': 0, 'total_profit': 0, 'pl_unrealized': 0, 'total_trades': 0, 'win_rate': 0, 'uptime': 0, 'last_5_trades': []},
            'server': {'flask_uptime': 0, 'cpu_percent': 0, 'ram_percent': 0, 'platform': 'Windows', 'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S')},
            'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    send_email(**format_dashboard_email(metrics))

def send_monthly_summary():
    config = load_config()
    notif = config.get('notifications', {})
    if not (notif.get('enabled', False) and notif.get('types', {}).get('monthly_summary', False)):
        return
    send_email(**format_monthly_summary())

def main():
    # Launch bots and monitor in threads
    procs = [
        threading.Thread(target=run_subprocess, args=(os.path.join(BASE_DIR, 'live_paper.py'), 'live_paper'), daemon=True),
        threading.Thread(target=run_subprocess, args=(os.path.join(BASE_DIR, 'live_trading.py'), 'live_trading'), daemon=True),
        threading.Thread(target=run_subprocess, args=(os.path.join(BASE_DIR, 'monitor.py'), 'monitor'), daemon=True),
    ]
    for t in procs:
        t.start()
    print("[RUN] Orchestrator started. Ctrl+C to exit.")
    try:
        while True:
            # Update OHLC data
            os.system(f'{sys.executable} {UPDATE_DATA_SCRIPT}')
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n[RUN] Orchestrator stopped by user.")

if __name__ == "__main__":
    # Allow activating/deactivating notifications from the command line
    if len(sys.argv) > 1:
        if sys.argv[1] == '--activate-notifications':
            activate_notifications()
            sys.exit(0)
        elif sys.argv[1] == '--deactivate-notifications':
            deactivate_notifications()
            sys.exit(0)
    # Example: send daily and monthly summary at startup (you can schedule this with a real scheduler)
    send_daily_summary()
    if datetime.now().day == 1:
        send_monthly_summary()
    main()
