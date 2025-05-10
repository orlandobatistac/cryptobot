# main.py

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

from utils.logger import logger
from functools import wraps
from tqdm import tqdm
from colorama import Fore, Style
from core.data import DataHandler
from core.strategy import Strategy
from core.backtest import Backtester
from datetime import datetime
import json
import shutil
import logging
import pandas as pd
import numpy as np
import subprocess
from utils.notifications import load_config, send_email, format_critical_error

# Load configuration from config.json
with open("config.json", "r") as config_file:
    config = json.load(config_file)

def log_debug(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.debug(f"Entering {func.__name__}")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"Exiting {func.__name__}")
            return result
        except Exception as e:
            logger.exception(f"Exception in {func.__name__}")
            raise
    return wrapper

@log_debug
def clear_logs():
    """
    Clear or empty the main log file.
    """
    try:
        logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        log_file_path = os.path.join(logs_dir, 'debug.log')
        with open(log_file_path, 'w') as f:
            f.truncate(0)
    except FileNotFoundError:
        pass

@log_debug
def clean_old_results(directory, keep, file_prefix=None):
    """
    Clean the specified directory by keeping only the latest 'keep' subfolders and/or files.
    :param directory: The directory to clean.
    :param keep: Number of latest items to keep.
    :param file_prefix: If specified, clean files with this prefix (e.g., 'best_config_'); otherwise, clean subfolders.
    """
    if not os.path.exists(directory):
        return
    if file_prefix:
        items = [os.path.join(directory, f) for f in os.listdir(directory) 
                 if f.startswith(file_prefix) and f.endswith('.json')]
    else:
        items = [os.path.join(directory, d) for d in os.listdir(directory) 
                 if os.path.isdir(os.path.join(directory, d))]
    items.sort(key=os.path.getctime, reverse=True)
    for item in items[keep:]:
        if os.path.isdir(item):
            shutil.rmtree(item)
            # logger.info(f"Deleted old results folder: {item}")
        else:
            os.remove(item)
            # logger.info(f"Deleted old JSON file: {item}")

@log_debug
def print_status_with_progress(step, status, pbar):
    """
    Update the progress bar with the status of a step.
    :param step: Description of the step.
    :param status: Status of the step ('OK' or 'FAILED').
    :param pbar: The tqdm progress bar instance.
    """
    color = Fore.GREEN if status == "OK" else Fore.RED
    pbar.set_description(f"{step} [{color}{status}{Style.RESET_ALL}]")
    pbar.update(1)
    pbar.refresh()

@log_debug
def create_sample_ohlcv_data():
    """
    Create realistic sample OHLCV data based on config.json and save it as 'data/sample_ohlcv_data.parquet'.
    """
    start_date = config["data"]["start_date"]
    end_date = config["data"]["end_date"]
    interval = config["data"]["interval"]
    output_file = "data/sample_ohlcv_data.parquet"

    date_range = pd.date_range(start=start_date, end=end_date, freq=interval)
    n_points = len(date_range)
    # logger.info(f"Generating {n_points} data points from {start_date} to {end_date} with interval {interval}")

    np.random.seed(42)
    base_price = 150
    price_series = [base_price]
    for _ in range(n_points - 1):
        step = np.random.normal(0, 2) + 0.02
        price_series.append(max(10, price_series[-1] + step))

    close_prices = np.array(price_series)
    spread = np.random.uniform(2, 10, n_points)
    open_prices = close_prices + np.random.uniform(-spread / 2, spread / 2, n_points)
    high_prices = np.maximum(open_prices, close_prices) + spread * np.random.uniform(0.5, 1.5, n_points)
    low_prices = np.minimum(open_prices, close_prices) - spread * np.random.uniform(0.5, 1.5, n_points)

    open_prices = np.clip(open_prices, low_prices, high_prices)
    close_prices = np.clip(close_prices, low_prices, high_prices)

    volume_base = 5000
    volume_noise = np.random.randint(-2000, 2000, n_points)
    price_change = np.diff(close_prices, prepend=close_prices[0])
    volume = volume_base + (price_change * 1000) + volume_noise
    volume = np.clip(volume, 1000, 20000)

    df = pd.DataFrame({
        "Open": open_prices,
        "High": high_prices,
        "Low": low_prices,
        "Close": close_prices,
        "Volume": volume
    }, index=date_range)
    df.index.name = "Timestamp"

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    df.to_parquet(output_file, engine="pyarrow")
    # logger.info(f"Sample data saved to {output_file} with {len(df)} points")

