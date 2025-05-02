import signal, functools, os, time, sqlite3, json, subprocess, threading, sys
from collections import deque
import pandas as pd, requests
from datetime import datetime, timedelta
from strategy import Strategy
from logger import logger
from colorama import init, Fore, Style
from tabulate import tabulate

try:
    from inputimeout import inputimeout, TimeoutOccurred
except ImportError:
    def inputimeout(prompt, timeout):
        raise TimeoutOccurred
    class TimeoutOccurred(Exception):
        pass

try:
    import krakenex
except ImportError:
    class KrakenAPIStub:
        def query_public(self, *args, **kwargs):
            return {"error": [], "result": {}}
        def query_private(self, *args, **kwargs):
            return {"error": [], "result": {}}
    krakenex = type('krakenex_module', (), {'API': KrakenAPIStub})

init(autoreset=True)

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
INTERVAL = 1  # minutes (monitoring interval)
DB_FILE = "paper_trades.db"

# Initialize threading lock for database operations
DB_LOCK = threading.Lock()

def setup_database():
    """
    Initialize SQLite database and ensure the trades and initial_balance tables exist.

    Raises:
        sqlite3.OperationalError: On database operation failure.
    """
    """
    Initialize SQLite database and ensure the trades and initial_balance tables exist.

    Raises:
        sqlite3.OperationalError: On database operation failure.
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Create trades table with correct columns
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        type TEXT,
        price REAL,
        volume REAL,
        profit REAL,
        balance REAL,
        fee REAL DEFAULT 0,
        fee REAL DEFAULT 0,
        source TEXT DEFAULT 'manual'
    )''')
    # Create initial_balance table if not exists
    c.execute('''CREATE TABLE IF NOT EXISTS initial_balance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        balance REAL,
        timestamp TEXT
    )''')
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

@retry((sqlite3.OperationalError, sqlite3.DatabaseError), tries=3, delay=2, backoff=2, logger=logger)
def save_trade(trade_type, price, volume, profit, balance, source='manual', fee=0):
    """
    Save a trade record into the SQLite database.

    Args:
        trade_type (str): 'buy' or 'sell'.
        price (float): Execution price of the trade.
        volume (float): Traded volume.
        profit (float): Profit from the trade.
        balance (float): Account balance after trade.
        source (str, optional): 'manual' or 'auto'. Defaults to 'manual'.
        fee (float, optional): Commission fee for the trade. Defaults to 0.

    Raises:
        sqlite3.OperationalError: On DB operational errors.
        sqlite3.DatabaseError: On other DB errors.
    """
    try:
        with DB_LOCK, sqlite3.connect(DB_FILE, check_same_thread=False) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO trades (timestamp, type, price, volume, profit, balance, fee, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (datetime.utcnow().isoformat(), trade_type, price, volume, profit, balance, fee, source)
            )
            c.execute(
                "INSERT INTO trades (timestamp, type, price, volume, profit, balance, fee, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (datetime.utcnow().isoformat(), trade_type, price, volume, profit, balance, fee, source)
            )
            conn.commit()
            logger.info(
                f"Trade saved: {trade_type} {volume} @ {price}, profit: {profit}, balance: {balance}, fee: {fee}, source: {source}"
            )
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        logger.error(f"Exception in save_trade: {e}")
        print(f"Warning: Failed to save trade to database: {e}. Continuing without saving.")

@retry((sqlite3.OperationalError, sqlite3.DatabaseError), tries=3, delay=2, backoff=2, logger=logger)
@retry((sqlite3.OperationalError, sqlite3.DatabaseError), tries=3, delay=2, backoff=2, logger=logger)
def get_open_position():
    """
    Retrieve the most recent open (buy) position without a closing sell.

    Returns:
        dict: Details of open position with keys 'entry_price', 'volume', 'entry_time', 'source'.
        None: If no open position exists.

    Raises:
        ValueError: If data from trades table is malformed.
    """
    with DB_LOCK, sqlite3.connect(DB_FILE, check_same_thread=False) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, timestamp, price, volume, balance, source FROM trades WHERE type='buy' ORDER BY id DESC LIMIT 1"
        )
        last_buy = c.fetchone()
        if not last_buy:
            return None
        buy_id = last_buy[0]
        buy_time = last_buy[1]
        buy_price = last_buy[2]
        buy_volume = last_buy[3]
        buy_balance = last_buy[4]
        source = last_buy[5] if len(last_buy) > 5 else 'manual'
        c.execute(
            "SELECT id FROM trades WHERE type='sell' AND id>? ORDER BY id ASC LIMIT 1",
            (buy_id,)
        )
        sell = c.fetchone()
        if not sell:
            logger.info(f"Open position found: entry {buy_price}, volume {buy_volume}, source {source}")
            return {
                'entry_price': buy_price,
                'volume': buy_volume,
                'entry_time': pd.to_datetime(buy_time),
                'source': source
            }
        return None

def update_parquet():
    """
    Update the Parquet file by running update_data.py.
    """
    update_script = os.path.join("data", "update_data.py")
    if not os.path.isfile(update_script):
        logger.warning(f"update_data.py not found at {update_script}. Skipping price update.")
        print(f"Warning: update_data.py not found at {update_script}. Skipping price update.")
        return
    print("Updating prices...")
    try:
        result = subprocess.run(
            [sys.executable, update_script],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"update_data.py output: {result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running update_data.py: {e.stderr}")
        print(f"Warning: Failed to update parquet data: {e.stderr}")

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
        resp = query_public_throttled('Ticker', {'pair': pair})
        if resp["error"]:
            logger.error(f"Kraken API error: {resp['error']}")
            return None
        ticker = resp["result"][list(resp["result"].keys())[0]]
        logger.info(f"Fetched real-time price: {ticker['c'][0]}")
        return float(ticker["c"][0])
    except Exception as e:
        logger.error(f"Error querying order fee: {e}")
    return None

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
            fee = float(fee_percent)
            # Kraken typically returns fees as a fraction (e.g., 0.0026 for 0.26%)
            # If the value looks like a percentage (> 1), convert to fraction
            if fee > 1:
                fee = fee / 100.0
            return fee
    except Exception as e:
        logger.error(f"Error querying order fee: {e}")
    return None

# Define BASE_DIR as the directory of the current script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Clear console
def clear_console():
    """
    Clear the terminal screen based on the operating system.
    """
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
        equity = balance + (realtime_price * position['volume']) if realtime_price else balance
        pl_color = Fore.GREEN if pl >= 0 else Fore.RED
        eq_color = Fore.GREEN if equity >= GENERAL_CONFIG['initial_capital'] else Fore.RED
        table.extend([
            ["Trade", f"{Fore.CYAN}BUY {position['volume']:.6f} BTC @ ${position['entry_price']:,.2f}{Style.RESET_ALL}"],
            ["Type", position.get('source', 'unknown')],
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
    """
    Main paper trading loop: initializes database, loads data, evaluates strategy, and handles user input.

    Raises:
        KeyboardInterrupt: If the user stops the program with Ctrl+C.
    """
    setup_database()
    with DB_LOCK, sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT balance FROM trades ORDER BY id DESC LIMIT 1')
        last_balance = c.fetchone()
        if not last_balance:
            c.execute('SELECT balance FROM initial_balance ORDER BY id DESC LIMIT 1')
            record = c.fetchone()
            balance = record[0] if record else GENERAL_CONFIG["initial_capital"]
        else:
            balance = last_balance[0]
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
    session_start_time = datetime.utcnow()
    initial_summary = []
    if position:
        initial_summary.append(f"Recovered open position: Entry price ${position['entry_price']:.2f}, Volume {position['volume']:.6f}")
    initial_summary.append(f"Paper trading started. Initial balance: ${balance:.2f}")
    interval = CONFIG["data"]["interval"] if "data" in CONFIG and "interval" in CONFIG["data"] else "1D"
    initial_summary.append(f"The strategy is evaluated automatically at the close of each {interval} candle. Monitoring is real-time.")
    print(f"Paper trading started. Initial balance: ${balance:.2f}")
    print(f"The strategy is evaluated automatically at the close of each {interval} candle. Monitoring is real-time.")
    print("\nAvailable commands:")
    print("[b] Buy at current price  ")
    print("[s] Sell (close position)  ")
    print("[q] Quit bot  \n")
    cycle = 0
    next_evaluation_time = None

    # Convert interval to seconds for evaluation timing
    interval_seconds = {
        '1D': 24 * 60 * 60,
        '4H': 4 * 60 * 60,
        '1W': 7 * 24 * 60 * 60,
        '1H': 60 * 60,
        '60min': 60 * 60,
    }.get(interval, 24 * 60 * 60)  # Default to 1D if interval not recognized

    # Try to load existing data at startup
    df_resampled = None
    try:
        df = pd.read_parquet(os.path.join(BASE_DIR, "data", "ohlc_data_60min_all_years.parquet"))
        df["Timestamp"] = pd.to_datetime(df["Timestamp"])
        df.set_index("Timestamp", inplace=True)
        start_time = df.index.min().floor(interval)
        end_time = pd.Timestamp(datetime.utcnow()).floor(interval)
        time_range = pd.date_range(start=start_time, end=end_time, freq=interval)
        df_resampled = df.resample(interval, closed='left', label='left').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        })
        # Do not drop NA to keep the most recent candles
        # df_resampled = df_resampled.dropna()
    except Exception as e:
        logger.error(f"Initial load of parquet data failed: {e}")
        print(f"Warning: Unable to load initial parquet data: {e}. Continuing without data.")

    try:
        while RUNNING:
            cycle += 1
            current_time = pd.Timestamp(datetime.utcnow())
            # Update parquet with new 60min candles
            update_parquet()

            # Load data from parquet file
            try:
                df = pd.read_parquet(os.path.join(BASE_DIR, "data", "ohlc_data_60min_all_years.parquet"))
                df["Timestamp"] = pd.to_datetime(df["Timestamp"])
                df.set_index("Timestamp", inplace=True)
                # Resample to the configured interval (e.g., '1D')
                start_time = df.index.min().floor(interval)
                end_time = current_time.floor(interval)
                time_range = pd.date_range(start=start_time, end=end_time, freq=interval)
                df_resampled = df.resample(interval, closed='left', label='left').agg({
                    'Open': 'first',
                    'High': 'max',
                    'Low': 'min',
                    'Close': 'last',
                    'Volume': 'sum'
                })

                # Include partial candle for the current day
                last_full_candle = df_resampled.index[-1] if not df_resampled.empty else end_time
                if df.index.max() > last_full_candle:
                    partial_data = df[df.index > last_full_candle]
                    if not partial_data.empty:
                        partial_candle = pd.DataFrame({
                            'Open': [partial_data['Open'].iloc[0]],
                            'High': [partial_data['High'].max()],
                            'Low': [partial_data['Low'].min()],
                            'Close': [partial_data['Close'].iloc[-1]],
                            'Volume': [partial_data['Volume'].sum()]
                        }, index=[last_full_candle + pd.Timedelta(seconds=interval_seconds)])
                        df_resampled = pd.concat([df_resampled, partial_candle])
            except Exception as e:
                logger.error(f"Error loading parquet data: {e}")
                print(f"Warning: error loading parquet data: {e}. Using last known data if available.")
                if df_resampled is None:
                    print("No previous data available. Skipping cycle.")
                    time.sleep(INTERVAL * 60)
                    continue

            clear_console()
            for line in initial_summary:
                print(line)
            realtime_price = get_realtime_price(PAIR)
            print_trade_status(cycle, position, balance, realtime_price, trade_fee, session_start_time)

            # --- AUTO STRATEGY EVALUATION ---
            # Only evaluate the strategy at the close of each interval
            should_evaluate = False
            if next_evaluation_time is None:
                # Set the next evaluation time to the end of the current interval
                next_evaluation_time = (current_time + pd.Timedelta(seconds=interval_seconds)).floor(interval)
                should_evaluate = True  # Evaluate immediately on first cycle
            elif current_time >= next_evaluation_time:
                should_evaluate = True
                next_evaluation_time = (next_evaluation_time + pd.Timedelta(seconds=interval_seconds)).floor(interval)

            if should_evaluate:
                print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Evaluating strategy...\n")
                strategy.calculate_indicators(df_resampled)
                # Update last_candle after calculating indicators to ensure it matches the modified DataFrame
                if not df_resampled.empty:
                    now = datetime.now()
                    data_valid = df_resampled[df_resampled.index <= now]
                    if not data_valid.empty:
                        last_candle = data_valid.iloc[-1]
                        logger.debug(f"Last candle timestamp: {last_candle.name}, Price: {last_candle['Close']}")
                    else:
                        logger.warning("No valid candles to evaluate.")
                        print("No data available after calculating indicators, skipping cycle.")
                        time.sleep(INTERVAL * 60)
                        continue
                auto_action = None
                if not position and strategy.entry_signal(last_candle, data_valid, is_backtest=False):
                    auto_action = 'buy'
                    print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Entry signal detected.")
                    # Use real-time price for buying
                    auto_price = realtime_price
                    if auto_price is None:
                        print("Cannot buy: real-time price unavailable.")
                        time.sleep(INTERVAL * 60)
                        continue
                    invest_amount = balance * investment_fraction
                    if invest_amount >= 1e-8 and balance > 0:
                        volume = invest_amount / auto_price
                        balance -= invest_amount
                        # Use current time for the entry time
                        entry_time = datetime.utcnow()
                        save_trade('buy', auto_price, volume, 0, balance, source='auto', fee=trade_fee)
                        position = {
                            'entry_price': auto_price,
                            'volume': volume,
                            'entry_time': entry_time,
                            'source': 'auto'
                        }
                        print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Auto BUY: {volume:.6f} BTC @ ${auto_price:,.2f}")
                # Auto SELL
                elif position and strategy.exit_signal(last_candle, data_valid, is_backtest=False):
                    auto_action = 'sell'
                    print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Exit signal detected.")
                    # Use real-time price for selling
                    auto_price = realtime_price
                    if auto_price is None:
                        print("Cannot sell: real-time price unavailable.")
                        time.sleep(INTERVAL * 60)
                        continue
                    pl = (auto_price - position['entry_price']) * position['volume']
                    pl -= (position['entry_price'] + auto_price) * position['volume'] * trade_fee
                    balance += (auto_price * position['volume']) + pl
                    save_trade('sell', auto_price, position['volume'], pl, balance, source='auto', fee=trade_fee)
                    print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Auto SELL: {position['volume']:.6f} BTC @ ${auto_price:,.2f} | P/L: ${pl:,.2f}")
                    position = None
            else:
                print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Waiting for next {interval} candle to evaluate strategy...\n")

            # Show available commands to the user
            # Show available commands to the user
            print("Available commands:")
            print("[b] Buy at current price  ")
            print("[s] Sell (close position)  ")
            print("[q] Quit bot  \n")
            user_input = input_with_timeout("Press Enter after choosing an option: ", INTERVAL * 60).strip().lower()
            print()
            print()

            if user_input == 'q':
                print("\nBot stopped by user (q).\n")
                logger.info("Bot stopped by user (q).")
                break
            elif user_input == 'b' and not position:
                realtime_price = get_realtime_price(PAIR)
                realtime_price = get_realtime_price(PAIR)
                if not realtime_price:
                    print("Cannot buy: real-time price unavailable.")
                elif balance <= 0:
                    print("Insufficient balance to buy.")
                else:
                    invest_amount = balance * investment_fraction
                    if invest_amount < 1e-8:
                    if invest_amount < 1e-8:
                        print("Investment amount too small to execute a trade.")
                    else:
                        volume = invest_amount / realtime_price
                        fee = trade_fee  # Use the configured trade fee
                        balance -= invest_amount
                        save_trade('buy', realtime_price, volume, 0, balance, source='manual', fee=fee)
                        position = {
                            'entry_price': realtime_price,
                            'volume': volume,
                            'entry_time': datetime.utcnow(),
                            'source': 'manual'
                        }
                        print(f"Simulated BUY: {volume:.6f} BTC @ ${realtime_price:,.2f}")
                        logger.info(f"Simulated BUY: {volume:.6f} BTC @ ${realtime_price:,.2f}")
            elif user_input == 's' and position:
                realtime_price = get_realtime_price(PAIR)
                realtime_price = get_realtime_price(PAIR)
                if not realtime_price:
                    print("Cannot sell: real-time price unavailable.")
                else:
                    pl = (realtime_price - position['entry_price']) * position['volume']
                    pl -= (position['entry_price'] + realtime_price) * position['volume'] * trade_fee
                    fee = trade_fee  # Use the configured trade fee
                    balance += (realtime_price * position['volume']) + pl
                    save_trade('sell', realtime_price, position['volume'], pl, balance, source='manual', fee=fee)
                    print(f"Simulated SELL: {position['volume']:.6f} BTC @ ${realtime_price:,.2f} | P/L: ${pl:,.2f}")
                    logger.info(f"Simulated SELL: {position['volume']:.6f} BTC @ ${realtime_price:,.2f} | P/L: ${pl:,.2f}")
                    position = None
            elif user_input == 'b' and position:
                print("You already have an open position. Close it before buying again.")
                time.sleep(4)
            elif user_input == 's' and not position:
                print("No open position to sell.")
            # else: just continue

            # If user_input was empty (timeout), just continue to next cycle
            time.sleep(INTERVAL * 60)
    except KeyboardInterrupt:
        print("\nBot manually stopped by user (Ctrl+C).\n")
        logger.info("Bot manually stopped by user (Ctrl+C).")
    finally:
        print_session_summary()
    finally:
        print_session_summary()

if __name__ == "__main__":
    main()