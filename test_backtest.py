from backtest import Backtester
from strategy import Strategy
import pandas as pd

# Cargar datos
df = pd.read_parquet("data/ohlc_data_60min_all_years.parquet")
df["Timestamp"] = pd.to_datetime(df["Timestamp"])
df.set_index("Timestamp", inplace=True)

# Crear estrategia
strategy = Strategy()

# Crear backtester
backtester = Backtester(
    data=df,
    strategy=strategy,
    initial_capital=1000.0,
    trade_fee=0.0026,
    investment_fraction=1.0,
    debug=True
)

# Ejecutar backtest
backtester.run()

# Generar métricas y gráficos
metrics = backtester.calculate_metrics()
print("Metrics:", metrics)
backtester.plot_results(output_folder="results/backtest")