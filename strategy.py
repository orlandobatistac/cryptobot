# strategy.py

import pandas as pd
import json
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

logger.debug("Starting execution of strategy.py")

# Load strategy parameters from config.json
with open("config.json", "r") as f:
    config = json.load(f)
strategy_params = config["strategy"]

class Strategy:
    def __init__(self, config=None):
        """
        Initialize the strategy with an optional configuration dictionary.
        :param config: Dictionary with indicator parameters (optional).
        """
        # Default configuration (updated with optimized parameters)
        self.default_config = strategy_params

        # Use provided config if available, otherwise use default
        self.config = self.default_config.copy()
        if config is not None:
            self.config.update(config)

        # Validate all required keys are present
        required_keys = list(self.default_config.keys())
        missing_keys = [key for key in required_keys if key not in self.config]
        if missing_keys:
            raise KeyError(f"Missing required config keys: {missing_keys}")

        # Validate and convert config types only once
        for key, value in self.config.items():
            if key in ["use_supertrend", "use_adx_positive", "use_macd_positive", "time_based_stop_loss_percent"]:
                continue  # Skip validation for booleans and time_based_stop_loss_percent
            float_keys = [
                "stop_loss_atr_multiplier", "trailing_stop_percentage", "bollinger_std_dev",
                "supertrend_multiplier", "stop_loss_multiplier", "take_profit_multiplier",
                "resistance_margin", "support_margin"
            ]
            if key in float_keys:
                self.config[key] = float(value)
            else:
                self.config[key] = int(value)

        self.last_entry_time = None  # Track the last entry time to avoid same-candle exits
        self.position_open = False  # Track if a position is currently open
        self.highest_price = None  # Track the highest price since entry for trailing stop
        self.entry_price = None  # Track the entry price for stop-loss
        self.is_range_trading = False 

    @log_debug
    def calculate_indicators(self, data):
        """
        Calculate technical indicators and add them to the DataFrame.
        :param data: DataFrame with OHLCV data.
        """
        logger.debug("Starting indicator calculation. Data shape: %s", data.shape)
        try:
            # Add signal tracking columns
            data['entry_signal_generated'] = False
            data['exit_signal_generated'] = False

            # Check data length against max period
            min_periods = max(
                self.config['sma_long'], self.config['rsi_period'], self.config['macd_slow'],
                self.config['atr_period'], self.config['adx_period'], self.config['bollinger_period'],
                52  # Ichimoku Cloud max period
            )
            if len(data) < min_periods:
                logger.warning(f"Data too short for indicators. Required: {min_periods}, Available: {len(data)}")
                return

            # Validate required columns
            required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
            if data[required_columns].isnull().any().any():
                raise ValueError("Data contains NaN values in required columns.")

            # Calculate SMA
            data['sma_short'] = data['Close'].rolling(self.config['sma_short']).mean()
            data['sma_long'] = data['Close'].rolling(self.config['sma_long']).mean()

            # Calculate RSI
            delta = data['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(self.config['rsi_period']).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(self.config['rsi_period']).mean()
            rs = gain / loss
            data['rsi'] = 100 - (100 / (1 + rs))

            # Calculate MACD
            ema_fast = data['Close'].ewm(span=self.config['macd_fast'], adjust=False).mean()
            ema_slow = data['Close'].ewm(span=self.config['macd_slow'], adjust=False).mean()
            data['macd'] = ema_fast - ema_slow
            data['macd_signal'] = data['macd'].ewm(span=self.config['macd_signal'], adjust=False).mean()

            # Calculate ATR
            high_low = data['High'] - data['Low']
            high_close = (data['High'] - data['Close'].shift()).abs()
            low_close = (data['Low'] - data['Close'].shift()).abs()
            tr = high_low.combine(high_close, max).combine(low_close, max)
            data['atr'] = tr.rolling(self.config['atr_period']).mean()

            # Calculate ATR moving average for volatility filter
            data['atr_sma'] = data['atr'].rolling(self.config['atr_period']).mean()

            # Calculate ADX
            plus_dm = (data['High'] - data['High'].shift()).clip(lower=0)
            minus_dm = (data['Low'].shift() - data['Low']).clip(lower=0)
            plus_di = 100 * (plus_dm.ewm(span=self.config['adx_period'], adjust=False).mean() / data['atr'])
            minus_di = 100 * (minus_dm.ewm(span=self.config['adx_period'], adjust=False).mean() / data['atr'])
            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
            data['adx'] = dx.ewm(span=self.config['adx_period'], adjust=False).mean()

            # Calculate Volume SMA
            data['volume_sma'] = data['Volume'].rolling(self.config['volume_sma_period']).mean()

            # Calculate Bollinger Bands
            data['bollinger_mid'] = data['Close'].rolling(self.config['bollinger_period']).mean()
            data['bollinger_upper'] = data['bollinger_mid'] + (data['Close'].rolling(self.config['bollinger_period']).std() * self.config['bollinger_std_dev'])
            data['bollinger_lower'] = data['bollinger_mid'] - (data['Close'].rolling(self.config['bollinger_period']).std() * self.config['bollinger_std_dev'])

            # Calculate Supertrend (used only if use_supertrend is True)
            atr = data['atr']
            hl2 = (data['High'] + data['Low']) / 2
            data['supertrend_upper'] = hl2 + (self.config['supertrend_multiplier'] * atr)
            data['supertrend_lower'] = hl2 - (self.config['supertrend_multiplier'] * atr)
            data['supertrend'] = (data['Close'] > data['supertrend_lower']).astype(int)

            # Calculate Ichimoku Cloud
            high_9 = data['High'].rolling(window=9).max()
            low_9 = data['Low'].rolling(window=9).min()
            data['tenkan_sen'] = (high_9 + low_9) / 2
            high_26 = data['High'].rolling(window=26).max()
            low_26 = data['Low'].rolling(window=26).min()
            data['kijun_sen'] = (high_26 + low_26) / 2
            data['senkou_span_a'] = ((data['tenkan_sen'] + data['kijun_sen']) / 2).shift(26)
            high_52 = data['High'].rolling(window=52).max()
            low_52 = data['Low'].rolling(window=52).min()
            data['senkou_span_b'] = ((high_52 + low_52) / 2).shift(26)
            data['chikou_span'] = data['Close'].shift(-26)

            # Drop NaN values after all calculations
            data.dropna(inplace=True)
            if data.empty:
                logger.warning("All data dropped after indicator calculation due to NaN values.")
            logger.debug("Indicators calculated. Final data shape: %s", data.shape)
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            raise

    @log_debug
    def entry_signal(self, row, data):
        """
        Generate entry signal based on indicators.
        :param row: Current row of data (Series).
        :param data: Full DataFrame to access previous values.
        :return: True if entry signal is triggered, False otherwise.
        """
        try:
            if row.get('entry_signal_generated', False) or self.position_open:
                return False
            idx = row.name
            if idx not in data.index or data.index.get_loc(idx) < 1:
                return False
            prev_idx_1 = data.index[data.index.get_loc(idx) - 1]
            prev_sma_short_1 = data.loc[prev_idx_1, 'sma_short']
            prev_sma_long_1 = data.loc[prev_idx_1, 'sma_long']
            
            # Detect sideways market
            lateral_market = row['adx'] < self.config['lateral_adx_threshold']
            
            # Range trading conditions
            range_conditions = {
                "lateral_market": lateral_market,
                "buy_near_support": row['Close'] < row['bollinger_lower'] * self.config['support_margin'] * 1.02,  # More margin
                "volume_confirmation": row['Volume'] > 1.5 * row['volume_sma'],  # Stricter volume filter
                "rsi_not_oversold": row['rsi'] > 20  # Avoid extreme oversold
            }
            
            # Trend trading conditions
            trend_conditions = {
                "sma_crossover": row['sma_short'] > row['sma_long'] and prev_sma_short_1 > prev_sma_long_1,
                "macd_above_signal": row['macd'] > row['macd_signal'] - self.config['macd_threshold'],
                "rsi_below_threshold": row['rsi'] < self.config['rsi_threshold'],
                "volume_above_sma": row['Volume'] > 1.2 * row['volume_sma'],
                "supertrend_uptrend": not self.config['use_supertrend'] or row['supertrend'] == 1,
                "adx_trend": not self.config['use_adx_positive'] or row['adx'] > self.config['adx_threshold'],
                "macd_positive": not self.config['use_macd_positive'] or row['macd'] > 0,
                "volatility_filter": row['atr'] > row['atr_sma']
            }
            
            # Decide trading mode
            if lateral_market:
                # Only evaluate range trading conditions in sideways market
                signal = all(range_conditions.values())
                self.is_range_trading = signal
            else:
                # Only evaluate trend trading conditions in non-sideways markets
                trend_main_conditions = ["sma_crossover", "macd_above_signal", "rsi_below_threshold"]
                trend_secondary_conditions = ["volume_above_sma", "supertrend_uptrend", "adx_trend", "macd_positive", "volatility_filter"]
                trend_main_pass = all(trend_conditions[cond] for cond in trend_main_conditions)
                trend_secondary_pass = sum(trend_conditions[cond] for cond in trend_secondary_conditions) >= 3
                signal = trend_main_pass and trend_secondary_pass
                self.is_range_trading = False
            
            if signal:
                logger.info(f"Entry signal generated at {row.name} (Range Trading: {self.is_range_trading})")
                # row['entry_signal_generated'] = True  # Commented to avoid SettingWithCopyWarning. Does not affect main logic.
                self.last_entry_time = row.name
                self.position_open = True
                self.highest_price = row['Close']
                self.entry_price = row['Close']
            else:
                failed_conditions = [key for key, value in (trend_conditions | range_conditions).items() if not value]
                logger.debug(f"Entry signal failed at {row.name}. Failed conditions: {failed_conditions}")
            return signal
        except Exception as e:
            logger.error(f"Error in entry_signal: {e}")
            return False

    @log_debug
    def exit_signal(self, row, data):
        try:
            if row.get('exit_signal_generated', False) or not self.position_open or self.last_entry_time == row.name:
                return False
            self.highest_price = max(self.highest_price, row['Close'])
            trailing_stop = self.highest_price * (1 - self.config['trailing_stop_percentage'])
            stop_loss = self.entry_price - (self.config['stop_loss_atr_multiplier'] * row['atr'] * self.config['stop_loss_multiplier'])
            dynamic_stop_loss = self.entry_price - (self.config['stop_loss_atr_multiplier'] * row['atr'] * self.config['stop_loss_multiplier'])
            stop_loss = min(stop_loss, dynamic_stop_loss)
            take_profit = self.entry_price + (self.config['stop_loss_atr_multiplier'] * row['atr'] * self.config['take_profit_multiplier'])
            supertrend_exit = self.config['use_supertrend'] and row['supertrend'] == 0

            # Time-based stop-loss
            duration_ms = (row.name - self.last_entry_time).total_seconds() * 1000
            profit_percent = (row['Close'] - self.entry_price) / self.entry_price * 100
            time_based_stop = duration_ms < self.config['time_based_stop_days'] * 24 * 60 * 60 * 1000 and profit_percent < self.config['time_based_stop_loss_percent']

            # Range trading exit: sell near resistance
            sell_near_resistance = row['Close'] > row['bollinger_upper'] * self.config['resistance_margin']
            range_exit = self.is_range_trading and sell_near_resistance

            # Trend trading exit conditions
            trend_exit = (
                row['macd'] < row['macd_signal'] - self.config['macd_threshold'] or
                row['Close'] < trailing_stop or
                row['Close'] < stop_loss or
                row['Close'] > take_profit or
                supertrend_exit or
                time_based_stop
            )

            # Decide exit based on mode
            signal = range_exit if self.is_range_trading else trend_exit

            if signal:
                logger.info(f"Exit signal generated at {row.name} (Range Trading: {self.is_range_trading})")
                row['exit_signal_generated'] = True
                self.last_entry_time = None
                self.position_open = False
                self.highest_price = None
                self.entry_price = None
                self.is_range_trading = False

            return signal
        except Exception as e:
            logger.error(f"Error in exit_signal: {e}")
            return False

logger.debug("Finished execution of strategy.py")