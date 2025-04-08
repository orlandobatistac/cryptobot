# main_updated.py

from logger import logger
from functools import wraps
from tqdm import tqdm
from colorama import Fore, Style
from data import DataHandler
from strategy import Strategy
from backtest import Backtester
from datetime import datetime
import json
import os
import shutil
import logging
import pandas as pd
import numpy as np

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
        with open('debug.log', 'w') as f:
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
            logger.info(f"Deleted old results folder: {item}")
        else:
            os.remove(item)
            logger.info(f"Deleted old JSON file: {item}")

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
    # Extract data settings from config
    start_date = config["data"]["start_date"]
    end_date = config["data"]["end_date"]
    interval = config["data"]["interval"]
    output_file = "data/sample_ohlcv_data.parquet"

    # Generate date range
    date_range = pd.date_range(start=start_date, end=end_date, freq=interval)
    n_points = len(date_range)
    logger.info(f"Generating {n_points} data points from {start_date} to {end_date} with interval {interval}")

    # Generate a trending price series with random walk
    np.random.seed(42)
    base_price = 150  # Starting price
    price_series = [base_price]
    for _ in range(n_points - 1):
        step = np.random.normal(0, 2) + 0.02  # Slight upward bias
        price_series.append(max(10, price_series[-1] + step))  # Avoid negative prices

    close_prices = np.array(price_series)
    spread = np.random.uniform(2, 10, n_points)  # Dynamic spread
    open_prices = close_prices + np.random.uniform(-spread / 2, spread / 2, n_points)
    high_prices = np.maximum(open_prices, close_prices) + spread * np.random.uniform(0.5, 1.5, n_points)
    low_prices = np.minimum(open_prices, close_prices) - spread * np.random.uniform(0.5, 1.5, n_points)

    # Ensure coherence
    open_prices = np.clip(open_prices, low_prices, high_prices)
    close_prices = np.clip(close_prices, low_prices, high_prices)

    # Generate volume correlated with price changes
    volume_base = 5000
    volume_noise = np.random.randint(-2000, 2000, n_points)
    price_change = np.diff(close_prices, prepend=close_prices[0])
    volume = volume_base + (price_change * 1000) + volume_noise
    volume = np.clip(volume, 1000, 20000)

    # Create DataFrame with Timestamp as index only
    df = pd.DataFrame({
        "Open": open_prices,
        "High": high_prices,
        "Low": low_prices,
        "Close": close_prices,
        "Volume": volume
    }, index=date_range)
    df.index.name = "Timestamp"

    # Save to .parquet file
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    df.to_parquet(output_file, engine="pyarrow")
    logger.info(f"Sample data saved to {output_file} with {len(df)} points")

logger.info("Cryptobot initialized. Logger is configured.")

