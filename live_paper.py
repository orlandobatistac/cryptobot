import signal, functools, os, time, sqlite3, json, subprocess, threading
import krakenex, pandas as pd, requests
from datetime import datetime
from strategy import Strategy
from logger import logger
from colorama import init, Fore, Style
from inputimeout import inputimeout, TimeoutOccurred
from dotenv import load_dotenv
from collections import deque
from tabulate import tabulate

init(autoreset=True)
load_dotenv()

def round_financial(value, decimals=8):
    rounded = round(value, decimals)
    return max(rounded, 0) if rounded < 1e-8 else rounded

BASE_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DB_FILE = os.path.join(BASE_DIR, "paper_trades.db")

# Retry decorator for robustness
def retry(ExceptionToCheck, tries=3, delay=2, backoff=2, logger=None):
    """Decorator that retries retriable errors and aborts on non-retriable ones."""
    def deco_retry(f):
        @functools.wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    msg = f"{f.__name__}: {str(e)}, Retrying in {mdelay}s... ({mtries-1} tries left)"
                    if logger:
                        logger.warning(msg)
                    else:
                        print(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
                except Exception as e:
                    msg = f"{f.__name__}: Non-retriable error {str(e)}. Aborting."
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

# Load configuration
def load_config():
    with open(CONFIG_PATH, "r") as f:
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

@retry((requests.ConnectionError, requests.Timeout), tries=3, delay=2, backoff=2, logger=logger)
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
    # Usar context manager para liberar conexión automáticamente
    try:
        with DB_LOCK, sqlite3.connect(DB_FILE, check_same_thread=False) as conn:
            c = conn.cursor()
            c.execute("INSERT INTO trades (timestamp, type, price, volume, profit, balance, fee, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (datetime.utcnow().isoformat(), trade_type, price, volume, profit, balance, fee, source))
            conn.commit()
            logger.info(f"Trade saved: {trade_type} {volume} @ {price}, profit: {profit}, balance: {balance}, fee: {fee}, source: {source}")
    except Exception as e:
        logger.error(f"Exception in save_trade: {e}")
        raise

@retry(Exception, tries=3, delay=2, backoff=2, logger=logger)
def get_open_position():
    try:
        with DB_LOCK, sqlite3.connect(DB_FILE, check_same_thread=False) as conn:
            c = conn.cursor()
            c.execute('''SELECT id, timestamp, price, volume, balance, source
                         FROM trades
                         WHERE type = 'buy'
                         ORDER BY id DESC LIMIT 1''')
            last_buy = c.fetchone()
            if last_buy:
                buy_id, buy_time, buy_price, buy_volume, buy_balance, buy_source = last_buy
                c.execute('''SELECT id FROM trades
                             WHERE type = 'sell' AND id > ?
                             ORDER BY id ASC LIMIT 1''', (buy_id,))
                if not c.fetchone():
                    logger.info(f"Open position found: entry {buy_price}, volume {buy_volume}, source {buy_source}")
                    return {
                        "entry_price": buy_price,
                        "volume": buy_volume,
                        "entry_time": pd.to_datetime(buy_time),
                        "source": buy_source
                    }
        return None
    except Exception as e:
        logger.error(f"Exception in get_open_position: {e}")
        raise

def update_parquet():
    update_script = os.path.join(BASE_DIR, "data", "update_data.py")
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

# --- Signals y flag de ejecución ---
RUNNING = True
def _signal_handler(sig, frame):
    global RUNNING
    print("\nDetenido por señal de salida.\n")
    logger.info("Se recibió señal de salida, deteniendo bot.")
    RUNNING = False

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

def print_session_summary():
    """Al finalizar muestra resumen de trades."""
    with DB_LOCK, sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(SUM(profit),0) FROM trades")
        total_trades, total_profit = c.fetchone()
        c.execute("SELECT COUNT(*) FROM trades WHERE profit>0")
        wins = c.fetchone()[0]
    win_rate = (wins/total_trades*100) if total_trades else 0
    msg = f"Resumen sesión → Trades: {total_trades}, P/L: ${total_profit:.2f}, Win Rate: {win_rate:.2f}%"
    print(msg); logger.info(msg)

def print_trade_status(cycle, position, balance, realtime_price, trade_fee):
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    headers = [f"{Fore.YELLOW}Field{Style.RESET_ALL}", f"{Fore.YELLOW}Value{Style.RESET_ALL}"]
    table = [
        ["Cycle", cycle],
        ["Time", now + " UTC"],
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
        while RUNNING:
            cycle += 1
            # Update trade_fee dynamically if possible
            dynamic_fee = get_dynamic_trade_fee()
            if dynamic_fee is not None:
                trade_fee = dynamic_fee
            # Update parquet with new 60min candles
            try:
                update_parquet()
            except Exception as e:
                logger.error(f"Error actualizando datos parquet: {e}")
                print(f"Warning: fallo al actualizar datos, se omite ciclo.")
            # Load parquet and resample to D1 (or config.json interval)
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
                logger.error(f"Error cargando parquet: {e}")
                time.sleep(INTERVAL * 60)
                continue

            clear_console()
            for line in initial_summary:
                print(line)
            # Ensure user_input is always defined
            user_input = ''
            print_trade_status(cycle, position, balance, get_realtime_price(PAIR), trade_fee)

            # --- AUTO STRATEGY EVALUATION ---
            print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Evaluating strategy...\n")
            strategy.calculate_indicators(df_resampled)
            last_candle = df_resampled.iloc[-1]
            auto_action = None
            # Auto BUY
            if not position and strategy.entry_signal(last_candle, df_resampled):
                auto_action = 'buy'
                print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Entry signal detected.")
                auto_price = last_candle['Close']  # Precio de cierre para consistencia
                invest_amount = balance * investment_fraction
                if invest_amount >= 1e-8 and balance > 0:
                    volume = invest_amount / auto_price
                    order_result = simulate_order('buy', PAIR, volume, price=auto_price, validate=True)
                    if not order_result:
                        market_price = get_realtime_price(PAIR)
                        if market_price:
                            volume = invest_amount / market_price
                            order_result = simulate_order('buy', PAIR, volume, price=None, validate=True)
                            auto_price = market_price
                    if order_result:
                        balance = round_financial(balance - invest_amount)
                        save_trade('buy', auto_price, volume, 0, balance, fee=order_result.get('fee', trade_fee), source='auto')
                        position = {'entry_price': auto_price, 'volume': volume, 'entry_time': last_candle.name, 'source': 'auto'}
                        print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} BUY: {volume:.6f} BTC @ ${auto_price:.2f}")
            # Auto SELL
            elif position and strategy.exit_signal(last_candle, df_resampled):
                auto_action = 'sell'
                print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Exit signal detected.")
                auto_price = last_candle['Close']  # Precio de cierre para consistencia
                pl = (auto_price - position['entry_price']) * position['volume']
                pl -= (position['entry_price'] + auto_price) * position['volume'] * trade_fee
                order_result = simulate_order('sell', PAIR, position['volume'], price=auto_price, validate=True)
                if not order_result:
                    market_price = get_realtime_price(PAIR)
                    if market_price:
                        auto_price = market_price
                        order_result = simulate_order('sell', PAIR, position['volume'], price=None, validate=True)
                if order_result:
                    balance = round_financial(balance + (auto_price * position['volume']) + pl)
                    save_trade('sell', auto_price, position['volume'], pl, balance, fee=order_result.get('fee', trade_fee), source='auto')
                    print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} SELL: {position['volume']:.6f} BTC @ ${auto_price:.2f} | P/L: ${pl:.2f}")

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
                realtime_price = get_realtime_price(PAIR)
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
                            balance = round_financial(balance - invest_amount)
                            fee_real = realtime_price * volume * trade_fee
                            save_trade('buy', realtime_price, volume, 0, balance, fee=fee_real, source='manual')
                            position = {
                                'entry_price': realtime_price,
                                'volume': volume,
                                'entry_time': datetime.utcnow(),
                                'source': 'manual'
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
                realtime_price = get_realtime_price(PAIR)
                if not realtime_price:
                    print("Cannot sell: real-time price unavailable.")
                else:
                    pl = (realtime_price - position['entry_price']) * position['volume']
                    pl -= (position['entry_price'] + realtime_price) * position['volume'] * trade_fee
                    # Use limit order at realtime_price
                    order_result = simulate_order('sell', PAIR, position['volume'], price=realtime_price, validate=True)
                    if order_result:
                        balance = round_financial(balance + (realtime_price * position['volume']) + pl)
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
    finally:
        print_session_summary()

if __name__ == "__main__":
    main()
