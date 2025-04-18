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
import functools
import sys
import threading
from inputimeout import inputimeout, TimeoutOccurred
from dotenv import load_dotenv

init(autoreset=True)

# Cargar variables de entorno desde .env
load_dotenv()

# Retry decorator for robustness
def retry(ExceptionToCheck, tries=3, delay=2, backoff=2, logger=None):
    def deco_retry(f):
        @functools.wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    msg = f"{f.__name__}: {str(e)}, Retrying in {mdelay} seconds... ({mtries-1} tries left)"
                    if logger:
                        logger.warning(msg)
                    else:
                        print(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)
        return f_retry
    return deco_retry

# Load configuration
def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

CONFIG = load_config()
STRATEGY_CONFIG = CONFIG["strategy"]
GENERAL_CONFIG = CONFIG["general"]

# Initialize Kraken connection
k = krakenex.API()
k.key = os.getenv('KRAKEN_API_KEY')
k.secret = os.getenv('KRAKEN_API_SECRET')

# Parameters
PAIR = "XXBTZUSD"  # BTC/USD
INTERVAL = 1  # minutes
DB_FILE = "paper_trades.db"

# Minimum volumes per pair (extend this dictionary as needed)
MIN_VOLUME = {
    'XXBTZUSD': 0.0001,  # 0.0001 BTC
    # Add other pairs if needed
}

# Initialize threading lock for database operations
DB_LOCK = threading.Lock()

