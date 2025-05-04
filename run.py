import os
import sys
import time
import subprocess
import threading
import platform
import json
from notifications import send_test_emails, load_config, send_email, format_status_change, format_daily_summary, format_monthly_summary, format_dashboard_email
import monitor
from datetime import datetime, timedelta

# Configuración de rutas
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPDATE_DATA_SCRIPT = os.path.join(BASE_DIR, 'data', 'update_data.py')

# Función para liberar el puerto 5000
def kill_port_5000():
    try:
        if platform.system() == 'Windows':
            import subprocess
            # Buscar el PID que usa el puerto 5000
            result = subprocess.check_output('netstat -ano | findstr :5000', shell=True).decode()
            for line in result.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(':5000'):
                    pid = parts[-1]
                    print(f"[RUN] Killing process on port 5000 (PID {pid}) [Windows]")
                    subprocess.call(f'taskkill /PID {pid} /F', shell=True)
        else:
            import subprocess
            # Buscar el PID que usa el puerto 5000
            result = subprocess.check_output('lsof -i :5000 | grep LISTEN', shell=True).decode()
            for line in result.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 2:
                    pid = parts[1]
                    print(f"[RUN] Killing process on port 5000 (PID {pid}) [Linux]")
                    subprocess.call(f'kill -9 {pid}', shell=True)
    except Exception as e:
        print(f"[RUN] No se pudo liberar el puerto 5000 automáticamente: {e}")

# Función para lanzar subprocesos y reiniciarlos si se caen
def run_subprocess(cmd, name):
    while True:
        if name == 'monitor':
            kill_port_5000()
        print(f"[RUN] Lanzando {name}...")
        p = subprocess.Popen([sys.executable, cmd])
        p.wait()
        print(f"[WARN] {name} terminó. Reiniciando en 5s...")
        time.sleep(5)

def activar_notificaciones():
    config = load_config()
    if not config['notifications']['enabled']:
        config['notifications']['enabled'] = True
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print('[RUN] Notificaciones activadas. Enviando correos de prueba...')
        send_test_emails()
    else:
        print('[RUN] Las notificaciones ya estaban activadas.')

def desactivar_notificaciones():
    config = load_config()
    if config['notifications']['enabled']:
        config['notifications']['enabled'] = False
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print('[RUN] Notificaciones desactivadas.')
        send_email(**format_status_change(False))
    else:
        print('[RUN] Las notificaciones ya estaban desactivadas.')

def enviar_resumen_diario():
    config = load_config()
    notif = config.get('notifications', {})
    if not (notif.get('enabled', False) and notif.get('types', {}).get('daily_summary', False)):
        return
    # Obtener métricas reales de monitor.py
    try:
        metrics = monitor.metrics_api().get_json() if hasattr(monitor.metrics_api(), 'get_json') else monitor.metrics_api().json
    except Exception:
        metrics = None
    if not metrics:
        # Si no se pueden obtener, usar ceros
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

def enviar_resumen_mensual():
    config = load_config()
    notif = config.get('notifications', {})
    if not (notif.get('enabled', False) and notif.get('types', {}).get('monthly_summary', False)):
        return
    send_email(**format_monthly_summary())

def main():
    # Lanzar bots y monitor en threads
    procs = [
        threading.Thread(target=run_subprocess, args=(os.path.join(BASE_DIR, 'live_paper.py'), 'live_paper'), daemon=True),
        threading.Thread(target=run_subprocess, args=(os.path.join(BASE_DIR, 'live_trading.py'), 'live_trading'), daemon=True),
        threading.Thread(target=run_subprocess, args=(os.path.join(BASE_DIR, 'monitor.py'), 'monitor'), daemon=True),
    ]
    for t in procs:
        t.start()
    print("[RUN] Orquestador iniciado. Ctrl+C para salir.")
    try:
        while True:
            # Actualizar datos OHLC
            os.system(f'{sys.executable} {UPDATE_DATA_SCRIPT}')
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n[RUN] Orquestador detenido por el usuario.")

if __name__ == "__main__":
    # Permitir activar/desactivar notificaciones desde la línea de comandos
    if len(sys.argv) > 1:
        if sys.argv[1] == '--activar-notificaciones':
            activar_notificaciones()
            sys.exit(0)
        elif sys.argv[1] == '--desactivar-notificaciones':
            desactivar_notificaciones()
            sys.exit(0)
    # Ejemplo: enviar resumen diario y mensual al inicio (puedes programar esto con un scheduler real)
    enviar_resumen_diario()
    if datetime.now().day == 1:
        enviar_resumen_mensual()
    main()
