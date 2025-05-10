import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.backtest import Backtester
from core.strategy import Strategy
import pandas as pd

# Load data
df = pd.read_parquet("data/ohlc_data_60min_all_years.parquet")
df["Timestamp"] = pd.to_datetime(df["Timestamp"])
df.set_index("Timestamp", inplace=True)

# Create strategy
strategy = Strategy()

# Create backtester
backtester = Backtester(
    data=df,
    strategy=strategy,
    initial_capital=1000.0,
    trade_fee=0.0026,
    investment_fraction=1.0,
    debug=True
)

# Run backtest
backtester.run()

# Generate metrics and plots
metrics = backtester.calculate_metrics()
print("Metrics:", metrics)
backtester.plot_results(output_folder="results/backtest")