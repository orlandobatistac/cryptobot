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
import requests
from collections import deque

init(autoreset=True)

# Load environment variables from .env
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
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        type TEXT,
        price REAL,
        volume REAL,
        profit REAL,
        balance REAL,
        fee REAL DEFAULT 0,
        source TEXT DEFAULT 'manual'
    )''')
    # Try to add the columns if upgrading an old DB
    try:
        c.execute("ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'manual'")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        c.execute("ALTER TABLE trades ADD COLUMN fee REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.commit()
    conn.close()

RATE_LIMIT_THRESHOLD = 2  # You can adjust this value as needed
RATE_LIMIT_SLEEP = 3     # Seconds to wait if threshold is reached

# --- Local rate limit tracking ---
RATE_LIMIT_POINTS = 15  # Kraken standard limit
RATE_LIMIT_WINDOW = 3   # Time window in seconds

# Points per endpoint (based on experience/community)
ENDPOINT_POINTS = {
    'AddOrder': 2,  # Can be 2-4 according to docs, conservative
    'CancelOrder': 1,
    'Ticker': 1,
    'OHLC': 1,
    'TradeBalance': 1,
    'AssetPairs': 1,
    # Add other endpoints here if needed
}

api_call_times = deque()
api_call_points = deque()

def rate_limit_throttle(endpoint):
    now = time.time()
    # Remove calls outside the window
    while api_call_times and now - api_call_times[0] > RATE_LIMIT_WINDOW:
        api_call_times.popleft()
        api_call_points.popleft()
    # Calculate used points
    used_points = sum(api_call_points)
    endpoint_points = ENDPOINT_POINTS.get(endpoint, 1)
    if used_points + endpoint_points > RATE_LIMIT_POINTS:
        sleep_time = RATE_LIMIT_WINDOW - (now - api_call_times[0])
        logger.warning(f"Local rate limit: {used_points} points used. Pausing {sleep_time:.2f}s to avoid lockout.")
        time.sleep(max(sleep_time, 0.1))
    # Register the call
    api_call_times.append(time.time())
    api_call_points.append(endpoint_points)

def query_public_throttled(endpoint, *args, **kwargs):
    rate_limit_throttle(endpoint)
    return k.query_public(endpoint, *args, **kwargs)

def query_private_throttled(endpoint, *args, **kwargs):
    rate_limit_throttle(endpoint)
    return k.query_private(endpoint, *args, **kwargs)

@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
def get_latest_candle(pair, interval):
    try:
        resp = query_public_throttled('OHLC', {'pair': pair, 'interval': interval})
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
def save_trade(trade_type, price, volume, profit, balance, fee=0, source='manual'):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DB_FILE, check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT INTO trades (timestamp, type, price, volume, profit, balance, fee, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (datetime.utcnow().isoformat(), trade_type, price, volume, profit, balance, fee, source))
            conn.commit()
            logger.info(f"Trade saved: {trade_type} {volume} @ {price}, profit: {profit}, balance: {balance}, fee: {fee}, source: {source}")
    except Exception as e:
        logger.error(f"Exception in save_trade: {e}")
        raise
    finally:
        conn.close()

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
    print("Updating prices...")
    with open(os.devnull, 'w') as devnull:
        subprocess.run([
            "python", update_script
        ], check=True, stdout=devnull, stderr=devnull)

@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
def get_realtime_price(pair):
    try:
        resp = query_public_throttled('Ticker', {'pair': pair})
        if resp["error"]:
            logger.error(f"Kraken API error: {resp['error']}")
            return None
        ticker = resp["result"][list(resp["result"].keys())[0]]
        logger.info(f"Fetched real-time price: {ticker['c'][0]}")
        return float(ticker["c"][0])  # 'c' is the closing price (last trade)
    except Exception as e:
        logger.error(f"Exception in get_realtime_price: {e}")
        raise

def get_estimated_order_fee(pair, ordertype, volume):
    """
    Estimate the fee for a specific order using the Fee endpoint.
    Returns the fee rate (as a float, e.g., 0.0026 for 0.26%) or None if unavailable.
    """
    if not k.key or not k.secret:
        return None
    try:
        resp = query_private_throttled('Fee', {'pair': pair, 'type': ordertype, 'ordertype': ordertype, 'volume': str(volume)})
        if resp.get('error'):
            logger.warning(f"Kraken Fee endpoint error: {resp['error']}")
            return None
        # The fee is usually in resp['result']['fee'] as a percentage (e.g., 0.26)
        fee_percent = resp.get('result', {}).get('fee')
        if fee_percent is not None:
            return float(fee_percent) / 100.0  # Convert percent to fraction
    except Exception as e:
        logger.error(f"Error querying order fee: {e}")
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
    Returns a dict with simulated order status and details.
    """
    # Estimate fee for this order
    estimated_fee = get_estimated_order_fee(pair, order_type, volume)
    # Check if API keys are present; if not, skip validation and simulate order
    if not k.key or not k.secret:
        logger.warning("Kraken API keys not configured. Skipping order validation.")
        print(f"[Simulation] Kraken API keys not configured. Skipping order validation.")
        # Simulate immediate fill for market orders in paper trading
        return {
            'descr': f"{order_type} {volume} {pair} @ market (no validation)",
            'status': 'filled',
            'filled_volume': volume,
            'remaining_volume': 0.0,
            'fee': estimated_fee if estimated_fee is not None else GENERAL_CONFIG["trade_fee"]
        }
    # Check minimum volume
    min_vol = get_min_volume(pair)
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
        resp = query_private_throttled('AddOrder', order)
        if resp.get('error'):
            logger.warning(f"Kraken AddOrder error: {resp['error']}")
            print(f"[Simulation] Kraken AddOrder error: {resp['error']}")
            return None
        descr = resp.get('result', {}).get('descr', '')
        print(f"[Simulation] Order validated: {descr}")
        logger.info(f"Order simulation successful: {descr}")
        # Simulate immediate fill for market orders in paper trading
        if validate:
            return {
                'descr': descr,
                'status': 'filled',
                'filled_volume': volume,
                'remaining_volume': 0.0,
                'fee': estimated_fee if estimated_fee is not None else GENERAL_CONFIG["trade_fee"]
            }
        # In real trading, you should use QueryOrders to check the actual order status.
        # Example:
        # order_id = resp['result'].get('txid', [None])[0]
        # if order_id:
        #     order_status_resp = query_private_throttled('QueryOrders', {'txid': order_id})
        #     # order_status_resp['result'][order_id] contains status, filled volume, remaining volume, etc.
        #     # Example of handling partial fill:
        #     # status = order_status_resp['result'][order_id]['status']
        #     # filled = float(order_status_resp['result'][order_id]['vol_exec'])
        #     # remaining = float(order_status_resp['result'][order_id]['vol']) - filled
        #     # return {
        #     #     'descr': descr,
        #     #     'status': status,
        #     #     'filled_volume': filled,
        #     #     'remaining_volume': remaining,
        #     #     'fee': ... # extract fee if available
        #     # }
        return resp['result']
    except Exception as e:
        logger.error(f"Exception in simulate_order: {e}")
        print(f"[Simulation] Error in simulate_order: {e}")
        return None

def get_dynamic_trade_fee():
    """
    Query the real fee of the Kraken account using the TradeBalance endpoint.
    If there are no API keys, return None.
    """
    if not k.key or not k.secret:
        return None
    try:
        resp = query_private_throttled('TradeBalance')
        if resp.get('error'):
            logger.warning(f"Kraken TradeBalance error: {resp['error']}")
            return None
        fee = resp.get('result', {}).get('fee')
        if fee is not None:
            return float(fee)
    except Exception as e:
        logger.error(f"Error querying dynamic fee: {e}")
    return None

def get_min_volume(pair):
    resp = query_public_throttled('AssetPairs', {'pair': pair})
    if resp['error']:
        logger.warning(f"Failed to fetch min volume for {pair}: {resp['error']}")
        return 0
    return float(resp['result'][pair]['ordermin'])

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
            # Update trade_fee dynamically if possible
            dynamic_fee = get_dynamic_trade_fee()
            if dynamic_fee is not None:
                trade_fee = dynamic_fee
            # Update parquet with new 60min candles
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
                    print(f"CYCLE {cycle} | {now} UTC\n")
                    print(f"Open trade: {Fore.CYAN}BUY {position['volume']:.6f} BTC @ ${position['entry_price']:,.2f} on {position['entry_time'].strftime('%Y-%m-%d %H:%M:%S')}{Style.RESET_ALL}")
                    print(f"Current BTCUSD:  {Fore.YELLOW}${realtime_price:,.2f}{Style.RESET_ALL}")
                    print(f"P/L real-time:  {pl_color}${pl_realtime:,.2f}{Style.RESET_ALL}")
                    print(f"Current Balance: {balance_color}${equity:,.2f}{Style.RESET_ALL}")
                    print(Fore.CYAN + "="*40 + Style.RESET_ALL + "\n")
            else:
                realtime_price = get_realtime_price(PAIR)
                print("\n" + Fore.CYAN + "="*40 + Style.RESET_ALL)
                print(f"CYCLE {cycle} | {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
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
                    # Use limit order at auto_price
                    order_result = simulate_order('buy', PAIR, volume, price=auto_price, validate=True)
                    if order_result:
                        balance -= invest_amount
                        if auto_price == last_candle['Close']:
                            entry_time = last_candle.name.to_pydatetime() if hasattr(last_candle.name, 'to_pydatetime') else last_candle.name
                        else:
                            entry_time = datetime.utcnow()
                        save_trade('buy', auto_price, volume, 0, balance, fee=order_result.get('fee', trade_fee), source='auto')
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
                # Use limit order at auto_price
                order_result = simulate_order('sell', PAIR, position['volume'], price=auto_price, validate=True)
                if order_result:
                    balance += (auto_price * position['volume']) + pl
                    save_trade('sell', auto_price, position['volume'], pl, balance, fee=order_result.get('fee', trade_fee), source='auto')
                    print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Auto SELL: {position['volume']:.6f} BTC @ ${auto_price:,.2f} | P/L: ${pl:,.2f}")
                    position = None
                else:
                    print(f"[AUTO] Sell order not validated. Trade not executed.")
                    logger.warning("[AUTO] Sell order not validated. Trade not executed.")

            # --- HÍBRIDO: TIMEOUT Y RESPALDO A ORDEN DE MERCADO EN AUTO ---
            # Solo aplica para auto-trading (no manual)
            # Si hubo acción auto (buy/sell) pero la orden límite no se ejecutó, intenta respaldo a mercado
            if auto_action in ['buy', 'sell'] and (order_result is None):
                print(f"[AUTO] Orden límite no ejecutada. Esperando timeout para respaldo a mercado...")
                logger.warning(f"[AUTO] Orden límite no ejecutada. Esperando timeout para respaldo a mercado...")
                timeout_seconds = 120  # 2 minutos
                time.sleep(timeout_seconds)
                # Intentar orden de mercado (sin precio)
                print(f"[AUTO] Intentando orden de mercado de respaldo...")
                logger.info(f"[AUTO] Intentando orden de mercado de respaldo...")
                if auto_action == 'buy':
                    market_price = get_realtime_price(PAIR) or last_candle['Close']
                    invest_amount = balance * investment_fraction
                    if invest_amount >= 1e-8 and balance > 0:
                        volume = invest_amount / market_price
                        market_order = simulate_order('buy', PAIR, volume, price=None, validate=True)
                        if market_order:
                            balance -= invest_amount
                            entry_time = datetime.utcnow()
                            save_trade('buy', market_price, volume, 0, balance, fee=market_order.get('fee', trade_fee), source='auto')
                            position = {
                                'entry_price': market_price,
                                'volume': volume,
                                'entry_time': entry_time
                            }
                            print(f"[AUTO] Orden de mercado ejecutada: {volume:.6f} BTC @ ${market_price:,.2f}")
                            logger.info(f"[AUTO] Orden de mercado ejecutada: {volume:.6f} BTC @ ${market_price:,.2f}")
                        else:
                            print(f"[AUTO] Orden de mercado de respaldo fallida.")
                            logger.warning(f"[AUTO] Orden de mercado de respaldo fallida.")
                elif auto_action == 'sell' and position:
                    market_price = get_realtime_price(PAIR) or last_candle['Close']
                    pl = (market_price - position['entry_price']) * position['volume']
                    pl -= (position['entry_price'] + market_price) * position['volume'] * trade_fee
                    market_order = simulate_order('sell', PAIR, position['volume'], price=None, validate=True)
                    if market_order:
                        balance += (market_price * position['volume']) + pl
                        save_trade('sell', market_price, position['volume'], pl, balance, fee=market_order.get('fee', trade_fee), source='auto')
                        print(f"[AUTO] Orden de mercado ejecutada: {position['volume']:.6f} BTC @ ${market_price:,.2f} | P/L: ${pl:,.2f}")
                        logger.info(f"[AUTO] Orden de mercado ejecutada: {position['volume']:.6f} BTC @ ${market_price:,.2f} | P/L: ${pl:,.2f}")
                        position = None
                    else:
                        print(f"[AUTO] Orden de mercado de respaldo fallida.")
                        logger.warning(f"[AUTO] Orden de mercado de respaldo fallida.")

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
                else:
                    invest_amount = balance * investment_fraction
                    if invest_amount < 1e-8:  # Prevent extremely small trades
                        print("Investment amount too small to execute a trade.")
                    else:
                        volume = invest_amount / realtime_price
                        # Use limit order at realtime_price
                        order_result = simulate_order('buy', PAIR, volume, price=realtime_price, validate=True)
                        if order_result:
                            balance -= invest_amount
                            fee_real = realtime_price * volume * trade_fee
                            save_trade('buy', realtime_price, volume, 0, balance, fee=fee_real, source='manual')
                            position = {
                                'entry_price': realtime_price,
                                'volume': volume,
                                'entry_time': datetime.utcnow()
                            }
                            print(f"Simulated BUY: {volume:.6f} BTC @ ${realtime_price:,.2f}")
                            logger.info(f"Simulated BUY: {volume:.6f} BTC @ ${realtime_price:,.2f}")
                            # Short delay and immediate next cycle
                            time.sleep(4)
                            continue
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
                    # Use limit order at realtime_price
                    order_result = simulate_order('sell', PAIR, position['volume'], price=realtime_price, validate=True)
                    if order_result:
                        balance += (realtime_price * position['volume']) + pl
                        fee_real = realtime_price * position['volume'] * trade_fee
                        save_trade('sell', realtime_price, position['volume'], pl, balance, fee=fee_real, source='manual')
                        print(f"Simulated SELL: {position['volume']:.6f} BTC @ ${realtime_price:,.2f} | P/L: ${pl:,.2f}")
                        logger.info(f"Simulated SELL: {position['volume']:.6f} BTC @ ${realtime_price:,.2f} | P/L: ${pl:,.2f}")
                        position = None
                        # Short delay and immediate next cycle
                        time.sleep(4)
                        continue
                    else:
                        print("[MANUAL] Sell order not validated. Trade not executed.")
                        logger.warning("[MANUAL] Sell order not validated. Trade not executed.")
            elif user_input == 'b' and position:
                print("You already have an open position. Close it before buying again.")
                # Short delay and immediate next cycle
                time.sleep(4)
                continue
            elif user_input == 's' and not position:
                print("No open position to sell.")
                # Short delay and immediate next cycle
                time.sleep(4)
                continue
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
