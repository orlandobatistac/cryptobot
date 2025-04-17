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
from logger import logger

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

# Configurar verbosidad de Optuna dependiendo de cómo se ejecuta el archivo
if __name__ != "__main__":
    # Si se importa (ej. desde main.py), silenciar los detalles de los trials
    optuna.logging.set_verbosity(optuna.logging.WARNING)
else:
    # Si se ejecuta directamente (python optimize.py), mostrar todos los detalles
    optuna.logging.set_verbosity(optuna.logging.INFO)

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
slippage = base_config["general"].get("slippage", 0.0001)  # Default 0.01%
spread = base_config["general"].get("spread", 0.00015)  # Default 0.015%
n_trials = base_config["optimization"]["n_trials"]
optimization_results_dir = base_config["optimization"]["optimization_results_dir"]
results_cleanup_limit = base_config["general"]["results_cleanup_limit"]

def objective(trial):
    # Test different combinations of hyperparameters
    config = {
        "sma_short": trial.suggest_int("sma_short", 5, 100),
        "sma_long": trial.suggest_int("sma_long", trial.params["sma_short"] + 1, 300),
        "rsi_period": trial.suggest_int("rsi_period", 5, 50),
        "rsi_threshold": trial.suggest_int("rsi_threshold", 30, 90),
        "macd_fast": trial.suggest_int("macd_fast", 5, 30),
        "macd_slow": trial.suggest_int("macd_slow", 20, 60),
        "macd_signal": trial.suggest_int("macd_signal", 5, 30),
        "volume_sma_period": trial.suggest_int("volume_sma_period", 5, 50),
        "atr_period": trial.suggest_int("atr_period", 5, 40),
        "adx_period": trial.suggest_int("adx_period", 5, 40),
        "adx_threshold": trial.suggest_int("adx_threshold", 30, 60),
        "bollinger_period": trial.suggest_int("bollinger_period", 10, 50),
        "bollinger_std_dev": trial.suggest_float("bollinger_std_dev", 1.0, 4.0),
        "supertrend_multiplier": trial.suggest_float("supertrend_multiplier", 0.5, 6.0),
        "use_supertrend": trial.suggest_categorical("use_supertrend", [True, False]),
        "macd_threshold": trial.suggest_int("macd_threshold", 1, 50),
        "stop_loss_atr_multiplier": trial.suggest_float("stop_loss_atr_multiplier", 0.5, 5.0),
        "use_adx_positive": trial.suggest_categorical("use_adx_positive", [True, False]),
        "use_macd_positive": trial.suggest_categorical("use_macd_positive", [True, False]),
        "trailing_stop_percentage": trial.suggest_float("trailing_stop_percentage", 0.05, 0.2),
        "take_profit_multiplier": trial.suggest_float("take_profit_multiplier", 5, 30),
        "stop_loss_multiplier": trial.suggest_float("stop_loss_multiplier", 0.3, 1.5),
        "time_based_stop_days": trial.suggest_int("time_based_stop_days", 1, 5),
        "time_based_stop_loss_percent": trial.suggest_float("time_based_stop_loss_percent", -8.0, -3.0),
        "lateral_adx_threshold": trial.suggest_int("lateral_adx_threshold", 15, 30),
        "support_margin": trial.suggest_float("support_margin", 1.02, 1.10),
        "resistance_margin": trial.suggest_float("resistance_margin", 0.90, 0.98)
    }

    try:
        # Load and prepare data
        data_handler = DataHandler(file_path, start_date, end_date, interval)
        data = data_handler.load_data()
        if data.empty:
            logger.error("Data is empty. Cannot proceed with trial.")
            return -9999  # Penalize empty data

        # Calculate indicators
        strategy = Strategy(config)
        strategy.calculate_indicators(data)
        if data.isnull().any().any():
            logger.warning("Data contains NaN values after calculating indicators.")

        # Run backtest with the flag `from_optimize=True`
        backtester = Backtester(
            data=data,
            strategy=strategy,
            initial_capital=initial_capital,
            trade_fee=trade_fee,
            investment_fraction=investment_fraction,
            from_optimize=True,  # Pass the flag
            debug=True  # Enable debug mode for detailed logs
        )
        backtester.slippage = slippage
        backtester.spread = spread

        backtester.run()
        if not backtester.trades:
            logger.warning("No trades were executed during the backtest.")

        metrics = backtester.calculate_metrics()
        trial.set_user_attr("start_date", start_date)
        trial.set_user_attr("end_date", end_date)
        trial.set_user_attr("pl_percent", metrics["capital"]["pl_percent"])
        trial.set_user_attr("sharpe_ratio", metrics["performance"]["sharpe_ratio"])
        trial.set_user_attr("max_drawdown", metrics["performance"]["max_drawdown"])

        return metrics["capital"]["pl_percent"]  # Maximize this metric

    except Exception as e:
        logger.error(f"Error during trial: {e}", exc_info=True)
        return -9999  # Penalize configurations that fail

def run_optimization(callback=None):
    study = optuna.create_study(
        storage="sqlite:///optuna_study.db",
        study_name="trading_strategy",
        direction="maximize",
        load_if_exists=True
    )
    study.optimize(objective, n_trials=n_trials, callbacks=[callback] if callback else None)
    
    # Guardar resultados
    os.makedirs(optimization_results_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
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
            "start_date": start_date,
            "end_date": end_date,
            "interval": interval,
            "initial_capital": initial_capital,
            "trade_fee": trade_fee,
            "spread": spread,
            "slippage": slippage,
            "investment_fraction": investment_fraction
        }
    }

    with open(file_path, "w") as f:
        json.dump(output_data, f, indent=4)
    logging.info(f"Best parameters saved to {file_path}")

    clean_old_results(optimization_results_dir, results_cleanup_limit, file_prefix="best_config_")

    return study.best_params

if __name__ == "__main__":
    best_params = run_optimization()
    study = optuna.load_study(study_name="trading_strategy", storage="sqlite:///optuna_study.db")
    print("\nBest configuration:")
    print(json.dumps(best_params, indent=4))
    print(f"\nBest pl_percent: {study.best_value:.2f}%")