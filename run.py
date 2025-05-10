import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Añadir mensaje de depuración inicial
print("[DEBUG] Iniciando CryptoBot - Depuración activada")

try:
    from utils.notifications import send_test_emails, load_config, send_email, format_status_change, format_daily_summary, format_monthly_summary, format_dashboard_email
    from monitoring import monitor
    from datetime import datetime, timedelta
    import threading
    import platform
    import time
    import logging
    import subprocess
    import json
    print("[DEBUG] Todas las importaciones realizadas correctamente")
except ImportError as e:
    print(f"[ERROR] Error al importar: {e}")
    sys.exit(1)

# Configura el nivel de registro para ver más información
logging.basicConfig(level=logging.INFO)
logging.getLogger().setLevel(logging.INFO)
print(f"[DEBUG] Nivel de logging configurado a INFO")

# Kill only python processes related to cryptobot before starting the orchestrator
print("[DEBUG] Verificando procesos existentes de CryptoBot")
if platform.system() == 'Linux':
    os.system("pkill -f 'python.*cryptobot'")
    time.sleep(2)
elif platform.system() == 'Windows':
    # Find processes that include 'cryptobot' in the command line
    try:
        import psutil
        count = 0
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] and 'python' in proc.info['name'].lower():
                    cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                    if 'cryptobot' in cmdline:
                        print(f"[DEBUG] Matando proceso PID {proc.info['pid']} ({cmdline})")
                        proc.kill()
                        count += 1
            except Exception as e:
                print(f"[ERROR] Error al examinar proceso: {e}")
        print(f"[DEBUG] Total de {count} procesos de CryptoBot terminados")
    except Exception as e:
        print(f"[ERROR] Error al manejar procesos: {e}")
    time.sleep(2)

# Configuration of routes
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPDATE_DATA_SCRIPT = os.path.join(BASE_DIR, 'data', 'update_data.py')
print(f"[DEBUG] BASE_DIR configurado como: {BASE_DIR}")
print(f"[DEBUG] UPDATE_DATA_SCRIPT configurado como: {UPDATE_DATA_SCRIPT}")

# Function to free port 5000
def kill_port_5000():
    print("[DEBUG] Intentando liberar puerto 5000")
    try:
        if platform.system() == 'Windows':
            import subprocess
            # Find the PID using port 5000
            print("[DEBUG] Ejecutando netstat para encontrar procesos usando puerto 5000")
            try:
                result = subprocess.check_output('netstat -ano | findstr :5000', shell=True).decode()
                if not result.strip():
                    print("[DEBUG] No se encontraron procesos usando el puerto 5000")
                    return
                for line in result.strip().split('\n'):
                    parts = line.split()
                    if len(parts) >= 5 and parts[1].endswith(':5000'):
                        pid = parts[-1]
                        print(f"[DEBUG] Matando proceso en puerto 5000 (PID {pid}) [Windows]")
                        subprocess.call(f'taskkill /PID {pid} /F', shell=True)
            except subprocess.CalledProcessError:
                print("[DEBUG] No se encontraron procesos usando el puerto 5000")
        else:
            import subprocess
            # Find the PID using port 5000
            try:
                result = subprocess.check_output('lsof -i :5000 | grep LISTEN', shell=True).decode()
                for line in result.strip().split('\n'):
                    parts = line.split()
                    if len(parts) >= 2:
                        pid = parts[1]
                        print(f"[DEBUG] Matando proceso en puerto 5000 (PID {pid}) [Linux]")
                        subprocess.call(f'kill -9 {pid}', shell=True)
            except subprocess.CalledProcessError:
                print("[DEBUG] No se encontraron procesos usando el puerto 5000")
    except Exception as e:
        print(f"[ERROR] No se pudo liberar automáticamente el puerto 5000: {e}")

