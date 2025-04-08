import optuna
import json
from data import DataHandler
from strategy import Strategy
from backtest import Backtester
import os
import warnings
import datetime
import logging
from main import clean_old_results

warnings.filterwarnings("ignore")

# Clear the debug.log file at the start of the script
def clear_debug_log():
    try:
        with open("debug.log", "w") as f:
            f.truncate(0)
    except FileNotFoundError:
        pass

clear_debug_log()  # Call the function to clear the log file

# Configure logging to write to a file
logging.basicConfig(
    filename="debug.log",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Load base configuration
with open("config.json") as f:
    base_config = json.load(f)

# Update to match the new structure in config.json
file_path = base_config["data"]["data_file_path"]
start_date = base_config["data"]["start_date"]
end_date = base_config["data"]["end_date"]
interval = base_config["data"]["interval"]
initial_capital = base_config["general"]["initial_capital"]
trade_fee = base_config["general"]["trade_fee"]
investment_fraction = base_config["general"]["investment_fraction"]
n_trials = base_config["optimization"]["n_trials"]
optimization_results_dir = base_config["optimization"]["optimization_results_dir"]
results_cleanup_limit = base_config["general"]["results_cleanup_limit"]

def objective(trial):
    # Test different combinations of hyperparameters
    config = {
        "sma_short": trial.suggest_int("sma_short", 5, 50),
        "sma_long": trial.suggest_int("sma_long", 20, 200),
        "rsi_period": trial.suggest_int("rsi_period", 5, 30),
        "rsi_threshold": trial.suggest_int("rsi_threshold", 50, 90),
        "macd_fast": trial.suggest_int("macd_fast", 5, 20),
        "macd_slow": trial.suggest_int("macd_slow", 20, 40),
        "macd_signal": trial.suggest_int("macd_signal", 5, 20),
        "volume_sma_period": trial.suggest_int("volume_sma_period", 5, 30),
        "atr_period": trial.suggest_int("atr_period", 5, 30),
        "adx_period": trial.suggest_int("adx_period", 5, 30),
        "adx_threshold": trial.suggest_int("adx_threshold", 10, 30),
        "bollinger_period": trial.suggest_int("bollinger_period", 10, 30),
        "bollinger_std_dev": trial.suggest_float("bollinger_std_dev", 1.5, 3.0),
        "supertrend_multiplier": trial.suggest_float("supertrend_multiplier", 1.0, 5.0),
        "use_supertrend": False,
        "macd_threshold": 100,
        "stop_loss_atr_multiplier": trial.suggest_float("stop_loss_atr_multiplier", 0.5, 3.0),
        "use_adx_positive": True,
        "use_macd_positive": False,
        "trailing_stop_percentage": trial.suggest_float("trailing_stop_percentage", 0.01, 0.05)
    }

    try:
        # Load and prepare data
        data_handler = DataHandler(file_path, start_date, end_date, interval)
        data = data_handler.load_data()

        # Calculate indicators
        strategy = Strategy(config)
        strategy.calculate_indicators(data)

        # Run backtest with the flag `from_optimize=True`
        backtester = Backtester(
            data=data,
            strategy=strategy,
            initial_capital=initial_capital,
            trade_fee=trade_fee,
            investment_fraction=investment_fraction,
            from_optimize=True  # Pass the flag
        )
        backtester.run()
        metrics = backtester.calculate_metrics()

        # Add additional metrics to the result
        trial.set_user_attr("start_date", start_date)
        trial.set_user_attr("end_date", end_date)
        trial.set_user_attr("interval", interval)
        trial.set_user_attr("initial_capital", initial_capital)
        trial.set_user_attr("trade_fee", trade_fee)
        trial.set_user_attr("investment_fraction", investment_fraction)
        trial.set_user_attr("pl_percent", metrics["pl_percent"])
        trial.set_user_attr("sharpe_ratio", metrics.get("sharpe_ratio", None))
        trial.set_user_attr("max_drawdown", metrics.get("max_drawdown", None))

        return metrics["pl_percent"]  # Maximize this metric

    except Exception as e:
        return -9999  # Penalize configurations that fail

if __name__ == "__main__":
    # Use SQLite storage for persistent study
    study = optuna.create_study(
        storage="sqlite:///optuna_study.db",
        study_name="trading_strategy",
        direction="maximize",
        load_if_exists=True
    )
    study.optimize(objective, n_trials=n_trials)

    print("\nBest configuration:")
    print(json.dumps(study.best_params, indent=4))
    print(f"\nBest pl_percent: {study.best_value:.2f}%")

    # Save best results
    try:
        os.makedirs(optimization_results_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"best_config_{timestamp}.json"
        file_path = os.path.join(optimization_results_dir, file_name)

        # Include additional data in the output
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

        print(f"\nFile successfully saved at: {file_path}")
        logging.info(f"File successfully saved at: {file_path}")

        clean_old_results(optimization_results_dir, results_cleanup_limit, file_prefix="best_config_")

    except Exception as e:
        error_message = f"Error saving the file: {e}"
        print(f"\n{error_message}")
        logging.error(error_message)
