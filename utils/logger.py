import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

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

logger = setup_logger()
