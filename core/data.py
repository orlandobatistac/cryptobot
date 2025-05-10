import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import pandas as pd
from utils.logger import logger
from functools import wraps
import os

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

class DataHandler:
    def __init__(self, file_path, start_date=None, end_date=None, interval=None):
        """
        Initialize the DataHandler with optional date range and interval.
        :param file_path: Path to the data file.
        :param start_date: Start date for filtering (e.g., '2023-01-01').
        :param end_date: End date for filtering (e.g., '2023-12-31').
        :param interval: Resampling interval (e.g., '4H', '1D').
        """
        self.file_path = file_path
        self.start_date = start_date
        self.end_date = end_date
        self.interval = interval

    @log_debug
    def load_data(self):
        """
        Load historical data from a file, filter by date range, and resample if needed.
        """
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"The data file '{self.file_path}' does not exist.")

        if self.file_path.endswith('.csv'):
            data = pd.read_csv(self.file_path, parse_dates=['Timestamp'])
        elif self.file_path.endswith('.parquet'):
            data = pd.read_parquet(self.file_path)
            # Ensure Timestamp is parsed as datetime if it's a column or index
            if 'Timestamp' in data.columns:
                data['Timestamp'] = pd.to_datetime(data['Timestamp'])
            elif data.index.name == 'Timestamp':
                data.index = pd.to_datetime(data.index)
        else:
            raise ValueError("Unsupported file format. Use .csv or .parquet.")

        # Check if 'Timestamp' is either a column or the index
        if 'Timestamp' not in data.columns and data.index.name != 'Timestamp':
            raise ValueError(f"The data file '{self.file_path}' must contain a 'Timestamp' column or index. "
                            f"Columns found: {list(data.columns)}, Index: {data.index.name}")

        # If 'Timestamp' is a column, set it as index
        if 'Timestamp' in data.columns:
            data.set_index('Timestamp', inplace=True)

        # Log the date range after loading
        logger.debug(f"Loaded data date range: {data.index[0]} to {data.index[-1]}")
        logger.debug(f"Loaded data index type: {type(data.index)}")

        # Validate required columns
        required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        missing_columns = [col for col in required_columns if col not in data.columns]
        if missing_columns:
            raise ValueError(f"The data file '{self.file_path}' is missing required columns: {missing_columns}. "
                            f"Columns found: {list(data.columns)}")

        # Filter by date range
        if self.start_date and self.end_date:
            data = data.sort_index()  # Ensure the index is sorted
            data = data.loc[self.start_date:self.end_date]
            logger.debug(f"Filtered data date range: {data.index[0]} to {data.index[-1]}")

        # Ensure the filtered data is not empty
        if data.empty:
            raise ValueError(f"No data available after filtering by date range: {self.start_date} to {self.end_date}")

        # Resample data to the specified interval
        if self.interval:
            interval = self.interval.lower()
            data = data.resample(interval).agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()
            logger.debug(f"Resampled data date range: {data.index[0]} to {data.index[-1]}")

        # Ensure the resampled data is not empty
        if data.empty:
            raise ValueError(f"No data available after resampling to interval: {self.interval}")

        return data