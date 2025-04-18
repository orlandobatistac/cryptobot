import requests
import time
from datetime import datetime, timedelta
import pandas as pd
import os
import logging
import signal
import sys

# Configure logging to debug.log
logging.basicConfig(
    filename="debug.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Output file (absolute path from project root)
output_file = os.path.join("data", "ohlc_data_60min_all_years.parquet")
print(f"Absolute path of OHLC file: {os.path.abspath(output_file)}")
logger.info(f"Absolute path of OHLC file: {os.path.abspath(output_file)}")
pair = "XXBTZUSD"
base_url = "https://api.kraken.com/0/public/Trades"

# Global variable to store new data
new_ohlc_data = []

# Get the last timestamp from the existing file
if os.path.exists(output_file):
    df_existing = pd.read_parquet(output_file)
    print(f"Existing file, rows: {len(df_existing)}")
    logger.info(f"Existing file, rows: {len(df_existing)}")
    if not df_existing.empty:
        # Ensure Timestamp is datetime
        if not pd.api.types.is_datetime64_any_dtype(df_existing["Timestamp"]):
            df_existing["Timestamp"] = pd.to_datetime(df_existing["Timestamp"])
        last_timestamp = df_existing["Timestamp"].max()
        print(f"Last timestamp found in file: {last_timestamp}")
        logger.info(f"Last timestamp found in file: {last_timestamp}")
        start_date = last_timestamp + pd.Timedelta(minutes=60)
    else:
        print("Empty file, starting from 2024-01-01")
        logger.info("Empty file, starting from 2024-01-01")
        start_date = datetime(2024, 1, 1)
else:
    print("File does not exist, starting from 2024-01-01")
    logger.info("File does not exist, starting from 2024-01-01")
    start_date = datetime(2024, 1, 1)

end_date = datetime.utcnow()

print(f"Updating data from {start_date} to {end_date}...")
logger.info(f"Updating data from {start_date} to {end_date}...")

def get_trades(pair, since=None):
    params = {"pair": pair}
    if since:
        params["since"] = since
    response = requests.get(base_url, params=params)
    data = response.json()
    if "error" in data and data["error"]:
        print(f"API error: {data['error']}")
        logger.error(f"API error: {data['error']}")
        return None, None
    return data["result"][pair], data["result"]["last"]

def trades_to_ohlc(trades):
    df_trades = pd.DataFrame(trades, columns=["price", "volume", "time", "buy_sell", "market_limit", "misc", "trade_id"])
    df_trades["time"] = pd.to_datetime(df_trades["time"].astype(float), unit="s")
    df_trades["price"] = df_trades["price"].astype(float)
    df_trades["volume"] = df_trades["volume"].astype(float)
    if df_trades.empty:
        return pd.DataFrame(columns=["Timestamp", "Open", "High", "Low", "Close", "VWAP", "Volume", "Count"])
    df_ohlc = df_trades.resample("60min", on="time").agg({
        "price": ["first", "max", "min", "last"],
        "volume": "sum"
    }).dropna()
    df_ohlc.columns = ["Open", "High", "Low", "Close", "Volume"]
    df_ohlc["Timestamp"] = df_ohlc.index
    vwap = (df_trades["price"] * df_trades["volume"]).sum() / df_trades["volume"].sum() if df_trades["volume"].sum() > 0 else 0
    df_ohlc["VWAP"] = vwap
    df_ohlc["Count"] = df_trades.resample("60min", on="time").size()
    return df_ohlc[["Timestamp", "Open", "High", "Low", "Close", "VWAP", "Volume", "Count"]]

def combine_and_save(new_ohlc, output_file):
    if new_ohlc is None or len(new_ohlc) == 0:
        print("No new data to save.")
        logger.info("No new data to save.")
        return
    if os.path.exists(output_file):
        df_existing = pd.read_parquet(output_file)
        df_combined = pd.concat([df_existing, new_ohlc]).drop_duplicates(subset="Timestamp").sort_values("Timestamp")
    else:
        df_combined = new_ohlc.drop_duplicates(subset="Timestamp").sort_values("Timestamp")
    df_combined.to_parquet(output_file, index=False)
    print(f"Data saved to '{output_file}'. Total points: {len(df_combined)}")
    logger.info(f"Data saved to '{output_file}'. Total points: {len(df_combined)}")

# Ctrl+C handler
def signal_handler(sig, frame):
    print("\nCtrl+C detected. Saving new data before exiting...")
    logger.info("Ctrl+C detected. Saving new data before exiting...")
    if new_ohlc_data:
        df_new = pd.concat(new_ohlc_data)
        combine_and_save(df_new, output_file)
    else:
        print("No new data to save.")
        logger.info("No new data to save.")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def download_new_data(start_date, end_date):
    start_timestamp = int(start_date.timestamp())
    end_timestamp = int(end_date.timestamp())
    current_since = start_timestamp
    all_ohlc_data = []
    max_timestamp_seen = start_timestamp
    print(f"Downloading new trades from {start_date} to {end_date}...")
    logger.info(f"Downloading new trades from {start_date} to {end_date}...")
    stuck_counter = 0
    last_since = None
    while True:
        print(f"Requesting trades from timestamp: {current_since}")
        logger.info(f"Requesting trades from timestamp: {current_since}")
        trades, last = get_trades(pair, current_since)
        if not trades:
            print("No trades received, stopping loop.")
            logger.info("No trades received, stopping loop.")
            break
        df_ohlc = trades_to_ohlc(trades)
        if not df_ohlc.empty:
            all_ohlc_data.append(df_ohlc)
            new_ohlc_data.append(df_ohlc)
            max_ts = int(df_ohlc["Timestamp"].iloc[-1].timestamp())
            max_timestamp_seen = max(max_timestamp_seen, max_ts)
            print(f"OHLC points generated: {len(df_ohlc)}, First timestamp: {df_ohlc['Timestamp'].iloc[0]}, Last timestamp: {df_ohlc['Timestamp'].iloc[-1]}")
            logger.info(f"OHLC points generated: {len(df_ohlc)}, First timestamp: {df_ohlc['Timestamp'].iloc[0]}, Last timestamp: {df_ohlc['Timestamp'].iloc[-1]}")
            print(df_ohlc[["Timestamp", "Open", "High", "Low", "Close"]])
            logger.info(f"Downloaded OHLC:\n{df_ohlc[['Timestamp', 'Open', 'High', 'Low', 'Close']].to_string(index=False)}")
        # Escape condition if 'last' does not advance after 5 attempts
        if last_since == last:
            stuck_counter += 1
            print(f"Warning: 'last' not advancing. Attempt {stuck_counter}/5")
            logger.warning(f"Warning: 'last' not advancing. Attempt {stuck_counter}/5")
            if stuck_counter >= 5:
                print("No new data. Exiting to avoid infinite loop.")
                logger.warning("No new data. Exiting to avoid infinite loop.")
                break
        else:
            stuck_counter = 0
        last_since = last
        current_since = last
        print(f"New since (ns): {current_since}")
        logger.info(f"New since (ns): {current_since}")
        if max_timestamp_seen >= end_timestamp:
            print(f"End of range reached: {end_date}")
            logger.info(f"End of range reached: {end_date}")
            break
        time.sleep(1)
    if all_ohlc_data:
        df_new = pd.concat(all_ohlc_data)
        df_new = df_new[(df_new["Timestamp"] >= pd.to_datetime(start_timestamp, unit="s")) & \
                        (df_new["Timestamp"] <= pd.to_datetime(end_timestamp, unit="s"))]
        combine_and_save(df_new, output_file)
        new_ohlc_data.clear()
    else:
        print("No new data to add.")
        logger.info("No new data to add.")

download_new_data(start_date, end_date)

# Show final information
if os.path.exists(output_file):
    df_final = pd.read_parquet(output_file)
    print(f"Total data points collected: {len(df_final)}")
    logger.info(f"Total data points collected: {len(df_final)}")
    print("Last 5 rows:")
    logger.info(f"Last 5 rows:\n{df_final.tail().to_string(index=False)}")
    print(df_final.tail())