import os
import sys
import time
import subprocess
import threading
import pandas as pd
import plotly.graph_objs as go
from datetime import datetime

# Configuración de rutas
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_1H = os.path.join(BASE_DIR, 'data', 'ohlc_data_60min_all_years.parquet')
CHARTS_DIR = os.path.join(BASE_DIR, 'metrics', 'charts')
CHART_FILE = os.path.join(CHARTS_DIR, 'btc_chart_live.html')
UPDATE_DATA_SCRIPT = os.path.join(BASE_DIR, 'data', 'update_data.py')

os.makedirs(CHARTS_DIR, exist_ok=True)

# Función para generar la gráfica desde el parquet
def generate_chart():
    try:
        df = pd.read_parquet(DATA_1H)
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
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df_1d.index,
            open=df_1d['Open'], high=df_1d['High'], low=df_1d['Low'], close=df_1d['Close'],
            name='Velas',
            increasing_line_color='#26a69a', decreasing_line_color='#ef5350',
            showlegend=False
        ))
        fig.add_trace(go.Scatter(
            x=df_1d.index, y=df_1d['EMA9'],
            line=dict(color='#ffd600', width=1.5),
            name='EMA 9',
        ))
        fig.add_trace(go.Scatter(
            x=df_1d.index, y=df_1d['EMA21'],
            line=dict(color='#00b0ff', width=1.5),
            name='EMA 21',
        ))
        fig.add_trace(go.Bar(
            x=df_1d.index, y=df_1d['Volume'],
            marker_color='#757575',
            name='Volumen',
            yaxis='y2',
            opacity=0.3
        ))
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            template='plotly_dark',
            margin=dict(l=10, r=10, t=40, b=30),
            height=700,
            yaxis=dict(title='Precio', side='right'),
            yaxis2=dict(
                title='Volumen',
                overlaying='y',
                side='left',
                showgrid=False,
                position=0.05,
                anchor='x',
                layer='below traces',
            ),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            title=f"BTC/USDT 1D - Actualizado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        AUTOREFRESH_HTML = """
        <script>setTimeout(function(){ location.reload(); }, 5000);</script>
        """
        fig.write_html(CHART_FILE, include_plotlyjs='cdn', full_html=True, post_script=AUTOREFRESH_HTML)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Gráfica actualizada.")
    except Exception as e:
        print(f"Error generando gráfica: {e}")

def run_subprocess(cmd, name):
    while True:
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
            # Generar gráfica
            generate_chart()
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n[RUN] Orquestador detenido por el usuario.")

if __name__ == "__main__":
    main()
