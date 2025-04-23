import signal, functools, os, time, sqlite3, json, subprocess, threading
from collections import deque
import krakenex, pandas as pd, requests
from datetime import datetime
from strategy import Strategy
from logger import logger
from colorama import init, Fore, Style
from inputimeout import inputimeout, TimeoutOccurred
from tabulate import tabulate
import functools
import sys
import threading
from inputimeout import inputimeout, TimeoutOccurred

init(autoreset=True)

# Retry decorator for robustness
def retry(ExceptionToCheck, tries=3, delay=2, backoff=2, logger=None):
    def deco_retry(f):
        @functools.wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    pass  # Add your logic here
                except Exception as e:
                    logger.error(f"An error occurred: {e}")
                except Exception as e:
                    logger.error(f"An error occurred: {e}")
                except Exception as e:
                    logger.error(f"An error occurred: {e}")
                except Exception as e:
                    logger.error(f"An error occurred: {e}")
                except Exception as e:
                    logger.error(f"An error occurred: {e}")
                except Exception as e:
                    logger.error(f"An error occurred: {e}")
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
                        logger.error(msg)
                    else:
                        print(msg)
                    raise
            try:
                return f(*args, **kwargs)
            except Exception as e:
                msg = f"{f.__name__}: {str(e)}. No more retries."
                if logger:
                    logger.error(msg)
                else:
                    print(msg)
                raise
        return f_retry
    return deco_retry

# Define the path to the configuration file
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def load_config():
    """
    Load and parse the JSON configuration file.

    Returns:
        dict: Configuration data parsed from JSON.

    Raises:
        FileNotFoundError: If the config file does not exist.
        json.JSONDecodeError: If the JSON is invalid.
    """
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

CONFIG = load_config()
STRATEGY_CONFIG = CONFIG["strategy"]
GENERAL_CONFIG = CONFIG["general"]

k = krakenex.API()

# Parameters
PAIR = "XXBTZUSD"  # BTC/USD
INTERVAL = 1  # minutes
DB_FILE = "paper_trades.db"

# Initialize threading lock for database operations
DB_LOCK = threading.Lock()

