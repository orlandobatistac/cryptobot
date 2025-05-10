import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from logging.handlers import RotatingFileHandler

# Fuerza el nivel del root logger para silenciar INFO y DEBUG de cualquier módulo
logging.getLogger().setLevel(logging.WARNING)

# Logging system
def setup_logger():
    # Ensure logs directory exists
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    logger = logging.getLogger("cryptobot")
    # Remove all handlers to avoid duplicates and conflicts
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    logger.setLevel(logging.WARNING)
    
    # Use full path to debug.log in logs directory
    log_file_path = os.path.join(logs_dir, "debug.log")
    handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(module)s - %(message)s")
    handler.setFormatter(formatter)
    handler.setLevel(logging.WARNING)
    logger.addHandler(handler)
    return logger

def get_live_trading_logger():
    """Devuelve un logger dedicado para live_trading con rotación de archivos y formato personalizado."""
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file_path = os.path.join(logs_dir, "live_trading.log")
    logger = logging.getLogger("live_trading")
    # Evita handlers duplicados
    if not logger.handlers:
        handler = RotatingFileHandler(log_file_path, maxBytes=2*1024*1024, backupCount=5, encoding="utf-8")
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(module)s | %(message)s | %(funcName)s | %(lineno)d"
        )
        handler.setFormatter(formatter)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger

logger = setup_logger()
