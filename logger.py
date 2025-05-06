import logging

# Fuerza el nivel del root logger para silenciar INFO y DEBUG de cualquier módulo
logging.getLogger().setLevel(logging.WARNING)

# Logging system
def setup_logger():
    logger = logging.getLogger("cryptobot")
    # Remove all handlers to avoid duplicates and conflicts
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    logger.setLevel(logging.WARNING)
    handler = logging.FileHandler("debug.log", mode="a", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(module)s - %(message)s")
    handler.setFormatter(formatter)
    handler.setLevel(logging.WARNING)
    logger.addHandler(handler)
    return logger

logger = setup_logger()