def setup_database():
    """
    Initialize SQLite database and ensure the trades and initial_balance tables exist.

    Raises:
        sqlite3.OperationalError: On database operation failure.
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Add 'source' column if it doesn't exist
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
        balance REAL,
        source TEXT DEFAULT 'manual'
    )''')
    # Try to add the column if upgrading an old DB
    try:
        c.execute("ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'manual'")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE trades ADD COLUMN fee REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # Insert initial balance record if none exists
    c.execute("SELECT balance FROM initial_balance ORDER BY id DESC LIMIT 1")
    initial_record = c.fetchone()
    if not initial_record:
        c.execute(
            "INSERT INTO initial_balance (balance, timestamp) VALUES (?, ?)",
            (GENERAL_CONFIG["initial_capital"], datetime.utcnow().isoformat())
        )
    conn.commit()
    conn.close()

RATE_LIMIT_THRESHOLD = 2
RATE_LIMIT_SLEEP = 3

RATE_LIMIT_POINTS = 15
RATE_LIMIT_WINDOW = 3

ENDPOINT_POINTS = {
    'AddOrder': 2,
    'CancelOrder': 1,
    'Ticker': 1,
    'OHLC': 1,
    'TradeBalance': 1,
    'AssetPairs': 1,
}

api_call_times = deque()
api_call_points = deque()

def rate_limit_throttle(endpoint):
    """
    Throttle local API calls to respect Kraken's rate limits.

    Args:
        endpoint (str): Kraken API endpoint being called.
    """
    now = time.time()
    while api_call_times and now - api_call_times[0] > RATE_LIMIT_WINDOW:
        api_call_times.popleft()
        api_call_points.popleft()
    used_points = sum(api_call_points)
    endpoint_points = ENDPOINT_POINTS.get(endpoint, 1)
    if used_points + endpoint_points > RATE_LIMIT_POINTS:
        sleep_time = RATE_LIMIT_WINDOW - (now - api_call_times[0])
        logger.warning(f"Local rate limit: {used_points} points used. Pausing {sleep_time:.2f}s to avoid lockout.")
        time.sleep(max(sleep_time, 0.1))
    api_call_times.append(time.time())
    api_call_points.append(endpoint_points)

def query_public_throttled(endpoint, *args, **kwargs):
    """
    Call Kraken public API with local rate limiting.

    Args:
        endpoint (str): Kraken public API endpoint.
        *args: Positional arguments for API call.
        **kwargs: Keyword arguments for API call.

    Returns:
        dict: Response from Kraken API.

    Raises:
        requests.ConnectionError: On connection failure.
        requests.Timeout: On request timeout.
    """
    rate_limit_throttle(endpoint)
    return k.query_public(endpoint, *args, **kwargs)

def query_private_throttled(endpoint, *args, **kwargs):
    """
    Call Kraken private API with local rate limiting.

    Args:
        endpoint (str): Kraken private API endpoint.
        *args: Positional arguments for API call.
        **kwargs: Keyword arguments for API call.

    Returns:
        dict: Response from Kraken API.

    Raises:
        requests.ConnectionError: On connection failure.
        requests.Timeout: On request timeout.
    """
    rate_limit_throttle(endpoint)
    return k.query_private(endpoint, *args, **kwargs)

@retry((requests.ConnectionError, requests.Timeout), tries=3, delay=2, backoff=2, logger=logger)
def get_latest_candle(pair, interval):
    """
    Fetch the latest OHLC candle for a trading pair.

    Args:
        pair (str): Asset pair code (e.g. 'XXBTZUSD').
        interval (int): Candle interval in minutes.

    Returns:
        pandas.DataFrame: DataFrame with one row representing the latest candle.

    Raises:
        requests.ConnectionError: If API call fails.
        requests.Timeout: If API call times out.
        Exception: For other unexpected errors.
    """
    try:
        resp = query_public_throttled('OHLC', {'pair': pair, 'interval': interval})
        if resp["error"]:
            logger.error(f"Kraken API error: {resp['error']}")
            return None
        ohlc = resp["result"][list(resp["result"].keys())[0]]
        df = pd.DataFrame(ohlc, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
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
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DB_FILE, check_same_thread=False)
            c = conn.cursor()
            c.execute(
                "INSERT INTO trades (timestamp, type, price, volume, profit, balance, fee, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (datetime.utcnow().isoformat(), trade_type, price, volume, profit, balance, 0, source)  # Default fee to 0
            )
            conn.commit()
            logger.info(
                f"Trade saved: {trade_type} {volume} @ {price}, profit: {profit}, balance: {balance}, fee: 0, source: {source}"
            )
    except Exception as e:
        logger.error(f"Exception in save_trade: {e}")
        print(f"Warning: Failed to save trade to database: {e}. Continuing without saving.")
        return

@retry((sqlite3.OperationalError, sqlite3.DatabaseError), tries=3, delay=2, backoff=2, logger=logger)
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
    except Exception as e:
        logger.error(f"Exception in get_open_position: {e}")
    return None

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

@retry((requests.ConnectionError, requests.Timeout), tries=3, delay=2, backoff=2, logger=logger)
def get_realtime_price(pair):
    """
    Fetch the current market price for a given trading pair.

    Args:
        pair (str): Asset pair code (e.g. 'XXBTZUSD').

    Returns:
        float: Last traded price, or None on API error.

    Raises:
        requests.ConnectionError: If API call fails.
        requests.Timeout: If API call times out.
        Exception: For other unexpected errors.
    """
    try:
        resp = query_public_throttled('Ticker', {'pair': pair})
        if resp["error"]:
            logger.error(f"Kraken API error: {resp['error']}")
            return None
        ticker = resp["result"][list(resp["result"].keys())[0]]
        logger.info(f"Fetched real-time price: {ticker['c'][0]}")
        return float(ticker["c"][0])
    except Exception as e:
        logger.error(f"Exception in get_realtime_price: {e}")
        raise

def get_estimated_order_fee(pair, ordertype, volume):
    """
    Estimate the commission fee for an order using Kraken's Fee endpoint.

    Args:
        pair (str): Asset pair code.
        ordertype (str): 'buy' or 'sell'.
        volume (float): Order volume.

    Returns:
        float: Fee fraction (e.g. 0.0026) or None if not available.

    Raises:
        requests.ConnectionError: On connection failure.
        requests.Timeout: On request timeout.
        Exception: For other unexpected errors.
    """
    if not k.key or not k.secret:
        return None
    try:
        resp = query_private_throttled('Fee', {'pair': pair, 'type': ordertype, 'ordertype': ordertype, 'volume': str(volume)})
        if resp.get('error'):
            logger.warning(f"Kraken Fee endpoint error: {resp['error']}")
            return None
        fee_percent = resp.get('result', {}).get('fee')
        if fee_percent is not None:
            return float(fee_percent) / 100.0
    except Exception as e:
        logger.error(f"Error querying order fee: {e}")
    return None

@retry((requests.ConnectionError, requests.Timeout), tries=3, delay=2, backoff=2, logger=logger)
def simulate_order(order_type, pair, volume, price=None, validate=True):
    """
    Simulate a paper-trading order via Kraken's API in validation mode.

    Args:
        order_type (str): 'buy' or 'sell'.
        pair (str): Asset pair (e.g. 'XXBTZUSD').
        volume (float): Order volume.
        price (float, optional): Limit price; None for market orders.
        validate (bool): If True, perform API validation; else return API response.

    Returns:
        dict or None: Simulation result with keys 'status', 'filled_volume', etc., or None on failure.

    Raises:
        requests.ConnectionError: On connection failure.
        requests.Timeout: On request timeout.
        Exception: For other unexpected errors.
    """
    estimated_fee = get_estimated_order_fee(pair, order_type, volume)
    if not k.key or not k.secret:
        logger.warning("Kraken API keys not configured. Skipping order validation.")
        print(f"[Simulation] Kraken API keys not configured. Skipping order validation.")
        return {
            'descr': f"{order_type} {volume} {pair} @ market (no validation)",
            'status': 'filled',
            'filled_volume': volume,
            'remaining_volume': 0.0,
            'fee': estimated_fee if estimated_fee is not None else GENERAL_CONFIG["trade_fee"]
        }
    # Define a default minimum volume or fetch it dynamically if needed
    min_vol = 0.0001  # Replace with the actual logic if available
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
        if validate:
            return {
                'descr': descr,
                'status': 'filled',
                'filled_volume': volume,
                'remaining_volume': 0.0,
                'fee': estimated_fee if estimated_fee is not None else GENERAL_CONFIG["trade_fee"]
            }
        return resp['result']
    except Exception as e:
        logger.error(f"Exception in simulate_order: {e}")
        print(f"[Simulation] Error in simulate_order: {e}")
        return None

def get_dynamic_trade_fee():
    """
    Query the actual trading fee rate via Kraken's TradeBalance endpoint.

    Returns:
        float: Fee amount or None if unavailable or no API keys.

    Raises:
        requests.ConnectionError: On connection failure.
        requests.Timeout: On request timeout.
        Exception: For other unexpected errors.
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
        logger.error(f"Exception in get_realtime_price: {e}")
        raise