# Initialize database
def setup_database():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Add 'source' column if it doesn't exist
    # Add 'source' column if it doesn't exist
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        type TEXT,
        price REAL,
        volume REAL,
        profit REAL,
        balance REAL,
        source TEXT DEFAULT 'manual'
        balance REAL,
        source TEXT DEFAULT 'manual'
    )''')
    # Try to add the column if upgrading an old DB
    try:
        c.execute("ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'manual'")
    except sqlite3.OperationalError:
        pass  # Column already exists
    # Try to add the column if upgrading an old DB
    try:
        c.execute("ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'manual'")
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.commit()
    conn.close()

@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
def get_latest_candle(pair, interval):
    try:
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
        logger.info("Fetched latest OHLC candle from Kraken API.")
        return df
    except Exception as e:
        logger.error(f"Exception in get_latest_candle: {e}")
        raise

@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
def save_trade(trade_type, price, volume, profit, balance, source='manual'):
def save_trade(trade_type, price, volume, profit, balance, source='manual'):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DB_FILE, check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT INTO trades (timestamp, type, price, volume, profit, balance, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (datetime.utcnow().isoformat(), trade_type, price, volume, profit, balance, source))
            conn.commit()
            logger.info(f"Trade saved: {trade_type} {volume} @ {price}, profit: {profit}, balance: {balance}, source: {source}")
        with DB_LOCK:
            conn = sqlite3.connect(DB_FILE, check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT INTO trades (timestamp, type, price, volume, profit, balance, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (datetime.utcnow().isoformat(), trade_type, price, volume, profit, balance, source))
            conn.commit()
            logger.info(f"Trade saved: {trade_type} {volume} @ {price}, profit: {profit}, balance: {balance}, source: {source}")
    except Exception as e:
        logger.error(f"Exception in save_trade: {e}")
        raise
    finally:
        conn.close()

@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
def get_open_position():
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DB_FILE, check_same_thread=False)
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
                    logger.info(f"Open position found: entry {buy_price}, volume {buy_volume}")
                    return {
                        "entry_price": buy_price,
                        "volume": buy_volume,
                        "entry_time": pd.to_datetime(buy_time),
                        # Fee/slippage/spread is not stored here, but you could if you save them in the table
                    }
            conn.close()
        with DB_LOCK:
            conn = sqlite3.connect(DB_FILE, check_same_thread=False)
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
                    logger.info(f"Open position found: entry {buy_price}, volume {buy_volume}")
                    return {
                        "entry_price": buy_price,
                        "volume": buy_volume,
                        "entry_time": pd.to_datetime(buy_time),
                        # Fee/slippage/spread is not stored here, but you could if you save them in the table
                    }
            conn.close()
        return None
    except Exception as e:
        logger.error(f"Exception in get_open_position: {e}")
        raise
    finally:
        try:
            conn.close()
        except:
            pass

def update_parquet():
    update_script = os.path.join("data", "update_data.py")
    if not os.path.isfile(update_script):
        logger.warning(f"update_data.py not found at {update_script}. Skipping price update.")
        print(f"Warning: update_data.py not found at {update_script}. Skipping price update.")
        return
    update_script = os.path.join("data", "update_data.py")
    if not os.path.isfile(update_script):
        logger.warning(f"update_data.py not found at {update_script}. Skipping price update.")
        print(f"Warning: update_data.py not found at {update_script}. Skipping price update.")
        return
    print("Updating prices...")
    with open(os.devnull, 'w') as devnull:
        subprocess.run([
            "python", update_script
            "python", update_script
        ], check=True, stdout=devnull, stderr=devnull)

@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
def get_realtime_price(pair):
    try:
        resp = k.query_public('Ticker', {'pair': pair})
        if resp["error"]:
            logger.error(f"Kraken API error: {resp['error']}")
            return None
        ticker = resp["result"][list(resp["result"].keys())[0]]
        logger.info(f"Fetched real-time price: {ticker['c'][0]}")
        return float(ticker["c"][0])  # 'c' is the closing price (last trade)
    except Exception as e:
        logger.error(f"Exception in get_realtime_price: {e}")
        raise
    try:
        resp = k.query_public('Ticker', {'pair': pair})
        if resp["error"]:
            logger.error(f"Kraken API error: {resp['error']}")
            return None
        ticker = resp["result"][list(resp["result"].keys())[0]]
        logger.info(f"Fetched real-time price: {ticker['c'][0]}")
        return float(ticker["c"][0])  # 'c' is the closing price (last trade)
    except Exception as e:
        logger.error(f"Exception in get_realtime_price: {e}")
        raise

@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
def simulate_order(order_type, pair, volume, price=None, validate=True):
    """
    Simulate an order using Kraken's private API with validate=True.
    order_type: 'buy' or 'sell'
    pair: trading pair (e.g. 'XXBTZUSD')
    volume: amount to trade
    price: limit price (None for market)
    validate: True for simulation (paper), False for real
    Returns the API result if valid, None if fails.
    """
    # Check minimum volume
    min_vol = MIN_VOLUME.get(pair, 0)
    if volume < min_vol:
        logger.warning(f"Volume {volume} is less than the minimum allowed ({min_vol}) for {pair}.")
        print(f"[Simulation] Volume {volume} is less than the minimum allowed ({min_vol}) for {pair}.")
        return None
    order = {
        'pair': pair,
        'type': order_type,
        'ordertype': 'market' if price is None else 'limit',
        'volume': str(volume),
        'validate': validate
    }
    if price is not None:
        order['price'] = str(price)
    try:
        resp = k.query_private('AddOrder', order)
        if resp.get('error'):
            logger.warning(f"Kraken AddOrder error: {resp['error']}")
            print(f"[Simulation] Kraken AddOrder error: {resp['error']}")
            return None
        descr = resp.get('result', {}).get('descr', '')
        print(f"[Simulation] Order validated: {descr}")
        logger.info(f"Order simulation successful: {descr}")
        return resp['result']
    except Exception as e:
        logger.error(f"Exception in simulate_order: {e}")
        print(f"[Simulation] Error in simulate_order: {e}")
        return None

@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
def simulate_order(order_type, pair, volume, price=None, validate=True):
    """
    Simulate an order using Kraken's private API with validate=True.
    order_type: 'buy' or 'sell'
    pair: trading pair (e.g. 'XXBTZUSD')
    volume: amount to trade
    price: limit price (None for market)
    validate: True for simulation (paper), False for real
    Returns the API result if valid, None if fails.
    """
    # Check minimum volume
    min_vol = MIN_VOLUME.get(pair, 0)
    if volume < min_vol:
        logger.warning(f"Volume {volume} is less than the minimum allowed ({min_vol}) for {pair}.")
        print(f"[Simulation] Volume {volume} is less than the minimum allowed ({min_vol}) for {pair}.")
        return None
    order = {
        'pair': pair,
        'type': order_type,
        'ordertype': 'market' if price is None else 'limit',
        'volume': str(volume),
        'validate': validate
    }
    if price is not None:
        order['price'] = str(price)
    try:
        resp = k.query_private('AddOrder', order)
        if resp.get('error'):
            logger.warning(f"Kraken AddOrder error: {resp['error']}")
            print(f"[Simulation] Kraken AddOrder error: {resp['error']}")
            return None
        descr = resp.get('result', {}).get('descr', '')
        print(f"[Simulation] Order validated: {descr}")
        logger.info(f"Order simulation successful: {descr}")
        return resp['result']
    except Exception as e:
        logger.error(f"Exception in simulate_order: {e}")
        print(f"[Simulation] Error in simulate_order: {e}")
        return None

# Clear console
def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')

def input_with_timeout(prompt, timeout):
    try:
        return inputimeout(prompt=prompt, timeout=timeout)
    except TimeoutOccurred:
        return ''
    except (EOFError, KeyboardInterrupt):
        return ''

def input_with_timeout(prompt, timeout):
    try:
        return inputimeout(prompt=prompt, timeout=timeout)
    except TimeoutOccurred:
        return ''
    except (EOFError, KeyboardInterrupt):
        return ''

# Main paper trading loop
def main():
    setup_database()
    # Query last balance from DB (thread-safe)
    with DB_LOCK:
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT balance FROM trades ORDER BY id DESC LIMIT 1')
        last_balance = c.fetchone()
        conn.close()
    if last_balance:
        balance = last_balance[0]
    else:
        balance = GENERAL_CONFIG["initial_capital"]
    # Query last balance from DB (thread-safe)
    with DB_LOCK:
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT balance FROM trades ORDER BY id DESC LIMIT 1')
        last_balance = c.fetchone()
        conn.close()
    if last_balance:
        balance = last_balance[0]
    else:
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
    print(f"Paper trading started. Initial balance: ${balance:.2f}")
    print("The strategy is evaluated automatically at the close of each daily candle (D1). Monitoring is real-time.")
    print("\nAvailable commands:")
    print("[b] Buy at current price  ")
    print("[s] Sell (close position)  ")
    print("[q] Quit bot  \n")
    cycle = 0
    last_resampled_time = None

    try:
        while True:
            cycle += 1
            # Update parquet with new 60min candles
            try:
                update_parquet()
            except Exception as e:
                logger.error(f"Error updating parquet data: {e}")
                print(f"Warning: Could not update price data this cycle. Reason: {e}")
            try:
                update_parquet()
            except Exception as e:
                logger.error(f"Error updating parquet data: {e}")
                print(f"Warning: Could not update price data this cycle. Reason: {e}")
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
            # Ensure user_input is always defined
            user_input = ''
            if position is not None:
                realtime_price = get_realtime_price(PAIR)
                if realtime_price:
                    pl_realtime = (realtime_price - position['entry_price']) * position['volume']
                    pl_realtime -= (position['entry_price'] + realtime_price) * position['volume'] * trade_fee
                    equity = balance + (realtime_price * position['volume']) + pl_realtime
                    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                    pl_color = Fore.GREEN if pl_realtime >= 0 else Fore.RED
                    balance_color = Fore.GREEN if equity >= GENERAL_CONFIG["initial_capital"] else Fore.RED
                    print("\n" + Fore.CYAN + "="*40 + Style.RESET_ALL)
                    balance_color = Fore.GREEN if equity >= GENERAL_CONFIG["initial_capital"] else Fore.RED
                    print("\n" + Fore.CYAN + "="*40 + Style.RESET_ALL)
                    print(f"CYCLE {cycle} | {now} UTC\n")
                    print(f"Open trade: {Fore.CYAN}BUY {position['volume']:.6f} BTC @ ${position['entry_price']:,.2f} on {position['entry_time'].strftime('%Y-%m-%d %H:%M:%S')}{Style.RESET_ALL}")
                    print(f"Open trade: {Fore.CYAN}BUY {position['volume']:.6f} BTC @ ${position['entry_price']:,.2f} on {position['entry_time'].strftime('%Y-%m-%d %H:%M:%S')}{Style.RESET_ALL}")
                    print(f"Current BTCUSD:  {Fore.YELLOW}${realtime_price:,.2f}{Style.RESET_ALL}")
                    print(f"P/L real-time:  {pl_color}${pl_realtime:,.2f}{Style.RESET_ALL}")
                    print(f"Current Balance: {balance_color}${equity:,.2f}{Style.RESET_ALL}")
                    print(Fore.CYAN + "="*40 + Style.RESET_ALL + "\n")
                    print(f"Current Balance: {balance_color}${equity:,.2f}{Style.RESET_ALL}")
                    print(Fore.CYAN + "="*40 + Style.RESET_ALL + "\n")
            else:
                realtime_price = get_realtime_price(PAIR)
                print("\n" + Fore.CYAN + "="*40 + Style.RESET_ALL)
                print("\n" + Fore.CYAN + "="*40 + Style.RESET_ALL)
                print(f"CYCLE {cycle} | {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
                print(f"Open trade: {Fore.LIGHTBLACK_EX}No open trade currently.{Style.RESET_ALL}")
                print(f"Open trade: {Fore.LIGHTBLACK_EX}No open trade currently.{Style.RESET_ALL}")
                if realtime_price:
                    print(f"Current BTCUSD:  {Fore.YELLOW}${realtime_price:,.2f}{Style.RESET_ALL}")
                else:
                    print("Current BTCUSD:  N/A")
                print(f"P/L real-time: {Fore.LIGHTBLACK_EX}N/A{Style.RESET_ALL}")
                print(f"Current Balance: {Fore.GREEN if balance >= GENERAL_CONFIG['initial_capital'] else Fore.RED}${balance:,.2f}{Style.RESET_ALL}")
                print(Fore.CYAN + "="*40 + Style.RESET_ALL + "\n")

            # --- AUTO STRATEGY EVALUATION ---
            print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Evaluating strategy...\n")
            strategy.calculate_indicators(df_resampled)
            last_candle = df_resampled.iloc[-1]
            auto_action = None
            # Auto BUY
            if not position and strategy.entry_signal(last_candle, df_resampled):
                auto_action = 'buy'
                print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Entry signal detected. Executing auto-buy.")
                auto_price = get_realtime_price(PAIR) or last_candle['Close']
                invest_amount = balance * investment_fraction
                if invest_amount >= 1e-8 and balance > 0:
                    volume = invest_amount / auto_price
                    # Validate order with Kraken (simulation)
                    order_result = simulate_order('buy', PAIR, volume, price=None, validate=True)
                    if order_result:
                        balance -= invest_amount
                        # Use datetime.utcnow() if using realtime price, else last_candle time
                        if auto_price == last_candle['Close']:
                            entry_time = last_candle.name.to_pydatetime() if hasattr(last_candle.name, 'to_pydatetime') else last_candle.name
                        else:
                            entry_time = datetime.utcnow()
                        save_trade('buy', auto_price, volume, 0, balance, source='auto')
                        position = {
                            'entry_price': auto_price,
                            'volume': volume,
                            'entry_time': entry_time
                        }
                        print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Auto BUY: {volume:.6f} BTC @ ${auto_price:,.2f}")
                    else:
                        print(f"[AUTO] Buy order not validated. Trade not executed.")
                        logger.warning("[AUTO] Buy order not validated. Trade not executed.")
            # Auto SELL
            elif position and strategy.exit_signal(last_candle, df_resampled):
                auto_action = 'sell'
                print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Exit signal detected. Executing auto-sell.")
                auto_price = get_realtime_price(PAIR) or last_candle['Close']
                pl = (auto_price - position['entry_price']) * position['volume']
                pl -= (position['entry_price'] + auto_price) * position['volume'] * trade_fee
                # Validate order with Kraken (simulation)
                order_result = simulate_order('sell', PAIR, position['volume'], price=None, validate=True)
                if order_result:
                    balance += (auto_price * position['volume']) + pl
                    save_trade('sell', auto_price, position['volume'], pl, balance, source='auto')
                    print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Auto SELL: {position['volume']:.6f} BTC @ ${auto_price:,.2f} | P/L: ${pl:,.2f}")
                    position = None
                else:
                    print(f"[AUTO] Sell order not validated. Trade not executed.")
                    logger.warning("[AUTO] Sell order not validated. Trade not executed.")

            # Always show available commands and get user input
            print("Available commands:")
            print("[b] Buy at current price  ")
            print("[s] Sell (close position)  ")
            print("[q] Quit bot  \n")
            user_input = input_with_timeout("Press Enter after choosing an option: ", INTERVAL * 60).strip().lower()
            print()  # Ensure a blank line after input for clarity

            if user_input == 'q':
                print("\nBot stopped by user (q).\n")
                logger.info("Bot stopped by user (q).")
                break
            elif user_input == 'b' and not position:
                # Simulate buy
                if not realtime_price:
                    print("Cannot buy: real-time price unavailable.")
                elif balance <= 0:
                    print("Insufficient balance to buy.")
                elif balance <= 0:
                    print("Insufficient balance to buy.")
                else:
                    invest_amount = balance * investment_fraction
                    if invest_amount < 1e-8:  # Prevent extremely small trades
                        print("Investment amount too small to execute a trade.")
                    else:
                        volume = invest_amount / realtime_price
                        # Validate order with Kraken (simulation)
                        order_result = simulate_order('buy', PAIR, volume, price=None, validate=True)
                        if order_result:
                            balance -= invest_amount
                            save_trade('buy', realtime_price, volume, 0, balance, source='manual')
                            position = {
                                'entry_price': realtime_price,
                                'volume': volume,
                                'entry_time': datetime.utcnow()
                            }
                            print(f"Simulated BUY: {volume:.6f} BTC @ ${realtime_price:,.2f}")
                            logger.info(f"Simulated BUY: {volume:.6f} BTC @ ${realtime_price:,.2f}")
                        else:
                            print("[MANUAL] Buy order not validated. Trade not executed.")
                            logger.warning("[MANUAL] Buy order not validated. Trade not executed.")
            elif user_input == 's' and position:
                # Simulate sell
                if not realtime_price:
                    print("Cannot sell: real-time price unavailable.")
                else:
                    pl = (realtime_price - position['entry_price']) * position['volume']
                    pl -= (position['entry_price'] + realtime_price) * position['volume'] * trade_fee
                    # Validate order with Kraken (simulation)
                    order_result = simulate_order('sell', PAIR, position['volume'], price=None, validate=True)
                    if order_result:
                        balance += (realtime_price * position['volume']) + pl
                        save_trade('sell', realtime_price, position['volume'], pl, balance, source='manual')
                        print(f"Simulated SELL: {position['volume']:.6f} BTC @ ${realtime_price:,.2f} | P/L: ${pl:,.2f}")
                        logger.info(f"Simulated SELL: {position['volume']:.6f} BTC @ ${realtime_price:,.2f} | P/L: ${pl:,.2f}")
                        position = None
                    else:
                        print("[MANUAL] Sell order not validated. Trade not executed.")
                        logger.warning("[MANUAL] Sell order not validated. Trade not executed.")
            elif user_input == 'b' and position:
                print("You already have an open position. Close it before buying again.")
            elif user_input == 's' and not position:
                print("No open position to sell.")
            # else: just continue

            # If user_input was empty (timeout), just continue to next cycle
            # Wait for the configured interval before next cycle
            time.sleep(INTERVAL * 60)
    except KeyboardInterrupt:
        print("\nBot manually stopped by user (Ctrl+C).\n")
        logger.info("Bot manually stopped by user (Ctrl+C).")
        return

if __name__ == "__main__":
    main()