@log_debug
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
        # logger.info(f"update_data.py output: {result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running update_data.py: {e.stderr}")
        print(f"Warning: Failed to update parquet data: {e.stderr}")

def notificaciones_habilitadas(tipo):
    config = load_config()
    notif = config.get('notifications', {})
    return notif.get('enabled', False) and notif.get('types', {}).get(tipo, False)

# logger.info("Cryptobot initialized. Logger is configured.")

if __name__ == "__main__":
    try:
        # logger.info("Step 0: Checking sample data generation.")
        with tqdm(total=1, desc="Step 0: Generate Sample Data", ncols=100, ascii=".-") as pbar:
            try:
                sample_data_path = "data/sample_ohlcv_data.parquet"
                if config["general"].get("generate_sample_data", False):
                    # logger.info("Generating sample data...")
                    create_sample_ohlcv_data()
                    file_path = sample_data_path
                    print_status_with_progress("Step 0: Generate Sample Data", "OK", pbar)
                else:
                    # logger.info("Using existing data file from config.")
                    file_path = config["data"]["data_file_path"]
                    pbar.set_description(f"Step 0: Generate Sample Data [{Fore.LIGHTBLACK_EX}DISABLE{Style.RESET_ALL}]")
                    pbar.update(1)
                    pbar.refresh()
            except Exception as e:
                logger.error(f"Step 0 failed: {e}", exc_info=True)
                print_status_with_progress("Step 0: Generate Sample Data", "FAILED", pbar)
                exit(1)

        # logger.info("Step 1: Initializing log clearing.")
        with tqdm(total=1, desc="Step 1: Clear Log Files", ncols=100, ascii=".-") as pbar:
            try:
                clear_logs()
                print_status_with_progress("Step 1: Clear Log Files", "OK", pbar)
            except Exception as e:
                logger.error(f"Step 1 failed: {e}", exc_info=True)
                print_status_with_progress("Step 1: Clear Log Files", "FAILED", pbar)
                exit(1)

        # logger.info("Step 2: Initializing configuration.")
        with tqdm(total=1, desc="Step 2: Configuration", ncols=100, ascii=".-") as pbar:
            try:
                initial_capital = config["general"]["initial_capital"]
                trade_fee = config["general"]["trade_fee"]
                investment_fraction = config["general"]["investment_fraction"]
                results_cleanup_limit = config["general"]["results_cleanup_limit"]
                enable_optimization = config["general"].get("enable_optimization", False)

                start_date = config["data"]["start_date"]
                end_date = config["data"]["end_date"]
                interval = config["data"]["interval"]
                output_dir = config["data"]["output_dir"]

                strategy_params = config["strategy"]

                print_status_with_progress("Step 2: Configuration", "OK", pbar)
            except Exception as e:
                logger.error(f"Step 2 failed: {e}", exc_info=True)
                print_status_with_progress("Step 2: Configuration", "FAILED", pbar)
                exit(1)

        # logger.info("Step 3: Initializing data update and loading.")
        with tqdm(total=1, desc="Step 3: Update and Load Data", ncols=100, ascii=".-") as pbar:
            try:
                # Update the Parquet file before loading
                update_parquet()

                # Load the updated data
                data_handler = DataHandler(file_path, start_date=start_date, end_date=end_date, interval=interval)
                data = data_handler.load_data()
                logger.debug("Data loaded successfully. Data shape: %s", data.shape)
                print_status_with_progress("Step 3: Update and Load Data", "OK", pbar)
            except Exception as e:
                logger.error(f"Step 3 failed: {e}", exc_info=True)
                print_status_with_progress("Step 3: Update and Load Data", "FAILED", pbar)
                exit(1)

        # logger.info("Step 4: Initializing data validation.")
        with tqdm(total=1, desc="Step 4: Validate Data", ncols=100, ascii=".-") as pbar:
            try:
                required_columns = ['Close', 'High', 'Low', 'Volume']
                missing_columns = [col for col in required_columns if col not in data.columns]
                if missing_columns:
                    raise ValueError(f"Missing required columns: {missing_columns}")
                if data.isnull().any().any():
                    raise ValueError("Data contains NaN values.")
                if len(data) < 100:
                    raise ValueError("Insufficient data for training.")
                print_status_with_progress("Step 4: Validate Data", "OK", pbar)
            except Exception as e:
                logger.error(f"Step 4 failed: {e}", exc_info=True)
                print_status_with_progress("Step 4: Validate Data", "FAILED", pbar)
                exit(1)

        # Filter future candles before evaluating the signal
        now = datetime.now()
        data_valid = data[data.index <= now]
        if not data_valid.empty:
            last_row = data_valid.iloc[-1]
            # Here you can call your signal logic, for example:
            # signal = strategy.entry_signal(last_row, data_valid)
        else:
            logger.warning("No valid candles to evaluate.")

        # logger.info("Step 5: Checking optimization status.")
        with tqdm(total=config["optimization"]["n_trials"], desc="Step 5: Optimization", ncols=100, ascii=".-", mininterval=0.1, dynamic_ncols=False) as pbar:
            try:
                if enable_optimization:
                    logger.info("Optimization enabled. Starting process...")
                    from core.optimize import run_optimization

                    def progress_callback(study, trial):
                        if pbar.n < pbar.total:
                            pbar.update(1)
                        if pbar.n >= pbar.total:
                            pbar.set_description(f"Step 5: Optimization [{Fore.GREEN}OK{Style.RESET_ALL}]")
                            pbar.close()

                    best_params = run_optimization(callback=progress_callback)
                    config["strategy"] = best_params
                    # logger.info(f"Loaded optimized parameters: {best_params}")

                    if not pbar.disable and pbar.n < pbar.total:
                        pbar.set_description(f"Step 5: Optimization [{Fore.GREEN}OK{Style.RESET_ALL}]")
                        pbar.update(pbar.total - pbar.n)

                else:
                    logger.info("Optimization disabled. Skipping process.")
                    pbar.set_description(f"Step 5: Optimization [{Fore.LIGHTBLACK_EX}DISABLE{Style.RESET_ALL}]")
                    pbar.update(config["optimization"]["n_trials"])
            except Exception as e:
                logger.error(f"Step 5 failed: {e}", exc_info=True)
                print_status_with_progress("Step 5: Optimization", "FAILED", pbar)
                exit(1)

        # logger.info("Step 6: Initializing strategy.")
        with tqdm(total=1, desc="Step 6: Strategy", ncols=100, ascii=".-") as pbar:
            try:
                if enable_optimization:
                    optimization_results_dir = config["optimization"]["optimization_results_dir"]
                    best_config_file = max(
                        [os.path.join(optimization_results_dir, f) for f in os.listdir(optimization_results_dir) if f.startswith("best_config_")],
                        key=os.path.getctime
                    )
                    with open(best_config_file, "r") as f:
                        loaded_data = json.load(f)
                        best_params = loaded_data["best_params"]
                        # logger.info(f"Loaded optimized parameters: {best_params}")
                        config["strategy"].update(best_params)

                strategy = Strategy(config["strategy"])
                print_status_with_progress("Step 6: Strategy", "OK", pbar)
            except Exception as e:
                logger.error(f"Step 6 failed: {e}", exc_info=True)
                print_status_with_progress("Step 6: Strategy", "FAILED", pbar)
                exit(1)

        # logger.info("Step 7: Initializing backtest.")
        with tqdm(total=1, desc="Step 7: Run Backtest", ncols=100, ascii=".-") as pbar:
            try:
                backtester = Backtester(
                    data=data,
                    strategy=strategy,
                    initial_capital=initial_capital,
                    trade_fee=trade_fee,
                    investment_fraction=investment_fraction,
                    debug=False
                )
                backtester.run()
                print_status_with_progress("Step 7: Run Backtest", "OK", pbar)
            except Exception as e:
                logger.error(f"Step 7 failed: {e}", exc_info=True)
                print_status_with_progress("Step 7: Run Backtest", "FAILED", pbar)
                exit(1)

        # logger.info("Step 8: Initializing metrics generation and plotting.")
        with tqdm(total=1, desc="Step 8: Generate Metrics", ncols=100, ascii=".-") as pbar:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                results_dir = os.path.join(output_dir, timestamp)
                os.makedirs(results_dir, exist_ok=True)

                metrics = backtester.calculate_metrics()
                metrics_file = os.path.join(results_dir, "metrics.json")
                with open(metrics_file, "w") as f:
                    json.dump(metrics, f, indent=4)
                logger.info(f"Metrics saved to {metrics_file}")

                trade_log = backtester.generate_trade_log()
                if not trade_log.empty:
                    trade_log_file = os.path.join(results_dir, "trades.json")
                    trade_log.to_json(trade_log_file, orient="records", indent=4)
                    logger.info(f"Trade log saved to {trade_log_file}")
                else:
                    logger.warning("No trades were made during the backtest.")

                backtester.plot_results(output_folder=results_dir, output_file="plot.png")
                
                plot_path = os.path.join(results_dir, "plot.png")
                if os.path.exists(plot_path):
                    try:
                        import matplotlib.pyplot as plt
                        import matplotlib.image as mpimg
                        import json

                        img = mpimg.imread(plot_path)

                        fig = plt.figure(figsize=(10, 8), constrained_layout=True)
                        fig.canvas.manager.window.state('normal')

                        ax1 = fig.add_subplot(3, 1, (1, 2))
                        im = ax1.imshow(img, aspect='equal')
                        ax1.axis('off')
                        ax1.set_title("Backtest Results", pad=20)

                        im.set_extent([0, img.shape[1], 0, img.shape[0]])

                        ax2 = fig.add_subplot(3, 1, 3)
                        ax2.axis('off')

                        metrics_title = "Metrics Summary"
                        metrics_formatted = {
                            "capital": {
                                "initial": metrics['capital']['initial'],
                                "final": metrics['capital']['final'],
                                "total_profit": metrics['capital']['total_profit'],
                                "pl_percent": metrics['capital']['pl_percent']
                            },
                            "trades": {
                                "number_of_trades": metrics['trades']['number_of_trades'],
                                "win_rate": metrics['trades']['win_rate'],
                                "avg_trade_duration_hours": metrics['trades']['avg_trade_duration_hours'],
                                "profit_factor": metrics['trades']['profit_factor'],
                                "expectancy": metrics['trades']['expectancy']
                            },
                            "fees": {
                                "total_fees": metrics['fees']['total_fees']
                            },
                            "performance": {
                                "max_drawdown": metrics['performance']['max_drawdown'],
                                "sharpe_ratio": metrics['performance']['sharpe_ratio'],
                                "sortino_ratio": metrics['performance']['sortino_ratio']
                            },
                            "buy_and_hold": {
                                "final_capital": metrics['buy_and_hold']['final_capital'],
                                "profit": metrics['buy_and_hold']['profit'],
                                "pl_percent": metrics['buy_and_hold']['pl_percent']
                            }
                        }

                        metrics_lines = []
                        for category, values in metrics_formatted.items():
                            values_str = json.dumps(values, ensure_ascii=False)
                            metrics_lines.append(f'"{category}": {values_str}')

                        metrics_text = ",\n".join(metrics_lines)

                        ax2.text(0.5, 0.95, metrics_title, fontsize=14, ha='center', va='top', fontweight='bold')
                        ax2.text(0.2, 0.85, metrics_text, fontsize=8, ha='left', va='top', wrap=True, 
                                 bbox=dict(boxstyle="round", facecolor="white", alpha=0.8, pad=0.5), 
                                 fontfamily='monospace')

                        plt.show()
                    except Exception as e:
                        logger.error(f"Failed to display plot file: {e}")
                else:
                    logger.warning(f"Plot file not found at {plot_path}")
                
                clean_old_results(directory=output_dir, keep=config["general"]["results_cleanup_limit"])

                print_status_with_progress("Step 8: Generate Metrics", "OK", pbar)
            except Exception as e:
                logger.error(f"Step 8 failed: {e}", exc_info=True)
                print_status_with_progress("Step 8: Generate Metrics", "FAILED", pbar)
                exit(1)

    except Exception as e:
        logger.critical(f"An unexpected error occurred: {e}", exc_info=True)
        if notificaciones_habilitadas('critical_error'):
            send_email(**format_critical_error())
        exit(1)