"""
config/settings.py
──────────────────
Global application settings for the AI News Bot.

What this file does:
  - Loads all environment variables from your .env file.
  - Provides a single place to change app-wide settings like
    virality thresholds, retry times, and scheduling intervals.

Why use a settings file?
  - Instead of hardcoding numbers like "60" or "6" all over the code,
    we define them here with clear names. This makes the code easier
    to read and easy to tweak without hunting through every file.

How to use in other modules:
  >>> from config.settings import settings
  >>> print(settings.VIRALITY_THRESHOLD)   # 60
  >>> print(settings.ANTHROPIC_API_KEY)    # your key from .env
"""

import os
import logging
from dotenv import load_dotenv

# Load the .env file so all os.getenv() calls below work correctly.
# This must happen before any os.getenv() call.
load_dotenv()

logger = logging.getLogger(__name__)


class Settings:
    """
    Holds all configuration values for the application.

    Values come from two places:
      1. Environment variables (from your .env file) — for secrets like API keys
      2. Hardcoded defaults below — for tunable settings like thresholds

    To change a setting, either update your .env file (for secrets)
    or change the default value here (for app behaviour).
    """

    # ── Euri AI (API Gateway) ──────────────────────────────────────────────
    # Euri is an OpenAI-compatible API gateway that provides access to 200+ AI models.
    # We use it to call Google Gemini models for both text and image generation.
    # Get your free key at: https://euron.one
    EURI_API_KEY: str = os.getenv("EURI_API_KEY", "")

    # Euri API base URL — this is the endpoint all API calls go through.
    EURI_BASE_URL: str = "https://api.euron.one/api/v1/euri"

    # ── Text Generation Model ──────────────────────────────────────────────
    # gemini-2.5-pro: Google's most capable text model.
    # Used to write AI news posts (English) and Bollywood posts (Hindi/Hinglish).
    TEXT_MODEL: str = "gemini-2.5-pro"

    # Maximum number of tokens the model can use in one response.
    # gemini-2.5-pro is a "thinking" model — it uses ~400 tokens internally
    # for reasoning before producing output. Set this to 4096 minimum,
    # otherwise the model returns empty content.
    TEXT_MAX_TOKENS: int = 4096

    # ── Image Generation Model ─────────────────────────────────────────────
    # gemini-2-pro-image-preview: Generates cover images for Telegram posts.
    # One image is generated per published post as a visual thumbnail.
    IMAGE_MODEL: str = "gemini-3-pro-image-preview"

    # Image output size (width x height in pixels).
    IMAGE_SIZE: str = "1024x1024"

    # ── Telegram ───────────────────────────────────────────────────────────
    TELEGRAM_AI_BOT_TOKEN: str = os.getenv("TELEGRAM_AI_BOT_TOKEN", "")
    TELEGRAM_AI_CHANNEL_ID: str = os.getenv("TELEGRAM_AI_CHANNEL_ID", "")

    TELEGRAM_BOLLYWOOD_BOT_TOKEN: str = os.getenv("TELEGRAM_BOLLYWOOD_BOT_TOKEN", "")
    TELEGRAM_BOLLYWOOD_CHANNEL_ID: str = os.getenv("TELEGRAM_BOLLYWOOD_CHANNEL_ID", "")

    TELEGRAM_ASTROLOGY_BOT_TOKEN: str = os.getenv("TELEGRAM_ASTROLOGY_BOT_TOKEN", "")
    TELEGRAM_ASTROLOGY_CHANNEL_ID: str = os.getenv("TELEGRAM_ASTROLOGY_CHANNEL_ID", "")

    # Your personal Telegram chat ID — where review requests are sent.
    TELEGRAM_REVIEWER_CHAT_ID: str = os.getenv("TELEGRAM_REVIEWER_CHAT_ID", "")

    # ── News API ───────────────────────────────────────────────────────────
    NEWS_API_KEY: str = os.getenv("NEWS_API_KEY", "")

    # ── Reddit API (Phase 2) ───────────────────────────────────────────────
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "AINewsBot/1.0")

    # ── Virality Scoring Thresholds ────────────────────────────────────────
    # An article needs this score (out of 100) to be considered "viral".
    # If no article reaches this score, we fall back to most-viewed.
    VIRALITY_THRESHOLD: int = 60

    # How many hours back to look for articles.
    # Articles older than this are ignored completely.
    MAX_ARTICLE_AGE_HOURS: int = 48

    # How many days to remember an article for deduplication.
    # If we've seen the same article within this window, we skip it.
    DEDUP_WINDOW_DAYS: int = 7

    # ── Scheduling ─────────────────────────────────────────────────────────
    # How often (in hours) to fetch new articles from RSS feeds.
    FETCH_INTERVAL_HOURS: int = 6

    # How many minutes after the review request is sent before we
    # retry if the reviewer hasn't responded.
    REVIEW_RETRY_MINUTES: int = 60

    # ── Logging ────────────────────────────────────────────────────────────
    # Log level for the application.
    # Use "DEBUG" when developing to see every detail.
    # Use "INFO" in normal operation.
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ── Database ───────────────────────────────────────────────────────────
    # SQLite database file path.
    # SQLite stores everything in a single file — simple and great for local use.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///db/ainews.db")

    # ── Bot Config File ────────────────────────────────────────────────────
    # Path to the master bot registry JSON file.
    BOTS_CONFIG_PATH: str = "config/bots.json"

    def validate(self) -> bool:
        """
        Checks that all required settings are present before the app starts.

        This prevents confusing errors later — for example, if you forget
        to set your Telegram token, the app will tell you clearly instead
        of crashing with a cryptic error deep inside the code.

        Returns:
            bool: True if all required settings are present, False otherwise.
        """
        required = {
            "EURI_API_KEY": self.EURI_API_KEY,
            "TELEGRAM_REVIEWER_CHAT_ID": self.TELEGRAM_REVIEWER_CHAT_ID,
        }

        all_valid = True
        for name, value in required.items():
            if not value:
                logger.error("Missing required setting: %s — please add it to your .env file", name)
                all_valid = False

        if all_valid:
            logger.info("All required settings are present.")

        return all_valid


# Create a single shared instance.
# Every module imports this one object:  from config.settings import settings
settings = Settings()
