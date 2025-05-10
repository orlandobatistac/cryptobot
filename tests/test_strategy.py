import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.strategy import Strategy
import pandas as pd

# Load data
df = pd.read_parquet("data/ohlc_data_60min_all_years.parquet")
df["Timestamp"] = pd.to_datetime(df["Timestamp"])
df.set_index("Timestamp", inplace=True)

# Create strategy
strategy = Strategy()

# Calculate indicators
strategy.calculate_indicators(df)

# Evaluate signals on the last candle
last_candle = df.iloc[-1]
entry_signal = strategy.entry_signal(last_candle, df, is_backtest=False)
print("Entry signal:", entry_signal)