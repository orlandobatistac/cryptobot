import os
import sys
import time
import logging
import signal
import json
from datetime import datetime
from decimal import Decimal
import krakenex
from strategy import Strategy
from logger import logger
from colorama import Fore, Style, init
from tabulate import tabulate
from dotenv import load_dotenv
from notifications import load_config, send_email, format_critical_error, format_order

init(autoreset=True)

# Load environment variables from .env
load_dotenv()

API_KEY = os.getenv('KRAKEN_API_KEY')
API_SECRET = os.getenv('KRAKEN_API_SECRET')

if not API_KEY or not API_SECRET:
    print("[ERROR] Kraken API keys not set. Please set KRAKEN_API_KEY and KRAKEN_API_SECRET in your .env file.")
    sys.exit(1)

k = krakenex.API(key=API_KEY, secret=API_SECRET)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)
STRATEGY_CONFIG = CONFIG["strategy"]
GENERAL_CONFIG = CONFIG["general"]

PAIR = "XXBTZUSD"
TRADE_FEE = GENERAL_CONFIG.get("trade_fee", 0.0026)
INVESTMENT_FRACTION = GENERAL_CONFIG.get("investment_fraction", 1.0)
MIN_TRADE_SIZE = 0.0001  # Minimum trade size - you can adjust per pair

RUNNING = True

# Execution metrics
metrics = {
    'start_time': datetime.utcnow(),
    'trades_executed': 0,
    'trades_won': 0,
    'total_profit': 0.0,
    'last_trade': None,  # {'type': 'buy'/'sell', 'time': datetime, 'price': float, 'volume': float}
    'max_drawdown': 0.0,
    'max_balance': 0.0,
}

def _signal_handler(sig, frame):
    global RUNNING
    print("\nStopped by exit signal.\n")
    logger.info("Exit signal received, stopping bot.")
    RUNNING = False

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

def get_account_balance(asset="ZUSD"):
    try:
        resp = k.query_private('Balance')
        if resp.get('error'):
            logger.error(f"Kraken API error (Balance): {resp['error']}")
            return None
        return float(resp['result'].get(asset, 0))
    except Exception as e:
        logger.error(f"Exception in get_account_balance: {e}")
        return None

def get_asset_balance(asset="XXBT"):
    try:
        resp = k.query_private('Balance')
        if resp.get('error'):
            logger.error(f"Kraken API error (Balance): {resp['error']}")
            return None
        return float(resp['result'].get(asset, 0))
    except Exception as e:
        logger.error(f"Exception in get_asset_balance: {e}")
        return None

def get_realtime_price(pair):
    try:
        resp = k.query_public('Ticker', {'pair': pair})
        if resp.get('error'):
            logger.error(f"Kraken API error (Ticker): {resp['error']}")
            return None
        ticker = resp['result'][list(resp['result'].keys())[0]]
        return float(ticker['c'][0])
    except Exception as e:
        logger.error(f"Exception in get_realtime_price: {e}")
        return None

def place_order(order_type, pair, volume, price=None):
    try:
        params = {
            'pair': pair,
            'type': order_type,
            'ordertype': 'market',
            'volume': str(volume)
        }
        if price:
            params['price'] = str(price)
        resp = k.query_private('AddOrder', params)
        if resp.get('error'):
            logger.error(f"Kraken API error (AddOrder): {resp['error']}")
            return None
        txid = resp['result']['txid'][0] if 'result' in resp and 'txid' in resp['result'] else None
        logger.info(f"Order placed: {order_type} {volume} {pair} (txid: {txid})")
        return txid
    except Exception as e:
        logger.error(f"Exception in place_order: {e}")
        return None

def check_order_status(txid):
    try:
        resp = k.query_private('QueryOrders', {'txid': txid})
        if resp.get('error'):
            logger.error(f"Kraken API error (QueryOrders): {resp['error']}")
            return None
        status = resp['result'][txid]['status']
        return status
    except Exception as e:
        logger.error(f"Exception in check_order_status: {e}")
        return None

def print_trade_status(balance, btc_balance, realtime_price, position):
    headers = [f"{Fore.YELLOW}Field{Style.RESET_ALL}", f"{Fore.YELLOW}Value{Style.RESET_ALL}"]
    balance_str = f"${balance:,.2f}" if balance is not None else "N/A"
    btc_balance_str = f"{btc_balance:.6f} BTC" if btc_balance is not None else "N/A"
    price_str = f"${realtime_price:,.2f}" if realtime_price is not None else "N/A"
    table = [
        ["USD Balance", balance_str],
        ["BTC Balance", btc_balance_str],
        ["BTCUSD Price", price_str]
    ]
    if position:
        entry_price = position.get('entry_price')
        volume = position.get('volume')
        entry_price_str = f"${entry_price:,.2f}" if entry_price is not None else "N/A"
        volume_str = f"{volume:.6f}" if volume is not None else "N/A"
        pl = (realtime_price - entry_price) * volume if (realtime_price is not None and entry_price is not None and volume is not None) else 0
        pl_color = Fore.GREEN if pl >= 0 else Fore.RED
        table.extend([
            ["Trade", f"{Fore.CYAN}BUY {volume_str} BTC @ {entry_price_str}{Style.RESET_ALL}"],
            ["Open Time", position['entry_time'].strftime('%Y-%m-%d %H:%M:%S') if position.get('entry_time') else "N/A"],
            ["P/L", f"{pl_color}${pl:,.2f}{Style.RESET_ALL}" if realtime_price is not None and entry_price is not None and volume is not None else "N/A"]
        ])
    else:
        table.append(["Trade", "No open trade"])
    print(f"\n{Fore.CYAN}{'='*40}{Style.RESET_ALL}")
    print(tabulate(table, headers, tablefmt="plain"))
    print(f"{Fore.CYAN}{'='*40}{Style.RESET_ALL}\n")

