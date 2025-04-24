import krakenex
import pandas as pd
import os
import time
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    filename="debug.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Initialize Kraken API
k = krakenex.API()

# Parameters
PAIR = "XXBTZUSD"  # BTC/USD
INTERVAL = 60  # Interval in minutes (1 hour)
FILE_PATH = "data/ohlc_data_60min_all_years.parquet"

def fetch_trades(since_ns):
    """Fetch trades from Kraken API from a given timestamp (in nanoseconds)."""
    since = str(int(since_ns / 1_000_000_000))  # Convert to seconds
    logging.info(f"Requesting trades from timestamp: {since}")
    try:
        resp = k.query_public('Trades', {'pair': PAIR, 'since': since})
        if resp["error"]:
            logging.error(f"Kraken API error: {resp['error']}")
            return None, since_ns
        trades = resp["result"][PAIR]
        new_since_ns = resp["result"]["last"]
        return trades, int(new_since_ns)
    except Exception as e:
        logging.error(f"Error fetching trades: {e}")
        return None, since_ns

def trades_to_ohlc(trades, start_time, end_time, interval_minutes=INTERVAL):
    """
    Convert trades into OHLC candles with the specified interval.
    :param trades: List of trades obtained from the API.
    :param start_time: Start time for the trades.
    :param end_time: End time for the trades (current time).
    :param interval_minutes: Interval for resampling (in minutes).
    """
    if not trades:
        return pd.DataFrame()
    
    # Convert trades to DataFrame
    trade_data = []
    for trade in trades:
        timestamp = pd.to_datetime(float(trade[2]), unit='s')
        price = float(trade[0])
        volume = float(trade[1])
        trade_data.append({'Timestamp': timestamp, 'Price': price, 'Volume': volume})
    
    df = pd.DataFrame(trade_data)
    if df.empty:
        return df

    # Set the index as Timestamp
    df.set_index('Timestamp', inplace=True)

    # Filter trades within the time range
    df = df[(df.index >= start_time) & (df.index <= end_time)]
    if df.empty:
        return df

    # Resample to OHLC candles
    ohlc = df['Price'].resample(f'{interval_minutes}min').ohlc()
    volume = df['Volume'].resample(f'{interval_minutes}min').sum()
    vwap = (df['Price'] * df['Volume']).resample(f'{interval_minutes}min').sum() / volume
    count = df['Price'].resample(f'{interval_minutes}min').count()

    # Combine the data
    ohlc['VWAP'] = vwap
    ohlc['Volume'] = volume
    ohlc['Count'] = count

    # Rename columns
    ohlc = ohlc.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'})
    ohlc = ohlc.reset_index()

    return ohlc.dropna()

def main():
    # Get the absolute path of the Parquet file
    file_path = os.path.abspath(FILE_PATH)
    logging.info(f"Absolute path of OHLC file: {file_path}")

    # Check if the file exists and get the last timestamp
    if os.path.exists(file_path):
        df_existing = pd.read_parquet(file_path)
        logging.info(f"Existing file, rows: {len(df_existing)}")
        last_timestamp = df_existing['Timestamp'].max()
        logging.info(f"Last timestamp found in file: {last_timestamp}")
    else:
        df_existing = pd.DataFrame()
        last_timestamp = pd.to_datetime("2017-01-01")  # Arbitrary starting date
        logging.info("No existing file found. Starting from scratch.")

    # Define the time range for the update
    start_time = last_timestamp
    end_time = pd.to_datetime(datetime.utcnow())

    logging.info(f"Updating data from {start_time} to {end_time}...")
    logging.info(f"Downloading new trades from {start_time} to {end_time}...")

    # Convert the last timestamp to nanoseconds for Kraken API
    since_ns = int(start_time.timestamp() * 1_000_000_000)

    all_new_data = []
    max_attempts = 5
    attempt = 0

    while True:
        trades, new_since_ns = fetch_trades(since_ns)
        if trades is None:
            logging.info("No trades received, stopping loop.")
            break

        # Generate complete OHLC candles (1-hour intervals)
        new_ohlc = trades_to_ohlc(trades, start_time, end_time, interval_minutes=INTERVAL)
        if not new_ohlc.empty:
            logging.info(f"OHLC points generated: {len(new_ohlc)}, First timestamp: {new_ohlc['Timestamp'].min()}, Last timestamp: {new_ohlc['Timestamp'].max()}")
            logging.info("Downloaded OHLC:\n" + new_ohlc.to_string())
            all_new_data.append(new_ohlc)

        # Check if 'last' has advanced
        if new_since_ns == since_ns:
            attempt += 1
            logging.warning(f"Warning: 'last' not advancing. Attempt {attempt}/{max_attempts}")
            if attempt >= max_attempts:
                logging.warning("No new data. Exiting to avoid infinite loop.")
                break
        else:
            attempt = 0

        since_ns = new_since_ns
        logging.info(f"New since (ns): {since_ns}")

        # Exit if we have reached the current time
        if pd.to_datetime(since_ns / 1_000_000_000, unit='s') >= end_time:
            break

        time.sleep(1)  # Pause to avoid API limits

    # Generate partial candle up to current time
    if all_new_data:
        df_new = pd.concat(all_new_data, ignore_index=True)
        last_full_candle = df_new['Timestamp'].max()
        if last_full_candle < end_time:
            logging.info(f"Generating partial candle from {last_full_candle} to {end_time}...")
            since_ns = int(last_full_candle.timestamp() * 1_000_000_000)
            trades, _ = fetch_trades(since_ns)
            if trades:
                # Generate a partial candle with the remaining interval
                partial_ohlc = trades_to_ohlc(trades, last_full_candle, end_time, interval_minutes=(end_time - last_full_candle).total_seconds() / 60)
                if not partial_ohlc.empty:
                    logging.info(f"Partial OHLC points generated: {len(partial_ohlc)}, First timestamp: {partial_ohlc['Timestamp'].min()}, Last timestamp: {partial_ohlc['Timestamp'].max()}")
                    logging.info("Partial OHLC:\n" + partial_ohlc.to_string())
                    all_new_data.append(partial_ohlc)

    # Combine new and existing data
    if all_new_data:
        df_new = pd.concat(all_new_data, ignore_index=True)
        if not df_existing.empty:
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        else:
            df_combined = df_new

        # Save the updated file
        df_combined.to_parquet(file_path, engine='pyarrow')
        logging.info(f"Data saved to '{file_path}'. Total points: {len(df_combined)}")
        logging.info(f"Total data points collected: {len(df_combined)}")
        logging.info(f"Last 5 rows:\n{df_combined.tail().to_string()}")
    else:
        logging.info("No new data to add.")

if __name__ == "__main__":
    main()