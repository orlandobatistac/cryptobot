import krakenex
import pandas as pd
import time
import sqlite3
import json
import subprocess
import os
from datetime import datetime, timedelta
from strategy import Strategy
from logger import logger
from colorama import init, Fore, Style

init(autoreset=True)

# Load configuration
def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

CONFIG = load_config()
STRATEGY_CONFIG = CONFIG["strategy"]
GENERAL_CONFIG = CONFIG["general"]

# Initialize Kraken connection
k = krakenex.API()

# Parameters
PAIR = "XXBTZUSD"  # BTC/USD
INTERVAL = 1  # minutes
DB_FILE = "paper_trades.db"

# Initialize database
def setup_database():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        type TEXT,
        price REAL,
        volume REAL,
        profit REAL,
        balance REAL
    )''')
    conn.commit()
    conn.close()

# Get latest OHLC from Kraken
def get_latest_candle(pair, interval):
    resp = k.query_public('OHLC', {'pair': pair, 'interval': interval})
    if resp["error"]:
        logger.error(f"Kraken API error: {resp['error']}")
        return None
    ohlc = resp["result"][list(resp["result"].keys())[0]]
    df = pd.DataFrame(ohlc, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
    # Rename columns to uppercase for Strategy compatibility
    df = df.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume"
    })
    return df

# Save trade to database
def save_trade(trade_type, price, volume, profit, balance):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO trades (timestamp, type, price, volume, profit, balance) VALUES (?, ?, ?, ?, ?, ?)",
              (datetime.utcnow().isoformat(), trade_type, price, volume, profit, balance))
    conn.commit()
    conn.close()

# Retrieve open position
def get_open_position():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Find the last 'buy' operation without a subsequent 'sell'
    c.execute('''
        SELECT id, timestamp, price, volume, balance
        FROM trades
        WHERE type = 'buy'
        ORDER BY id DESC LIMIT 1
    ''')
    last_buy = c.fetchone()
    if last_buy:
        buy_id, buy_time, buy_price, buy_volume, buy_balance = last_buy
        # Check if there is a 'sell' after this 'buy'
        c.execute('''
            SELECT id FROM trades
            WHERE type = 'sell' AND id > ?
            ORDER BY id ASC LIMIT 1
        ''', (buy_id,))
        sell = c.fetchone()
        if not sell:
            # There is an open position
            conn.close()
            return {
                "entry_price": buy_price,
                "volume": buy_volume,
                "entry_time": pd.to_datetime(buy_time),
                # Fee/slippage/spread is not stored here, but you could if you save them in the table
            }
    conn.close()
    return None

# Update parquet file
def update_parquet():
    print("Updating prices...")
    with open(os.devnull, 'w') as devnull:
        subprocess.run([
            "python", "data/update_data.py"
        ], check=True, stdout=devnull, stderr=devnull)

# Get real-time price
def get_realtime_price(pair):
    resp = k.query_public('Ticker', {'pair': pair})
    if resp["error"]:
        logger.error(f"Kraken API error: {resp['error']}")
        return None
    ticker = resp["result"][list(resp["result"].keys())[0]]
    return float(ticker["c"][0])  # 'c' is the closing price (last trade)

# Clear console
def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')

# Main paper trading loop
def main():
    setup_database()
    balance = GENERAL_CONFIG["initial_capital"]
    trade_fee = GENERAL_CONFIG["trade_fee"]
    investment_fraction = GENERAL_CONFIG["investment_fraction"]
    strategy = Strategy()
    # Retrieve open position if exists
    position = get_open_position()
    initial_summary = []
    if position:
        initial_summary.append(f"Recovered open position: Entry price ${position['entry_price']:.2f}, Volume {position['volume']:.6f}")
    initial_summary.append(f"Paper trading started. Initial balance: ${balance:.2f}")
    initial_summary.append("The strategy is evaluated automatically at the close of each daily candle (D1). Monitoring is real-time.")
    trades = []
    # If there is an open position, adjust balance to the last recorded
    if position:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('SELECT balance FROM trades ORDER BY id DESC LIMIT 1')
        last_balance = c.fetchone()
        if last_balance:
            balance = last_balance[0]
        conn.close()
    print(f"Paper trading started. Initial balance: ${balance:.2f}")
    print("The strategy is evaluated automatically at the close of each daily candle (D1). Monitoring is real-time.")
    cycle = 0
    last_resampled_time = None
    try:
        while True:
            cycle += 1
            # Update parquet with new 60min candles
            update_parquet()
            # Load parquet and resample to D1 (or config.json interval)
            df = pd.read_parquet("data/ohlc_data_60min_all_years.parquet")
            df["Timestamp"] = pd.to_datetime(df["Timestamp"])
            df.set_index("Timestamp", inplace=True)
            interval = CONFIG["data"]["interval"] if "data" in CONFIG and "interval" in CONFIG["data"] else "1D"
            df_resampled = df.resample(interval).agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()
            # Only show the real-time monitoring block, not the candle block
            clear_console()
            for line in initial_summary:
                print(line)
            if position is not None:
                realtime_price = get_realtime_price(PAIR)
                if realtime_price:
                    pl_realtime = (realtime_price - position['entry_price']) * position['volume']
                    pl_realtime -= (position['entry_price'] + realtime_price) * position['volume'] * trade_fee
                    equity = balance + (realtime_price * position['volume']) + pl_realtime
                    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                    pl_color = Fore.GREEN if pl_realtime >= 0 else Fore.RED
                    equity_color = Fore.GREEN if equity >= GENERAL_CONFIG["initial_capital"] else Fore.RED
                    print("\n" + "="*40)
                    print(f"CYCLE {cycle} | {now} UTC\n")
                    print(f"Open trade: {Fore.CYAN}BUY {position['volume']:.6f} BTC @ ${position['entry_price']:,.2f}{Style.RESET_ALL}")
                    print(f"Current BTCUSD:  {Fore.YELLOW}${realtime_price:,.2f}{Style.RESET_ALL}")
                    print(f"P/L real-time:  {pl_color}${pl_realtime:,.2f}{Style.RESET_ALL}")
                    print(f"Equity:         {equity_color}${equity:,.2f}{Style.RESET_ALL}")
                    print("="*40 + "\n")
            else:
                realtime_price = get_realtime_price(PAIR)
                print("\n" + "="*40)
                print(f"CYCLE {cycle} | {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
                print(f"No open trade currently.")
                if realtime_price:
                    print(f"Current BTCUSD:  {Fore.YELLOW}${realtime_price:,.2f}{Style.RESET_ALL}")
                print("="*40 + "\n")
            # Wait for the close of the next candle
            time.sleep(INTERVAL * 60)
    except KeyboardInterrupt:
        print("\nBot manually stopped by user (Ctrl+C).\n")
        logger.info("Bot manually stopped by user (Ctrl+C).")
        return

if __name__ == "__main__":
    main()