# Define BASE_DIR as the directory of the current script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Clear console
def clear_console():
    """
    Clear the terminal screen based on the operating system.
    """
    os.system('cls' if os.name == 'nt' else 'clear')

def input_with_timeout(prompt, timeout):
    """
    Prompt the user for input with a timeout.

    Args:
        prompt (str): Prompt message displayed to the user.
        timeout (int or float): Seconds to wait for input.

    Returns:
        str: User input or empty string on timeout or interruption.
    """
    try:
        return inputimeout(prompt=prompt, timeout=timeout)
    except TimeoutOccurred:
        return ''
    except (EOFError, KeyboardInterrupt):
        return ''

RUNNING = True
def _signal_handler(sig, frame):
    """
    Handle OS signals to gracefully stop the trading loop.

    Args:
        sig (int): Signal number received.
        frame: Current stack frame.
    """
    global RUNNING
    print("\nStopped by exit signal.\n")
    logger.info("Exit signal received, stopping bot.")
    RUNNING = False

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

def print_session_summary():
    """
    Display a summary of trades and profit at session end.

    Prints total trades, total profit, and win rate.
    """
    try:
        with DB_LOCK, sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*), COALESCE(SUM(profit),0) FROM trades")
            total_trades, total_profit = c.fetchone()
            c.execute("SELECT COUNT(*) FROM trades WHERE profit>0")
            wins = c.fetchone()[0]
    except Exception as e:
        logger.error(f"Exception in print_session_summary: {e}")
        print(f"Warning: Failed to fetch session summary from database: {e}.")
        return
    win_rate = (wins/total_trades*100) if total_trades else 0
    msg = f"Session summary → Trades: {total_trades}, P/L: ${total_profit:.2f}, Win Rate: {win_rate:.2f}%"
    print(msg); logger.info(msg)

