"""
main.py
───────
Entry point for the AI News Bot application.

What this file does:
  - This is the FIRST file that runs when you start the application.
  - It sets up logging, validates settings, loads bot configurations,
    and starts the scheduler that runs all fetch/publish jobs.

How to run:
  $ python main.py

What happens when you run it:
  1. Logging is initialised (you'll see log output in the terminal)
  2. Settings are validated (checks your .env file has required keys)
  3. Bot configs are loaded from config/bots.json
  4. The scheduler starts and registers a job for each active bot
  5. The app runs continuously until you press Ctrl+C
"""

import logging
import json
import sys

# Set up logging FIRST — before importing anything else.
# This ensures all log messages from imports are captured too.
from utils.logger import setup_logging
from config.settings import settings


def load_bots(config_path: str) -> list:
    """
    Loads the list of bot configurations from bots.json.

    Reads the master bot registry and returns only the bots
    that are marked as active (active: true).

    Args:
        config_path (str): Path to the bots.json file.

    Returns:
        list: A list of bot config dictionaries for active bots only.
              Returns empty list if the file cannot be read.
    """
    logger = logging.getLogger(__name__)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        all_bots = data.get("bots", [])

        # Filter to only active bots
        active_bots = [bot for bot in all_bots if bot.get("active", False)]

        logger.info(
            "Loaded %d active bot(s) from %s: %s",
            len(active_bots),
            config_path,
            [bot["name"] for bot in active_bots],
        )
        return active_bots

    except FileNotFoundError:
        logger.error("Bot config file not found: %s", config_path)
        return []
    except json.JSONDecodeError as e:
        logger.error("Failed to parse bot config file %s: %s", config_path, str(e))
        return []


def main():
    """
    Main function — starts the entire application.

    This function is called when you run `python main.py`.
    It initialises all components and keeps the app running.
    """

    # ── Step 1: Set up logging ─────────────────────────────────────────────
    setup_logging(log_level=settings.LOG_LEVEL)
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("AI News Bot — Starting up")
    logger.info("=" * 60)

    # ── Step 2: Validate settings ──────────────────────────────────────────
    # Make sure all required API keys and config values are present.
    logger.info("Validating settings...")
    if not settings.validate():
        logger.critical(
            "Required settings are missing. "
            "Please check your .env file and try again."
        )
        sys.exit(1)  # Exit with error code 1 — means something went wrong

    # ── Step 3: Load active bots ───────────────────────────────────────────
    logger.info("Loading bot configurations from %s...", settings.BOTS_CONFIG_PATH)
    active_bots = load_bots(settings.BOTS_CONFIG_PATH)

    if not active_bots:
        logger.critical(
            "No active bots found in %s. "
            "Set 'active': true for at least one bot.",
            settings.BOTS_CONFIG_PATH,
        )
        sys.exit(1)

    # ── Step 3: Initialise the database ───────────────────────────────────
    # Creates the database file and tables if they don't exist yet.
    logger.info("Initialising database...")
    from db.database import init_db, check_db_health
    init_db()
    if not check_db_health():
        logger.critical("Database health check failed. Exiting.")
        sys.exit(1)

    # ── Step 4: Start the scheduler ────────────────────────────────────────
    # The scheduler registers all pipeline jobs for each active bot and starts
    # the Telegram review bot in a background thread.
    logger.info("Starting scheduler and review bot...")
    from scheduler.jobs import start_scheduler
    scheduler = start_scheduler(active_bots)

    # ── Step 5: Keep the app running ───────────────────────────────────────
    # The scheduler and review bot both run in background threads.
    # This loop keeps the main process alive so those threads keep running.
    # Press Ctrl+C to stop the application cleanly.
    logger.info("Application started. Press Ctrl+C to stop.")
    try:
        import time
        while True:
            time.sleep(60)  # Sleep, wake up every minute (just to stay alive)
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user (Ctrl+C). Stopping...")
        scheduler.shutdown(wait=False)  # Stop the scheduler cleanly
        logger.info("AI News Bot stopped.")


# This block ensures main() only runs when you execute this file directly.
# It does NOT run if another file imports main.py.
if __name__ == "__main__":
    main()
