import krakenex
import pandas as pd
import os
import time
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    filename="debug.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logging.basicConfig(level=logging.ERROR)
logging.getLogger().setLevel(logging.ERROR)

# Initialize the Kraken API
k = krakenex.API()

# Parameters
PAIR = "XXBTZUSD"  # BTC/USD
INTERVAL = 60  # Interval in minutes (1 hour)
FILE_PATH = "data/ohlc_data_60min_all_years.parquet"

def fetch_trades(since_ns):
    """
    Fetch trades from the Kraken API starting from a given timestamp (in nanoseconds).

    Args:
        since_ns (int): Timestamp in nanoseconds to start fetching trades from.

    Returns:
        tuple: (trades, new_since_ns) where trades is the list of trades and new_since_ns is the updated timestamp.
    """
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

def trades_to_ohlc(trades, start_time, end_time, interval_minutes=INTERVAL, is_partial=False):
    """
    Convert trades into OHLC candles with the specified interval.

    Args:
        trades (list): List of trades obtained from the API.
        start_time (datetime): Start date for the trades.
        end_time (datetime): End date for the trades (current time).
        interval_minutes (int): Interval for resampling (in minutes).
        is_partial (bool): If True, generate a partial candle with end_time as the timestamp.

    Returns:
        pandas.DataFrame: OHLC DataFrame with the specified interval.
    """
    # Convert trades to DataFrame
    trade_data = []
    for trade in trades:
        timestamp = pd.to_datetime(float(trade[2]), unit='s')
        price = float(trade[0])
        volume = float(trade[1])
        trade_data.append({'Timestamp': timestamp, 'Price': price, 'Volume': volume})
    
    df = pd.DataFrame(trade_data)
    if df.empty:
        # If there are no trades, return an empty DataFrame with the correct structure
        return pd.DataFrame(columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'VWAP', 'Volume', 'Count'])

    # Set the index as Timestamp
    df.set_index('Timestamp', inplace=True)

    # Filter trades within the time range
    df = df[(df.index >= start_time) & (df.index <= end_time)]

    if is_partial:
        # For partial candles, create a single OHLC entry with end_time as the timestamp
        ohlc = pd.DataFrame({
            'Timestamp': [end_time],
            'Open': [df['Price'].iloc[0] if not df.empty else float('nan')],
            'High': [df['Price'].max() if not df.empty else float('nan')],
            'Low': [df['Price'].min() if not df.empty else float('nan')],
            'Close': [df['Price'].iloc[-1] if not df.empty else float('nan')],
            'VWAP': [(df['Price'] * df['Volume']).sum() / df['Volume'].sum() if not df.empty and df['Volume'].sum() > 0 else float('nan')],
            'Volume': [df['Volume'].sum() if not df.empty else 0],
            'Count': [len(df)]
        })
    else:
        # Floor the start time to the nearest interval
        start_time = start_time.floor(f'{interval_minutes}min')
        # Create a time range with the specified interval
        time_range = pd.date_range(start=start_time, end=end_time, freq=f'{interval_minutes}min')
        # Resample to OHLC candles
        ohlc = df['Price'].resample(f'{interval_minutes}min', closed='left', label='left').ohlc()
        volume = df['Volume'].resample(f'{interval_minutes}min', closed='left', label='left').sum()
        vwap = (df['Price'] * df['Volume']).resample(f'{interval_minutes}min', closed='left', label='left').sum() / volume
        count = df['Price'].resample(f'{interval_minutes}min', closed='left', label='left').count()
        # Combine the data
        ohlc['VWAP'] = vwap
        ohlc['Volume'] = volume
        ohlc['Count'] = count
        # Rename columns
        ohlc = ohlc.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'})
        ohlc = ohlc.reset_index()

    # Deduplicate by keeping the last entry for each timestamp
    ohlc = ohlc.drop_duplicates(subset=['Timestamp'], keep='last')

    return ohlc.dropna()