def print_trade_status(cycle, position, balance, realtime_price, trade_fee, session_start_time):
    """
    Print the current trade status, including cycle, price, P/L, and equity.

    Args:
        cycle (int): Current cycle number.
        position (dict or None): Current open position details.
        balance (float): Current account balance.
        realtime_price (float or None): Latest market price.
        trade_fee (float): Current trade fee fraction.
        session_start_time (datetime): Start time of the trading session.
    """
    now_dt = datetime.utcnow()
    now_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')
    uptime = now_dt - session_start_time
    uptime_str = str(uptime).split('.')[0]  # Format: days, HH:MM:SS
    headers = [f"{Fore.YELLOW}Field{Style.RESET_ALL}", f"{Fore.YELLOW}Value{Style.RESET_ALL}"]
    table = [
        ["Cycle", cycle],
        ["Session Start", session_start_time.strftime('%Y-%m-%d %H:%M:%S') + " UTC"],
        ["Uptime", uptime_str],
        ["Time", now_str + " UTC"],
        ["BTCUSD Price", f"${realtime_price:,.2f}" if realtime_price else "N/A"]
    ]
    if position:
        pl = (realtime_price - position['entry_price']) * position['volume'] if realtime_price else 0
        pl -= (position['entry_price'] + realtime_price) * position['volume'] * trade_fee if realtime_price else 0
        equity = balance + (realtime_price * position['volume'] + pl) if realtime_price else balance
        pl_color = Fore.GREEN if pl >= 0 else Fore.RED
        eq_color = Fore.GREEN if equity >= GENERAL_CONFIG['initial_capital'] else Fore.RED
        table.extend([
            ["Trade", f"{Fore.CYAN}BUY {position['volume']:.6f} BTC @ ${position['entry_price']:,.2f}{Style.RESET_ALL}"],
            ["Type", position['source']],
            ["Open Time", position['entry_time'].strftime('%Y-%m-%d %H:%M:%S')],
            ["P/L", f"{pl_color}${pl:,.2f}{Style.RESET_ALL}"],
            ["Equity", f"{eq_color}${equity:,.2f}{Style.RESET_ALL}"]
        ])
    else:
        bal_color = Fore.GREEN if balance >= GENERAL_CONFIG['initial_capital'] else Fore.RED
        table.extend([
            ["Trade", "No open trade"],
            ["P/L", "N/A"],
            ["Balance", f"{bal_color}${balance:,.2f}{Style.RESET_ALL}"]
        ])
    print(f"\n{Fore.CYAN}{'='*40}{Style.RESET_ALL}")
    print(tabulate(table, headers, tablefmt="plain"))
    print(f"{Fore.CYAN}{'='*40}{Style.RESET_ALL}\n")