# Function to launch subprocesses and restart them if they crash
def run_subprocess(cmd, name):
    print(f"[DEBUG] Configurando hilo para ejecutar {name}")
    while True:
        if name == 'monitor':
            kill_port_5000()
        print(f"[DEBUG] Lanzando {name}...")
        try:
            p = subprocess.Popen([sys.executable, cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print(f"[DEBUG] {name} iniciado con PID {p.pid}")
            
            # Configurar captura de salida en tiempo real
            def log_output(stream, prefix):
                for line in iter(stream.readline, b''):
                    print(f"[{prefix}] {line.decode().strip()}")
            
            t_stdout = threading.Thread(target=log_output, args=(p.stdout, f"{name}-STDOUT"))
            t_stderr = threading.Thread(target=log_output, args=(p.stderr, f"{name}-STDERR"))
            t_stdout.daemon = True
            t_stderr.daemon = True
            t_stdout.start()
            t_stderr.start()
            
            p.wait()
            exit_code = p.returncode
            print(f"[WARN] {name} finalizó con código de salida {exit_code}. Reiniciando en 5s...")
        except Exception as e:
            print(f"[ERROR] Error al iniciar {name}: {e}")
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
    print("[DEBUG] Iniciando función principal (main)")
    # Launch bots and monitor in threads
    procs = [
        threading.Thread(target=run_subprocess, args=(os.path.join(BASE_DIR, 'trading', 'live_paper.py'), 'live_paper'), daemon=True),
        threading.Thread(target=run_subprocess, args=(os.path.join(BASE_DIR, 'trading', 'live_trading.py'), 'live_trading'), daemon=True),
        threading.Thread(target=run_subprocess, args=(os.path.join(BASE_DIR, 'monitoring', 'monitor.py'), 'monitor'), daemon=True),
    ]
    print(f"[DEBUG] Se configuraron {len(procs)} hilos")
    
    for i, t in enumerate(procs):
        print(f"[DEBUG] Iniciando hilo {i+1}/{len(procs)}")
        t.start()
        time.sleep(1)  # Pequeña pausa entre inicios
    
    print("[DEBUG] Orquestador iniciado. Presiona Ctrl+C para salir.")
    try:
        while True:
            # Update OHLC data
            print("[DEBUG] Ejecutando script de actualización de datos OHLC")
            try:
                result = subprocess.run([sys.executable, UPDATE_DATA_SCRIPT], 
                                        capture_output=True, text=True, timeout=60)
                print(f"[DEBUG] Resultado de actualización de datos: {result.returncode}")
                if result.stdout.strip():
                    print(f"[DEBUG] Salida del script: {result.stdout.strip()}")
                if result.stderr.strip():
                    print(f"[ERROR] Error en script: {result.stderr.strip()}")
            except Exception as e:
                print(f"[ERROR] Error al actualizar datos OHLC: {e}")
            time.sleep(60)  # Aumentar tiempo entre actualizaciones para evitar sobrecarga
    except KeyboardInterrupt:
        print("\n[DEBUG] Orquestador detenido por el usuario.")

if __name__ == "__main__":
    print("[DEBUG] Punto de entrada __main__ alcanzado")
    # Allow activating/deactivating notifications from the command line
    if len(sys.argv) > 1:
        if sys.argv[1] == '--activate-notifications':
            activate_notifications()
            sys.exit(0)
        elif sys.argv[1] == '--deactivate-notifications':
            deactivate_notifications()
            sys.exit(0)
    
    print("[DEBUG] Verificando envío de resúmenes")
    # Example: send daily and monthly summary at startup (you can schedule this with a real scheduler)
    try:
        send_daily_summary()
        if datetime.now().day == 1:
            send_monthly_summary()
    except Exception as e:
        print(f"[ERROR] Error al enviar resúmenes: {e}")
    
    try:
        main()
    except Exception as e:
        print(f"[ERROR] Error fatal en la ejecución principal: {e}")
        import traceback
        traceback.print_exc()