if __name__ == "__main__":
    try:
        # Step 0: Generate Sample Data (Optional)
        logger.info("Step 0: Checking sample data generation.")
        with tqdm(total=1, desc="Step 0: Generate Sample Data", ncols=100, ascii=".-") as pbar:
            try:
                sample_data_path = "data/sample_ohlcv_data.parquet"
                if config["general"].get("generate_sample_data", False):
                    logger.info("Generating sample data...")
                    create_sample_ohlcv_data()
                    file_path = sample_data_path
                    print_status_with_progress("Step 0: Generate Sample Data", "OK", pbar)
                else:
                    logger.info("Using existing data file from config.")
                    file_path = config["data"]["data_file_path"]
                    pbar.set_description(f"Step 0: Generate Sample Data [{Fore.LIGHTBLACK_EX}DISABLE{Style.RESET_ALL}]")
                    pbar.update(1)
                    pbar.refresh()
            except Exception as e:
                logger.error(f"Step 0 failed: {e}", exc_info=True)
                print_status_with_progress("Step 0: Generate Sample Data", "FAILED", pbar)
                exit(1)

        # Step 1: Clear Log Files
        logger.info("Step 1: Initializing log clearing.")
        with tqdm(total=1, desc="Step 1: Clear Log Files", ncols=100, ascii=".-") as pbar:
            try:
                clear_logs()
                print_status_with_progress("Step 1: Clear Log Files", "OK", pbar)
            except Exception as e:
                logger.error(f"Step 1 failed: {e}", exc_info=True)
                print_status_with_progress("Step 1: Clear Log Files", "FAILED", pbar)
                exit(1)

        # Step 2: Configuration
        logger.info("Step 2: Initializing configuration.")
        with tqdm(total=1, desc="Step 2: Configuration", ncols=100, ascii=".-") as pbar:
            try:
                # General settings
                initial_capital = config["general"]["initial_capital"]
                trade_fee = config["general"]["trade_fee"]
                investment_fraction = config["general"]["investment_fraction"]
                results_cleanup_limit = config["general"]["results_cleanup_limit"]
                enable_optimization = config["general"].get("enable_optimization", False)

                # Data settings
                start_date = config["data"]["start_date"]
                end_date = config["data"]["end_date"]
                interval = config["data"]["interval"]
                output_dir = config["data"]["output_dir"]

                # Strategy parameters
                strategy_params = config["strategy"]

                print_status_with_progress("Step 2: Configuration", "OK", pbar)
            except Exception as e:
                logger.error(f"Step 2 failed: {e}", exc_info=True)
                print_status_with_progress("Step 2: Configuration", "FAILED", pbar)
                exit(1)

        # Step 3: Load Data
        logger.info("Step 3: Initializing data loading.")
        with tqdm(total=1, desc="Step 3: Load Data", ncols=100, ascii=".-") as pbar:
            try:
                data_handler = DataHandler(file_path, start_date=start_date, end_date=end_date, interval=interval)
                data = data_handler.load_data()
                logger.debug("Data loaded successfully. Data shape: %s", data.shape)
                print_status_with_progress("Step 3: Load Data", "OK", pbar)
            except Exception as e:
                logger.error(f"Step 3 failed: {e}", exc_info=True)
                print_status_with_progress("Step 3: Load Data", "FAILED", pbar)
                exit(1)

        # Step 4: Validate Data
        logger.info("Step 4: Initializing data validation.")
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

        # Step 5: Optimization (Optional)
        logger.info("Step 5: Checking optimization status.")
        with tqdm(total=1, desc="Step 5: Optimization", ncols=100, ascii=".-") as pbar:
            try:
                if enable_optimization:
                    logger.info("Optimization enabled. Starting process...")
                    from optimize import objective
                    import optuna

                    optuna_logger = logging.getLogger("optuna")
                    optuna_logger.setLevel(logging.WARNING)
                    for handler in optuna_logger.handlers[:]:
                        if isinstance(handler, logging.StreamHandler):
                            optuna_logger.removeHandler(handler)
                    optuna_handler = logging.FileHandler("debug.log", mode="a", encoding="utf-8")
                    optuna_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
                    optuna_logger.addHandler(optuna_handler)

                    def progress_callback(study, trial):
                        pbar.total = config["optimization"]["n_trials"]
                        pbar.update(1)
                        pbar.refresh()

                    study = optuna.create_study(
                        storage="sqlite:///optuna_study.db",
                        study_name="trading_strategy",
                        direction="maximize",
                        load_if_exists=True
                    )
                    study.optimize(objective, n_trials=config["optimization"]["n_trials"], callbacks=[progress_callback])
                    optuna_logger.removeHandler(optuna_handler)

                    optimization_results_dir = config["optimization"]["optimization_results_dir"]
                    os.makedirs(optimization_results_dir, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    file_name = f"best_config_{timestamp}.json"
                    file_path = os.path.join(optimization_results_dir, file_name)

                    best_trial = study.best_trial
                    output_data = {
                        "best_params": best_trial.params,
                        "metrics": {
                            "pl_percent": best_trial.user_attrs.get("pl_percent"),
                            "sharpe_ratio": best_trial.user_attrs.get("sharpe_ratio"),
                            "max_drawdown": best_trial.user_attrs.get("max_drawdown"),
                        },
                        "data_used": {
                            "start_date": best_trial.user_attrs.get("start_date"),
                            "end_date": best_trial.user_attrs.get("end_date"),
                            "interval": best_trial.user_attrs.get("interval"),
                            "initial_capital": best_trial.user_attrs.get("initial_capital"),
                            "trade_fee": best_trial.user_attrs.get("trade_fee"),
                            "investment_fraction": best_trial.user_attrs.get("investment_fraction"),
                        }
                    }
                    with open(file_path, "w") as f:
                        json.dump(output_data, f, indent=4)
                    logger.info(f"Best parameters saved to {file_path}")

                    clean_old_results(directory=optimization_results_dir, keep=results_cleanup_limit, file_prefix="best_config_")

                    best_config_file = max(
                        [os.path.join(optimization_results_dir, f) for f in os.listdir(optimization_results_dir) if f.startswith("best_config_")],
                        key=os.path.getctime
                    )
                    with open(best_config_file, "r") as f:
                        loaded_data = json.load(f)
                        best_config = loaded_data["best_params"]
                    config["strategy"] = best_config
                    logger.info(f"Loaded optimized parameters: {config['strategy']}")

                    print_status_with_progress("Step 5: Optimization", "OK", pbar)
                else:
                    logger.info("Optimization disabled. Skipping process.")
                    pbar.set_description(f"Step 5: Optimization [{Fore.LIGHTBLACK_EX}DISABLE{Style.RESET_ALL}]")
                    pbar.update(1)
                    pbar.refresh()
            except Exception as e:
                logger.error(f"Step 5 failed: {e}", exc_info=True)
                print_status_with_progress("Step 5: Optimization", "FAILED", pbar)
                exit(1)

        # Step 6: Prepare Strategy and Indicators
        logger.info("Step 6: Initializing strategy and calculating indicators.")
        with tqdm(total=1, desc="Step 6: Strategy and Indicators", ncols=100, ascii=".-") as pbar:
            try:
                strategy = Strategy(config["strategy"])
                strategy.calculate_indicators(data)
                data.dropna(inplace=True)
                print_status_with_progress("Step 6: Strategy and Indicators", "OK", pbar)
            except Exception as e:
                logger.error(f"Step 6 failed: {e}", exc_info=True)
                print_status_with_progress("Step 6: Strategy and Indicators", "FAILED", pbar)
                exit(1)

        # Step 7: Run Backtest
        logger.info("Step 7: Initializing backtest.")
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

        # Step 8: Generate Metrics and Plot Results
        logger.info("Step 8: Initializing metrics generation and plotting.")
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
                
                clean_old_results(directory=output_dir, keep=config["general"]["results_cleanup_limit"])

                print_status_with_progress("Step 8: Generate Metrics", "OK", pbar)
            except Exception as e:
                logger.error(f"Step 8 failed: {e}", exc_info=True)
                print_status_with_progress("Step 8: Generate Metrics", "FAILED", pbar)
                exit(1)

    except Exception as e:
        logger.critical(f"An unexpected error occurred: {e}", exc_info=True)
        exit(1)