def main():
    """
    Main paper trading loop: initializes database, loads data, evaluates strategy, and handles user input.

    Raises:
        KeyboardInterrupt: If the user stops the program with Ctrl+C.
    """
    setup_database()
    with DB_LOCK, sqlite3.connect(DB_FILE, check_same_thread=False) as conn:
        c = conn.cursor()
        c.execute('SELECT balance FROM trades ORDER BY id DESC LIMIT 1')
        last_balance = c.fetchone()
        if not last_balance:
            c.execute('SELECT balance FROM initial_balance ORDER BY id DESC LIMIT 1')
            record = c.fetchone()
            balance = record[0] if record else GENERAL_CONFIG["initial_capital"]
        else:
            balance = last_balance[0]
    trade_fee = GENERAL_CONFIG["trade_fee"]
    investment_fraction = GENERAL_CONFIG["investment_fraction"]
    strategy = Strategy()
    position = get_open_position()
    session_start_time = datetime.utcnow()
    initial_summary = []
    if position:
        initial_summary.append(f"Recovered open position: Entry price ${position['entry_price']:.2f}, Volume {position['volume']:.6f}")
    initial_summary.append(f"Paper trading started. Initial balance: ${balance:.2f}")
    interval = CONFIG["data"]["interval"] if "data" in CONFIG and "interval" in CONFIG["data"] else "1D"
    initial_summary.append(f"The strategy is evaluated automatically at the close of each {interval} candle. Monitoring is real-time.")
    trades = []
    print(f"Paper trading started. Initial balance: ${balance:.2f}")
    print(f"The strategy is evaluated automatically at the close of each {interval} candle. Monitoring is real-time.")
    print("\nAvailable commands:")
    print("[b] Buy at current price  ")
    print("[s] Sell (close position)  ")
    print("[q] Quit bot  \n")
    cycle = 0
    last_resampled_time = None

    try:
        while RUNNING:
            cycle += 1
            # Update parquet with new 60min candles
            try:
                update_parquet()
            except Exception as e:
                logger.error(f"Error updating parquet data: {e}")
                print("Warning: failed to update data, skipping cycle.")
            try:
                df = pd.read_parquet(os.path.join(BASE_DIR, "data", "ohlc_data_60min_all_years.parquet"))
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
            except Exception as e:
                logger.error(f"Error loading parquet data: {e}")
                print("Warning: error loading parquet data, skipping cycle.")
                time.sleep(INTERVAL * 60)
                continue

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
                    balance_color = Fore.GREEN if equity >= GENERAL_CONFIG["initial_capital"] else Fore.RED
                    print("\n" + Fore.CYAN + "="*40 + Style.RESET_ALL)
                    balance_color = Fore.GREEN if equity >= GENERAL_CONFIG["initial_capital"] else Fore.RED
                    print("\n" + Fore.CYAN + "="*40 + Style.RESET_ALL)
                    print(f"CYCLE {cycle} | {now} UTC\n")
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
            if not position and strategy.entry_signal(last_candle, df_resampled):
                auto_action = 'buy'
                print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Entry signal detected.")
                auto_price = last_candle['Close']
                invest_amount = balance * investment_fraction
                if invest_amount >= 1e-8 and balance > 0:
                    volume = invest_amount / auto_price
                    balance -= invest_amount
                    # Use datetime.utcnow() if using realtime price, else use last_candle time
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
            # Auto SELL
            elif position and strategy.exit_signal(last_candle, df_resampled):
                auto_action = 'sell'
                print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Exit signal detected.")
                auto_price = last_candle['Close']
                pl = (auto_price - position['entry_price']) * position['volume']
                pl -= (position['entry_price'] + auto_price) * position['volume'] * trade_fee
                balance += (auto_price * position['volume']) + pl
                save_trade('sell', auto_price, position['volume'], pl, balance, source='auto')
                print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Auto SELL: {position['volume']:.6f} BTC @ ${auto_price:,.2f} | P/L: ${pl:,.2f}")
                position = None

            # Show available commands to the user
            print("Available commands:")
            print("[b] Buy at current price  ")
            print("[s] Sell (close position)  ")
            print("[q] Quit bot  \n")
            user_input = input_with_timeout("Press Enter after choosing an option: ", INTERVAL * 60).strip().lower()
            print()

            if user_input == 'q':
                print("\nBot stopped by user (q).\n")
                logger.info("Bot stopped by user (q).")
                break
            elif user_input == 'b' and not position:
                realtime_price = get_realtime_price(PAIR)
                if not realtime_price:
                    print("Cannot buy: real-time price unavailable.")
                elif balance <= 0:
                    print("Insufficient balance to buy.")
                elif balance <= 0:
                    print("Insufficient balance to buy.")
                else:
                    invest_amount = balance * investment_fraction
                    if invest_amount < 1e-8:
                        print("Investment amount too small to execute a trade.")
                    else:
                        volume = invest_amount / realtime_price
                        balance -= invest_amount
                        save_trade('buy', realtime_price, volume, 0, balance, source='manual')
                        position = {
                            'entry_price': realtime_price,
                            'volume': volume,
                            'entry_time': datetime.utcnow()
                        }
                        print(f"Simulated BUY: {volume:.6f} BTC @ ${realtime_price:,.2f}")
                        logger.info(f"Simulated BUY: {volume:.6f} BTC @ ${realtime_price:,.2f}")
            elif user_input == 's' and position:
                realtime_price = get_realtime_price(PAIR)
                if not realtime_price:
                    print("Cannot sell: real-time price unavailable.")
                else:
                    pl = (realtime_price - position['entry_price']) * position['volume']
                    pl -= (position['entry_price'] + realtime_price) * position['volume'] * trade_fee
                    balance += (realtime_price * position['volume']) + pl
                    save_trade('sell', realtime_price, position['volume'], pl, balance, source='manual')
                    print(f"Simulated SELL: {position['volume']:.6f} BTC @ ${realtime_price:,.2f} | P/L: ${pl:,.2f}")
                    logger.info(f"Simulated SELL: {position['volume']:.6f} BTC @ ${realtime_price:,.2f} | P/L: ${pl:,.2f}")
                    position = None
            elif user_input == 'b' and position:
                print("You already have an open position. Close it before buying again.")
                time.sleep(4)
                continue
            elif user_input == 's' and not position:
                print("No open position to sell.")
            # else: just continue

            # If user_input was empty (timeout), just continue to next cycle
    except KeyboardInterrupt:
        print("\nBot manually stopped by user (Ctrl+C).\n")
        logger.info("Bot manually stopped by user (Ctrl+C).")
    finally:
        print_session_summary()

if __name__ == "__main__":
    main()
