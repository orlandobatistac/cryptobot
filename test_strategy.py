from strategy import Strategy
import pandas as pd

# Cargar datos
df = pd.read_parquet("data/ohlc_data_60min_all_years.parquet")
df["Timestamp"] = pd.to_datetime(df["Timestamp"])
df.set_index("Timestamp", inplace=True)

# Crear estrategia
strategy = Strategy()

# Calcular indicadores
strategy.calculate_indicators(df)

# Evaluar señales en la última vela
last_candle = df.iloc[-1]
entry_signal = strategy.entry_signal(last_candle, df, is_backtest=False)
print("Entry signal:", entry_signal)