def print_metrics(metrics, position, realtime_price):
    uptime = datetime.utcnow() - metrics['start_time']
    pl_unrealized = 0
    if position and realtime_price:
        pl_unrealized = (realtime_price - position['entry_price']) * position['volume']
    # Calculate win rate
    total_trades = metrics.get('trades_executed', 0)
    wins = metrics.get('trades_won', 0)
    win_rate = (wins / total_trades * 100) if total_trades else 0
    print("\n--- BOT EXECUTION METRICS ---")
    print(f"Uptime: {str(uptime).split('.')[0]}")
    print(f"Executed trades: {total_trades}")
    print(f"Win rate: {win_rate:.2f}%")
    print(f"Total realized profit: ${metrics['total_profit']:.2f}")
    print(f"Unrealized P/L: ${pl_unrealized:.2f}")
    if metrics['last_trade']:
        lt = metrics['last_trade']
        print(f"Last trade: {lt['type'].upper()} {lt['volume']:.6f} @ ${lt['price']:.2f} ({lt['time'].strftime('%Y-%m-%d %H:%M:%S')})")
    else:
        print("Last trade: N/A")
    print(f"Max balance reached: ${metrics['max_balance']:.2f}")
    print(f"Max drawdown: ${metrics['max_drawdown']:.2f}")
    print("-------------------------------------\n")

def notificaciones_habilitadas(tipo):
    config = load_config()
    notif = config.get('notifications', {})
    return notif.get('enabled', False) and notif.get('types', {}).get(tipo, False)

def main():
    print("\n[INFO] Starting LIVE trading mode (REAL MONEY).\n")
    logger.info("Starting LIVE trading mode (REAL MONEY).")
    strategy = Strategy()
    position = None
    global metrics
    
    try:
        while RUNNING:
            balance = get_account_balance()
            btc_balance = get_asset_balance()
            realtime_price = get_realtime_price(PAIR)
            # Update max balance and drawdown metrics
            if balance is not None:
                if balance > metrics['max_balance']:
                    metrics['max_balance'] = balance
                dd = metrics['max_balance'] - balance
                if dd > metrics['max_drawdown']:
                    metrics['max_drawdown'] = dd
            print_trade_status(balance, btc_balance, realtime_price, position)
            print_metrics(metrics, position, realtime_price)
            # --- Automatic strategy ---
            # ENTRY
            if not position and strategy.entry_signal(None, None, is_backtest=False):
                print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Entry signal detected.")
                invest_amount = balance * INVESTMENT_FRACTION
                if invest_amount < 10:  # Kraken minimum for BTC/USD
                    print("[WARN] Investment amount too small for real trade.")
                    logger.warning("Investment amount too small for real trade.")
                else:
                    volume = invest_amount / realtime_price
                    if volume < MIN_TRADE_SIZE:
                        print("[WARN] Volume below minimum trade size.")
                        logger.warning("Volume below minimum trade size.")
                    else:
                        txid = place_order('buy', PAIR, volume)
                        if txid:
                            print(f"[LIVE] Buy order placed. Waiting for confirmation...")
                            # Wait for confirmation
                            for _ in range(10):
                                status = check_order_status(txid)
                                if status == 'closed':
                                    print(f"[LIVE] Buy order filled.")
                                    break
                                time.sleep(5)
                            position = {
                                'entry_price': realtime_price,
                                'volume': volume,
                                'entry_time': datetime.utcnow()
                            }
                            # Update trade metrics
                            metrics['trades_executed'] += 1
                            if 'trades_won' not in metrics:
                                metrics['trades_won'] = 0
                            metrics['last_trade'] = {
                                'type': 'buy',
                                'time': datetime.utcnow(),
                                'price': realtime_price,
                                'volume': volume
                            }
                            if notificaciones_habilitadas('order'):
                                send_email(**format_order('compra'))
                        else:
                            print("[ERROR] Failed to place buy order.")
            # EXIT
            elif position and strategy.exit_signal(None, None, is_backtest=False):
                print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Exit signal detected.")
                txid = place_order('sell', PAIR, position['volume'])
                if txid:
                    print(f"[LIVE] Sell order placed. Waiting for confirmation...")
                    for _ in range(10):
                        status = check_order_status(txid)
                        if status == 'closed':
                            print(f"[LIVE] Sell order filled.")
                            break
                        time.sleep(5)
                    # Update trade metrics and realized profit
                    profit = (realtime_price - position['entry_price']) * position['volume']
                    metrics['total_profit'] += profit
                    metrics['trades_executed'] += 1
                    if profit > 0:
                        metrics['trades_won'] = metrics.get('trades_won', 0) + 1
                    metrics['last_trade'] = {
                        'type': 'sell',
                        'time': datetime.utcnow(),
                        'price': realtime_price,
                        'volume': position['volume']
                    }
                    position = None
                    if notificaciones_habilitadas('order'):
                        send_email(**format_order('venta'))
                else:
                    print("[ERROR] Failed to place sell order.")
            else:
                print(f"{Fore.MAGENTA}[AUTO]{Style.RESET_ALL} Waiting for strategy evaluation...\n")
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n[INFO] Stopping bot due to keyboard interrupt.\n")
        logger.info("Stopping bot due to keyboard interrupt.")
    except Exception as e:
        logger.error(f"Excepción crítica: {e}")
        if notificaciones_habilitadas('critical_error'):
            send_email(**format_critical_error())
        raise

if __name__ == "__main__":
    main()
