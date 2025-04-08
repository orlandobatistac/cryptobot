# backtest.py

import pandas as pd
import numpy as np
import mplfinance as mpf
import os
from datetime import datetime
from logger import logger
from functools import wraps

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

    @log_debug
    def run(self):
        """
        Execute the backtest by iterating through the data.
        """
        logger.info("Starting backtest. Initial capital: %s", self.initial_capital)
        if self.data.empty:
            logger.error("Data is empty. Cannot run backtest.")
            raise ValueError("Data is empty. Cannot run backtest.")

        position = None
        for i, row in self.data.iterrows():
            if not self.from_optimize:  # Log only if not from optimize
                logger.debug("Processing row at index: %s", row.name)
            try:
                # Check for entry signal
                if position is None:
                    entry_signal = self.strategy.entry_signal(row, self.data)
                    if entry_signal:
                        logger.info("Entry signal detected at %s. Entry price: %s", row.name, row['Close'])
                        self.trade_id += 1
                        # Calculate shares based on a fraction of the current capital
                        investment_amount = self.capital * self.investment_fraction
                        shares = investment_amount / row['Close']
                        position = {
                            'trade_id': self.trade_id,
                            'entry_price': row['Close'],
                            'entry_time': row.name,
                            'shares': shares
                        }
                        continue  # Skip exit signal processing in the same candle

                # Check for exit signal
                if position:
                    exit_signal = self.strategy.exit_signal(row, self.data)
                    if exit_signal:
                        logger.info("Exit signal detected at %s. Exit price: %s", row.name, row['Close'])
                        position['exit_price'] = row['Close']
                        position['exit_time'] = row.name
                        profit = (position['exit_price'] - position['entry_price']) * position['shares']
                        trade_fee = (position['entry_price'] + position['exit_price']) * position['shares'] * self.trade_fee
                        profit -= trade_fee
                        position['profit'] = profit
                        self.capital += profit  # Reinvest the profit (or loss) into the capital
                        self.final_capital = self.capital
                        self.trades.append(position)
                        logger.info("Trade closed. Profit: %s", position['profit'])
                        position = None
                        self.strategy.position_open = False  # Reset position state
                        continue

                if position:
                    logger.debug("Checking stop-loss and take-profit for position at %s", row.name)
                    # Avoid same-candle stop-loss/take-profit
                    if position['entry_time'] != row.name:
                        # Stop-loss (1.5 * ATR, handled in strategy.exit_signal)
                        # Take-profit (5 * ATR, handled in strategy.exit_signal)
                        pass

            except Exception as e:
                logger.error(f"Error processing row at {row.name}: {e}")
                raise

        # Close any open position at the end
        if position:
            logger.info("Closing remaining position at %s with price %s", self.data.index[-1], self.data['Close'].iloc[-1])
            position['exit_price'] = self.data['Close'].iloc[-1]
            position['exit_time'] = self.data.index[-1]
            profit = (position['exit_price'] - position['entry_price']) * position['shares']
            trade_fee = (position['entry_price'] + position['exit_price']) * position['shares'] * self.trade_fee
            profit -= trade_fee
            position['profit'] = profit
            self.capital += profit
            self.final_capital = self.capital
            self.trades.append(position)
            self.strategy.position_open = False  # Reset position state

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
            max_drawdown = min(0, min(np.array(equity_curve) - np.maximum.accumulate(equity_curve)))

            # Buy and hold performance (from first trade open to last trade close)
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

            return {
                "initial_capital": float(self.initial_capital),
                "final_capital": float(self.final_capital),
                "total_profit": float(total_profit),
                "pl_percent": round(pl_percentage, 2),
                "number_of_trades": num_trades,
                "win_rate": round(win_rate * 100, 2),
                "total_fees": round(total_fees, 2),
                "max_drawdown": round(max_drawdown, 2),
                "buy_and_hold_final_capital": float(buy_and_hold_final_capital),
                "buy_and_hold_profit": float(buy_and_hold_profit),
                "buy_and_hold_pl_percent": round(buy_and_hold_pl_percentage, 2)
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
    def plot_results(self, output_folder, output_file="plot.png"):
        """
        Plot candlestick chart with entry/exit points.
        :param output_folder: Folder to save the plot.
        :param output_file: Filename for the plot.
        """
        # Limit data to last 500 points for better visualization
        data_to_plot = self.data.tail(500).copy()
        
        # Check if data_to_plot is empty or lacks required columns
        required_columns = ['Open', 'High', 'Low', 'Close']
        if data_to_plot.empty or not all(col in data_to_plot.columns for col in required_columns):
            logger.warning("No data available to plot in the last 500 points. Skipping plot.")
            return

        # Check if required columns have valid data (not all NaN)
        if data_to_plot[required_columns].isna().all().any():
            logger.warning("Required columns (Open, High, Low, Close) contain only NaN values in the last 500 points. Skipping plot.")
            return

        # Recalculate SMA indicators for data_to_plot to ensure they exist
        data_to_plot['SMA Short'] = data_to_plot['Close'].rolling(self.strategy.config['sma_short']).mean()
        data_to_plot['SMA Long'] = data_to_plot['Close'].rolling(self.strategy.config['sma_long']).mean()

        # Check if SMA columns have valid data
        if data_to_plot['SMA Short'].isna().all() or data_to_plot['SMA Long'].isna().all():
            logger.warning("SMA indicators could not be calculated for the last 500 points (all NaN). Skipping plot.")
            return

        # Prepare entry and exit prices for plotting
        entry_prices = [np.nan] * len(self.data)
        exit_prices = [np.nan] * len(self.data)
        for trade in self.trades:
            if trade['entry_time'] in self.data.index:
                entry_prices[self.data.index.get_loc(trade['entry_time'])] = trade['entry_price']
            if trade['exit_time'] in self.data.index:
                exit_prices[self.data.index.get_loc(trade['exit_time'])] = trade['exit_price']

        entry_prices = entry_prices[-len(data_to_plot):]
        exit_prices = exit_prices[-len(data_to_plot):]

        # Check if entry_prices and exit_prices have valid data
        if np.isnan(entry_prices).all() and np.isnan(exit_prices).all():
            logger.warning("No trades in the last 500 points to plot. Skipping plot.")
            return

        add_plot = [
            mpf.make_addplot(entry_prices, type='scatter', markersize=100, marker='^', color='green', label='Entry'),
            mpf.make_addplot(exit_prices, type='scatter', markersize=100, marker='v', color='red', label='Exit')
        ]

        os.makedirs(output_folder, exist_ok=True)
        mpf.plot(
            data_to_plot,
            type='candle',
            style='charles',
            volume=True,
            addplot=[
                mpf.make_addplot(data_to_plot['SMA Short'], color='blue', label='SMA Short'),
                mpf.make_addplot(data_to_plot['SMA Long'], color='orange', label='SMA Long'),
                *add_plot
            ],
            title="Backtest Results",
            ylabel="Price",
            ylabel_lower="Volume",
            savefig=os.path.join(output_folder, output_file)
        )
        logger.info(f"Plot saved to: {os.path.join(output_folder, output_file)}")