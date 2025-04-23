# backtest.py

import pandas as pd
import numpy as np
import mplfinance as mpf
import os
from datetime import datetime
from logger import logger
from functools import wraps
import json

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

class Backtester:
    def __init__(self, data, strategy, initial_capital, trade_fee, investment_fraction, from_optimize=False, debug=False):
        """
        Initialize the backtester.
        :param data: Historical OHLCV data.
        :param strategy: Trading strategy object.
        :param initial_capital: Starting capital (required, no default).
        :param trade_fee: Fee per trade as a fraction (e.g., 0.001 = 0.1%) (required, no default).
        :param investment_fraction: Fraction of available capital to invest in each trade (required, no default).
        :param from_optimize: Flag to indicate if the backtest is part of an optimization process.
        :param debug: Enable debug logging.
        """
        self.data = data
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.capital = initial_capital  # Current capital, updated with reinvested profits
        self.trade_fee = trade_fee
        self.investment_fraction = investment_fraction  # Fraction of capital to invest per trade
        self.trades = []
        self.final_capital = initial_capital
        self.from_optimize = from_optimize  # Store the flag
        self.debug = debug
        self.trade_id = 0  # Added to track trade IDs

        # Load configuration
        with open("config.json", "r") as config_file:
            self.config = json.load(config_file)
        self.spread = self.config["general"].get("spread", 0.00015) # Default 0.015%
        self.slippage = self.config["general"].get("slippage", 0.0001)  # Default 0.01%

    @log_debug
    def run(self):
        """
        Execute the backtest by iterating through the data with spread and slippage.
        """
        logger.info("Starting backtest. Initial capital: %s, Spread: %s, Slippage: %s", 
                    self.initial_capital, self.spread, self.slippage)
        if self.data.empty:
            logger.error("Data is empty. Cannot run backtest.")
            raise ValueError("Data is empty. Cannot run backtest.")

        # Calculate indicators before starting the backtest
        self.strategy.calculate_indicators(self.data)
        if self.data.empty:
            logger.error("Data is empty after calculating indicators. Cannot run backtest.")
            raise ValueError("Data is empty after calculating indicators. Cannot run backtest.")

        position = None
        for i, row in self.data.iterrows():
            logger.debug("Processing row at index: %s", row.name)
            try:
                # Check for entry signal
                if position is None:
                    entry_signal = self.strategy.entry_signal(row, self.data, is_backtest=True)
                    if entry_signal:
                        logger.info("Entry signal detected at %s. Base price: %s", row.name, row['Close'])
                        self.trade_id += 1
                        # Apply spread and slippage to entry price
                        entry_price = row['Close'] * (1 + self.spread + self.slippage)
                        investment_amount = self.capital * self.investment_fraction
                        shares = investment_amount / entry_price
                        position = {
                            'trade_id': self.trade_id,
                            'entry_price': entry_price,
                            'entry_time': row.name,
                            'shares': shares
                        }
                        logger.info("Entry executed. Adjusted entry price (spread + slippage): %s", entry_price)
                        continue

                # Check for exit signal
                if position:
                    exit_signal = self.strategy.exit_signal(row, self.data, is_backtest=True)
                    if exit_signal:
                        logger.info("Exit signal detected at %s. Base price: %s", row.name, row['Close'])
                        # Apply spread and slippage to exit price
                        exit_price = row['Close'] * (1 - self.spread - self.slippage)
                        position['exit_price'] = exit_price
                        position['exit_time'] = row.name
                        profit = (position['exit_price'] - position['entry_price']) * position['shares']
                        trade_fee = (position['entry_price'] + position['exit_price']) * position['shares'] * self.trade_fee
                        profit -= trade_fee
                        position['profit'] = profit
                        self.capital += profit
                        self.final_capital = self.capital
                        self.trades.append(position)
                        logger.info("Trade closed. Adjusted exit price (spread + slippage): %s, Profit: %s", 
                                    exit_price, profit)
                        position = None
                        self.strategy.position_open = False
                        continue

            except Exception as e:
                logger.error(f"Error processing row at {row.name}: {e}")
                raise

        # Close any open position at the end
        if position:
            logger.info("Closing remaining position at %s with base price %s", 
                        self.data.index[-1], self.data['Close'].iloc[-1])
            exit_price = self.data['Close'].iloc[-1] * (1 - self.spread - self.slippage)
            position['exit_price'] = exit_price
            position['exit_time'] = self.data.index[-1]
            profit = (position['exit_price'] - position['entry_price']) * position['shares']
            trade_fee = (position['entry_price'] + position['exit_price']) * position['shares'] * self.trade_fee
            profit -= trade_fee
            position['profit'] = profit
            self.capital += profit
            self.final_capital = self.capital
            self.trades.append(position)
            logger.info("Final trade closed. Adjusted exit price (spread + slippage): %s, Profit: %s", 
                        exit_price, profit)

        logger.info("Backtest completed. Final capital: %s", self.final_capital)

    @log_debug
    def calculate_metrics(self):
        """
        Calculate performance metrics.
        :return: Dictionary with metrics.
        """
        try:
            total_profit = self.final_capital - self.initial_capital
            pl_percentage = (total_profit / self.initial_capital) * 100
            num_trades = len(self.trades)
            win_rate = sum(1 for trade in self.trades if trade['profit'] > 0) / num_trades if num_trades > 0 else 0

            # Calculate total fees (each trade has an entry and exit, so 2 fees per trade)
            total_fees = 0
            for trade in self.trades:
                entry_fee = trade['entry_price'] * trade['shares'] * self.trade_fee
                exit_fee = trade['exit_price'] * trade['shares'] * self.trade_fee
                total_fees += (entry_fee + exit_fee)

            # Calculate equity curve and max drawdown
            equity_curve = [self.initial_capital]
            for trade in self.trades:
                equity_curve.append(equity_curve[-1] + trade['profit'])
            equity_array = np.array(equity_curve)
            max_drawdown = min(0, min(equity_array - np.maximum.accumulate(equity_array)))

            # Buy and hold performance
            if self.trades:
                first_trade_open_price = self.trades[0]['entry_price']
                last_trade_close_price = self.trades[-1]['exit_price']
                logger.info("Buy and Hold (Trade Range): First trade open price: %s, Last trade close price: %s", 
                            first_trade_open_price, last_trade_close_price)
                shares = self.initial_capital / first_trade_open_price
                buy_and_hold_profit = (last_trade_close_price - first_trade_open_price) * shares
                buy_and_hold_final_capital = self.initial_capital + buy_and_hold_profit
                buy_and_hold_pl_percentage = (buy_and_hold_profit / self.initial_capital) * 100
            else:
                logger.warning("No trades available for buy-and-hold calculation.")
                buy_and_hold_profit = 0
                buy_and_hold_final_capital = self.initial_capital
                buy_and_hold_pl_percentage = 0

            # New Metrics
            # 1. Sharpe Ratio (assuming risk-free rate = 0 for simplicity)
            returns = np.diff(equity_curve) / equity_curve[:-1] if len(equity_curve) > 1 else [0]
            sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) != 0 else 0

            # 2. Sortino Ratio (downside risk only)
            downside_returns = [min(r, 0) for r in returns]
            sortino_ratio = np.mean(returns) / np.std(downside_returns) * np.sqrt(252) if np.std(downside_returns) != 0 else 0

            # 3. Average Trade Duration
            trade_durations = [(trade['exit_time'] - trade['entry_time']).total_seconds() / 3600 for trade in self.trades]
            avg_trade_duration_hours = sum(trade_durations) / num_trades if num_trades > 0 else 0

            # 4. Profit Factor
            gross_profit = sum(trade['profit'] for trade in self.trades if trade['profit'] > 0)
            gross_loss = abs(sum(trade['profit'] for trade in self.trades if trade['profit'] < 0))
            profit_factor = gross_profit / gross_loss if gross_loss != 0 else float('inf')

            # 5. Expectancy
            avg_win = gross_profit / sum(1 for trade in self.trades if trade['profit'] > 0) if win_rate > 0 else 0
            num_losses = sum(1 for trade in self.trades if trade['profit'] < 0)
            avg_loss = gross_loss / num_losses if num_losses > 0 else 0
            expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

            return {
                "capital": {
                    "initial": float(self.initial_capital),
                    "final": float(self.final_capital),
                    "total_profit": float(total_profit),
                    "pl_percent": round(pl_percentage, 2)
                },
                "trades": {
                    "number_of_trades": num_trades,
                    "win_rate": round(win_rate * 100, 2),
                    "avg_trade_duration_hours": round(avg_trade_duration_hours, 2),
                    "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else "inf",
                    "expectancy": round(expectancy, 2)
                },
                "fees": {
                    "total_fees": round(total_fees, 2)
                },
                "performance": {
                    "max_drawdown": round(max_drawdown, 2),
                    "sharpe_ratio": round(sharpe_ratio, 2),
                    "sortino_ratio": round(sortino_ratio, 2)
                },
                "buy_and_hold": {
                    "final_capital": float(buy_and_hold_final_capital),
                    "profit": float(buy_and_hold_profit),
                    "pl_percent": round(buy_and_hold_pl_percentage, 2)
                }
            }
        except Exception as e:
            logger.error(f"Error calculating metrics: {e}")
            raise

    @log_debug
    def generate_trade_log(self, format_for_display=False):
        """
        Generate a trade log.
        :param format_for_display: If True, format values with $ and %.
        :return: DataFrame with trade details.
        """
        if not self.trades:
            logger.warning("No trades were made during the backtest.")
            return pd.DataFrame()

        trade_log = pd.DataFrame(self.trades)
        if 'exit_time' not in trade_log.columns or 'entry_time' not in trade_log.columns:
            logger.error("Missing 'entry_time' or 'exit_time' in trade log.")
            raise ValueError("Missing 'entry_time' or 'exit_time' in trade log.")

        trade_log['duration_ms'] = trade_log['exit_time'] - trade_log['entry_time']
        trade_log['profit_percent'] = (trade_log['profit'] / (trade_log['entry_price'] * trade_log['shares'])) * 100
        # Removed redundant insertion of trade_id since it's already added in run()

        if format_for_display:
            display_log = trade_log.copy()
            display_log['entry_price'] = display_log['entry_price'].map(lambda x: f"${x:,.2f}")
            display_log['exit_price'] = display_log['exit_price'].map(lambda x: f"${x:,.2f}")
            display_log['profit'] = display_log['profit'].map(lambda x: f"${x:,.2f}")
            display_log['profit_percent'] = display_log['profit_percent'].map(lambda x: f"{x:.2f}%")
            logger.info("\nTrade Log:\n%s", display_log.to_string(index=False))

        return trade_log

    @log_debug
    def plot_results(self, output_folder, output_file="equity_with_price_plot.png"):
        """
        Plot equity curve with BTCUSD prices, trade signals, and SMA in one figure.
        Now using daily resampled equity data (more accurate).
        """
        import matplotlib.pyplot as plt
        from matplotlib.dates import YearLocator, DateFormatter

        data_to_plot = self.data.copy()
        required_columns = ['Close']
        if data_to_plot.empty or not all(col in data_to_plot.columns for col in required_columns):
            logger.warning("No data available to plot. Skipping plot.")
            return
        if data_to_plot[required_columns].isna().all().any():
            logger.warning("Required columns contain only NaN values. Skipping plot.")
            return

        # Calculate SMA
        sma_period = self.config["strategy"]["sma_long"]
        data_to_plot['SMA'] = data_to_plot['Close'].rolling(window=sma_period).mean()

        # Generate equity points (based on exit_time)
        equity_curve = [self.initial_capital]
        equity_times = [self.data.index[0]]
        for trade in self.trades:
            equity_curve.append(equity_curve[-1] + trade['profit'])
            equity_times.append(trade['exit_time'])
        equity_df = pd.DataFrame({'Equity': equity_curve}, index=pd.to_datetime(equity_times))
        equity_df = equity_df.sort_index()

        # Resample equity to daily frequency
        daily_equity = equity_df.resample("D").ffill()

        # Trade markers for price
        entry_times = [pd.to_datetime(t['entry_time']) for t in self.trades]
        exit_times = [pd.to_datetime(t['exit_time']) for t in self.trades]
        entry_prices = [self.data.loc[et]['Close'] for et in entry_times if et in self.data.index]
        exit_prices = [self.data.loc[et]['Close'] for et in exit_times if et in self.data.index]

        os.makedirs(output_folder, exist_ok=True)
        combined_file = os.path.join(output_folder, output_file)

        fig, ax = plt.subplots(figsize=(14, 8))
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        # Equity Curve
        ax.plot(daily_equity.index, daily_equity['Equity'], label='Daily Equity', color='#007ACC', linewidth=3, alpha=0.95)
        ax.set_title("BTCUSD, SMA, and Daily Equity with Signals", fontsize=18, fontweight='bold', color='#333333')
        ax.set_xlabel("Date", fontsize=14, color='#333333')
        ax.set_ylabel("Equity ($)", color='#007ACC', fontsize=14)
        ax.tick_params(axis='y', labelcolor='#007ACC', labelsize=12)
        ax.grid(True, linestyle='--', linewidth=0.5, alpha=0.6, color='#cccccc')

        # BTCUSD Price and SMA
        ax2 = ax.twinx()
        ax2.plot(data_to_plot.index, data_to_plot['Close'], label='BTCUSD Price', color='#7f7f7f', linewidth=1.5, alpha=0.9)
        ax2.plot(data_to_plot.index, data_to_plot['SMA'], label=f'SMA ({sma_period})', color='#FFA500', linewidth=2, linestyle='--', alpha=0.9)
        ax2.scatter(entry_times, entry_prices, marker='^', color='#2ECC71', label='Buy (Price)', s=100, edgecolor='black', alpha=1.0)
        ax2.scatter(exit_times, exit_prices, marker='v', color='#E74C3C', label='Sell (Price)', s=100, edgecolor='black', alpha=1.0)
        ax2.set_ylabel("BTCUSD Price ($)", color='#7f7f7f', fontsize=14)
        ax2.tick_params(axis='y', labelcolor='#7f7f7f', labelsize=12)

        # Legend
        lines_1, labels_1 = ax.get_legend_handles_labels()
        lines_2, labels_2 = ax2.get_legend_handles_labels()
        ax2.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper center', bbox_to_anchor=(0.5, -0.1), ncol=3, fontsize=12)

        ax.xaxis.set_major_locator(YearLocator())
        ax.xaxis.set_major_formatter(DateFormatter('%Y'))
        ax.tick_params(axis='x', labelsize=12)

        plt.tight_layout()
        plt.subplots_adjust(bottom=0.2)
        plt.savefig(combined_file, dpi=300)
        plt.close()
        logger.info(f"Daily equity with price and signals saved at: {combined_file}")