def main():
    """
    Main function to update the OHLC Parquet file with new trades from Kraken.
    """
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
        last_timestamp = pd.to_datetime("2017-01-01")  # Arbitrary start date
        logging.info("No existing file found. Starting from scratch.")

    # Define the time range for the update
    start_time = last_timestamp
    end_time = pd.to_datetime(datetime.utcnow())

    logging.info(f"Updating data from {start_time} to {end_time}...")
    logging.info(f"Downloading new trades from {start_time} to {end_time}...")

    # Convert the last timestamp to nanoseconds for the Kraken API
    since_ns = int(start_time.timestamp() * 1_000_000_000)

    all_new_data = []
    max_attempts = 5
    attempt = 0
    previous_timestamps = set(df_existing['Timestamp']) if not df_existing.empty else set()

    while True:
        trades, new_since_ns = fetch_trades(since_ns)
        if trades is None:
            logging.info("No trades received, stopping loop.")
            break

        # Generate full OHLC candles (1-hour intervals)
        new_ohlc = trades_to_ohlc(trades, start_time, end_time, interval_minutes=INTERVAL)
        if not new_ohlc.empty:
            # Avoid duplicates by checking timestamps
            new_ohlc = new_ohlc[~new_ohlc['Timestamp'].isin(previous_timestamps)]
            if not new_ohlc.empty:
                logging.info(f"OHLC points generated: {len(new_ohlc)}, First timestamp: {new_ohlc['Timestamp'].min()}, Last timestamp: {new_ohlc['Timestamp'].max()}")
                logging.info("Downloaded OHLC:\n" + new_ohlc.to_string())
                all_new_data.append(new_ohlc)
                previous_timestamps.update(new_ohlc['Timestamp'])

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

        # If we've reached the current time, break
        if pd.to_datetime(since_ns / 1_000_000_000, unit='s') >= end_time:
            break

        time.sleep(1)  # Pause to avoid API rate limits

    # Generate partial candle up to the current time
    last_full_candle = last_timestamp
    if all_new_data:
        df_new = pd.concat(all_new_data, ignore_index=True)
        last_full_candle = df_new['Timestamp'].max()
    if last_full_candle < end_time:
        logging.info(f"Generating partial candle from {last_full_candle} to {end_time}...")
        since_ns = int(last_full_candle.timestamp() * 1_000_000_000)
        trades, _ = fetch_trades(since_ns)
        partial_ohlc = trades_to_ohlc(trades, last_full_candle, end_time, interval_minutes=INTERVAL, is_partial=True)
        if not partial_ohlc.empty:
            # Avoid duplicates
            partial_ohlc = partial_ohlc[~partial_ohlc['Timestamp'].isin(previous_timestamps)]
            if not partial_ohlc.empty:
                logging.info(f"Partial OHLC points generated: {len(partial_ohlc)}, First timestamp: {partial_ohlc['Timestamp'].min()}, Last timestamp: {partial_ohlc['Timestamp'].max()}")
                logging.info("Partial OHLC:\n" + partial_ohlc.to_string())
                all_new_data.append(partial_ohlc)
                previous_timestamps.update(partial_ohlc['Timestamp'])

    # Combine new and existing data
    if all_new_data:
        df_new = pd.concat(all_new_data, ignore_index=True)
        if not df_existing.empty:
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        else:
            df_combined = df_new

        # Deduplicate combined DataFrame
        df_combined = df_combined.drop_duplicates(subset=['Timestamp'], keep='last')

        # Save the updated file
        df_combined.to_parquet(file_path, engine='pyarrow')
        logging.info(f"Data saved to '{file_path}'. Total points: {len(df_combined)}")
        logging.info(f"Total data points collected: {len(df_combined)}")
        logging.info(f"Last 5 rows:\n{df_combined.tail().to_string()}")
    else:
        logging.info("No new data to add. Generating partial candle anyway...")
        # Generate a partial candle even if there are no new trades
        since_ns = int(last_timestamp.timestamp() * 1_000_000_000)
        trades, _ = fetch_trades(since_ns)
        partial_ohlc = trades_to_ohlc(trades, last_timestamp, end_time, interval_minutes=INTERVAL, is_partial=True)
        if not partial_ohlc.empty:
            partial_ohlc = partial_ohlc[~partial_ohlc['Timestamp'].isin(previous_timestamps)]
            if not partial_ohlc.empty:
                if not df_existing.empty:
                    df_combined = pd.concat([df_existing, partial_ohlc], ignore_index=True)
                else:
                    df_combined = partial_ohlc
                df_combined = df_combined.drop_duplicates(subset=['Timestamp'], keep='last')
                df_combined.to_parquet(file_path, engine='pyarrow')
                logging.info(f"Data saved to '{file_path}'. Total points: {len(df_combined)}")
                logging.info(f"Total data points collected: {len(df_combined)}")
                logging.info(f"Last 5 rows:\n{df_combined.tail().to_string()}")
            else:
                logging.info("No new partial data to add after deduplication.")
        else:
            logging.info("No partial data generated.")

if __name__ == "__main__":
    main()