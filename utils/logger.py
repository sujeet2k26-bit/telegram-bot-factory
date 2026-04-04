"""
utils/logger.py
───────────────
Central logging configuration for the entire AI News Bot project.

What this file does:
  - Sets up ONE logging system that all other modules in the project use.
  - Writes logs to three places simultaneously:
      1. The terminal (so you can watch what's happening in real time)
      2. logs/app.log (general application logs)
      3. logs/guardrail_violations.log (content that was blocked by safety rules)
      4. logs/publish_history.log (every post that was published or rejected)

How to use this in any other module:
  >>> import logging
  >>> logger = logging.getLogger(__name__)
  >>> logger.info("This is an info message")
  >>> logger.error("Something went wrong: %s", error_message)

Log levels (from least to most severe):
  DEBUG   → Very detailed info, useful when you're debugging a problem
  INFO    → Normal operations (e.g. "Fetched 10 articles from TechCrunch")
  WARNING → Something unexpected happened but the app keeps running
  ERROR   → Something failed (e.g. API call failed)
  CRITICAL→ A serious failure — the app may not be able to continue
"""

import logging
import logging.handlers
import os


def setup_logging(log_level: str = "INFO") -> None:
    """
    Sets up the logging system for the entire application.

    Call this ONCE at the start of main.py before anything else runs.
    After calling this, every module can use logging.getLogger(__name__)
    and logs will automatically go to the right files.

    Args:
        log_level (str): The minimum level of messages to log.
                         Options: "DEBUG", "INFO", "WARNING", "ERROR"
                         Default is "INFO" — shows normal operations.
                         Use "DEBUG" during development for more detail.

    Returns:
        None
    """

    # ── Step 1: Make sure the logs/ folder exists ──────────────────────────
    # We create it here so the app works even on a fresh install.
    os.makedirs("logs", exist_ok=True)

    # ── Step 2: Define the log message format ─────────────────────────────
    # This is what each log line looks like:
    # 2024-04-03 07:15:23 | INFO     | aggregator.rss_fetcher | Fetched 5 articles
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

    # ── Step 3: Convert the log level string to a logging constant ─────────
    # e.g. "INFO" → logging.INFO (which is the number 20 internally)
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # ── Step 4: Get the root logger ────────────────────────────────────────
    # The root logger is the parent of all loggers in the app.
    # Setting its level here controls what gets logged everywhere.
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # ── Step 5: Terminal handler ───────────────────────────────────────────
    # Prints log messages to the terminal so you can watch in real time.
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(numeric_level)
    root_logger.addHandler(console_handler)

    # ── Step 6: General app log file (logs/app.log) ────────────────────────
    # RotatingFileHandler automatically starts a new file when the log
    # gets too big (max 5MB), and keeps the last 3 old log files.
    # This prevents your disk from filling up with log data.
    app_handler = logging.handlers.RotatingFileHandler(
        filename="logs/app.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    app_handler.setFormatter(formatter)
    app_handler.setLevel(numeric_level)
    root_logger.addHandler(app_handler)

    # ── Step 7: Guardrail violations log (logs/guardrail_violations.log) ───
    # Only logs WARNING level and above from the guardrails module.
    # This gives you a clean, separate record of all blocked content.
    guardrail_handler = logging.handlers.RotatingFileHandler(
        filename="logs/guardrail_violations.log",
        maxBytes=2 * 1024 * 1024,  # 2 MB
        backupCount=3,
        encoding="utf-8",
    )
    guardrail_handler.setFormatter(formatter)
    guardrail_handler.setLevel(logging.WARNING)
    # Only capture logs from the "guardrails" package
    guardrail_logger = logging.getLogger("guardrails")
    guardrail_logger.addHandler(guardrail_handler)

    # ── Step 8: Publish history log (logs/publish_history.log) ────────────
    # Keeps a clean record of every post that was published or rejected.
    publish_handler = logging.handlers.RotatingFileHandler(
        filename="logs/publish_history.log",
        maxBytes=2 * 1024 * 1024,  # 2 MB
        backupCount=5,
        encoding="utf-8",
    )
    publish_handler.setFormatter(formatter)
    publish_handler.setLevel(logging.INFO)
    # Only capture logs from the "publisher" package
    publish_logger = logging.getLogger("publisher")
    publish_logger.addHandler(publish_handler)

    # ── Step 9: Confirm logging is ready ───────────────────────────────────
    startup_logger = logging.getLogger(__name__)
    startup_logger.info("Logging initialised. Level: %s", log_level)
    startup_logger.info("Log files: logs/app.log | logs/guardrail_violations.log | logs/publish_history.log")
