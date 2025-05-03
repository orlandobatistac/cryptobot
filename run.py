import os
import sys
import time
import subprocess
import threading
import platform

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
    main()
