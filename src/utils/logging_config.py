"""Logging configuration for WiZ Music Sync."""

import logging
import sys
from typing import Optional


def setup_logging(verbose: bool = False, log_file: Optional[str] = None) -> logging.Logger:
    """Configure structured logging for the application.
    
    Args:
        verbose: If True, set log level to DEBUG. Otherwise INFO.
        log_file: Optional path to a file to write logs to.
        
    Returns:
        The configured root logger for the application.
    """
    level = logging.DEBUG if verbose else logging.INFO
    
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Configure root application logger
    app_logger = logging.getLogger("wiz_music_sync")
    app_logger.setLevel(level)
    app_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    app_logger.addHandler(console_handler)
    
    # Optional file handler
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        app_logger.addHandler(file_handler)
        
    # Tone down third-party loggers unless in verbose debug mode
    if not verbose:
        logging.getLogger("pywizlight").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)
    else:
        logging.getLogger("pywizlight").setLevel(logging.DEBUG)
        
    return app_logger
