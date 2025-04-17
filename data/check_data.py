import pandas as pd
import requests
from datetime import datetime
import os
import logging

# --- Configuration ---
parquet_file = os.path.join("data", "ohlc_data_60min_all_years.parquet")
print(f"Absolute path of OHLC file: {os.path.abspath(parquet_file)}")
kraken_api_url = "https://api.kraken.com/0/public/OHLC"
kraken_pair = "XXBTZUSD"
kraken_interval = 60  # minutes

# --- Functions ---

def inspect_parquet(file_path):
    """Inspects the Parquet file and displays its metadata and data."""
    try:
        print("\n--- Inspecting Parquet File ---")
        df = pd.read_parquet(file_path)
        print(f"File: {file_path}")
        print(f"Number of rows: {len(df)}")
        print(f"Columns: {df.columns.tolist()}")
        print(f"Data types:\n{df.dtypes}")
        print("\nFirst 5 rows:")
        print(df.head())
        print("\nLast 5 rows:")
        print(df.tail())
        print("\nDescriptive statistics:")
        print(df.describe())
        print("\nNull values per column:")
        print(df.isnull().sum())
        print("\nDuplicated values:")
        print(df.duplicated().sum())
        print("\nInfinite values per column:")
        print(df.isin([float('inf'), float('-inf')]).sum())
        print("\n--- End Parquet Inspection ---\n")
        return df
    except FileNotFoundError:
        print(f"Error: File not found: {file_path}")
        return None
    except Exception as e:
        print(f"Error reading Parquet file: {e}")
        return None

def get_kraken_data(pair, interval, since=None):
    """Gets OHLC data from the Kraken API."""
    params = {"pair": pair, "interval": interval}
    if since:
        params["since"] = since
    try:
        print("\n--- Getting Data from Kraken API ---")
        response = requests.get(kraken_api_url, params=params)
        response.raise_for_status()  # Raise exception for HTTP errors
        data = response.json()
        if "error" in data and data["error"]:
            print(f"Kraken API error: {data['error']}")
            return None
        ohlc_data = data["result"][pair]
        df = pd.DataFrame(ohlc_data, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
        df[["open", "high", "low", "close", "vwap", "volume"]] = df[["open", "high", "low", "close", "vwap", "volume"]].apply(pd.to_numeric)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        print(f"Kraken API data (first 5 rows):\n{df.head()}")
        print(f"\nKraken API data (last 5 rows):\n{df.tail()}")
        print("\n--- End Kraken API Data ---\n")
        return df
    except requests.exceptions.RequestException as e:
        print(f"Connection error to Kraken API: {e}")
        return None
    except Exception as e:
        print(f"Error processing Kraken API response: {e}")
        return None

# --- Execution ---

# Inspect the Parquet file
df_parquet = inspect_parquet(parquet_file)

# Get data from the Kraken API (example)
# You can adjust 'since' to get data for a specific period
df_kraken = get_kraken_data(kraken_pair, kraken_interval, since=datetime(2024, 1, 1).timestamp())

# --- End of Script ---
