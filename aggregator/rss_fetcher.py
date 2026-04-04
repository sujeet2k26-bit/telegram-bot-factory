"""
aggregator/rss_fetcher.py
─────────────────────────
Fetches news articles from RSS feeds for a given bot.

What this file does:
  - Reads the list of trusted RSS sources from the bot's sources file
    (e.g. config/sources_ai.json or config/sources_bollywood.json).
  - Fetches each RSS feed using the 'feedparser' library.
  - Parses each article into a clean dictionary with a consistent structure.
  - Returns a list of articles ready to be checked for duplicates and scored.

What is an RSS feed?
  - RSS (Really Simple Syndication) is a standard format that news websites
    use to publish their latest articles in a machine-readable way.
  - Think of it like a live list of the latest articles from a website.
  - feedparser is a Python library that reads these feeds for us.

How to use this module:
  >>> from aggregator.rss_fetcher import fetch_articles_for_bot
  >>> bot_config = {"id": "ai_news", "sources_file": "config/sources_ai.json", ...}
  >>> articles = fetch_articles_for_bot(bot_config)
  >>> for article in articles:
  ...     print(article["title"], article["url"])
"""

import logging
import json
import feedparser
from datetime import datetime, timezone
from time import mktime

logger = logging.getLogger(__name__)


def load_sources(sources_file: str) -> list:
    """
    Loads the list of trusted RSS sources from a JSON config file.

    Args:
        sources_file (str): Path to the sources JSON file.
                            e.g. "config/sources_ai.json"

    Returns:
        list: A list of source dictionaries, each with keys:
              name, website, rss_url, category, credibility.
              Returns empty list if the file cannot be read.
    """
    try:
        with open(sources_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        sources = data.get("sources", [])
        logger.debug("Loaded %d sources from %s", len(sources), sources_file)
        return sources
    except FileNotFoundError:
        logger.error("Sources file not found: %s", sources_file)
        return []
    except json.JSONDecodeError as e:
        logger.error("Failed to parse sources file %s: %s", sources_file, str(e))
        return []


def parse_published_date(entry) -> datetime:
    """
    Extracts and converts the published date from an RSS feed entry.

    RSS feeds can store dates in several different formats.
    feedparser parses them into a 'time struct' (a tuple of numbers).
    This function converts that into a Python datetime object.

    Args:
        entry: A feedparser entry object (one article from the feed).

    Returns:
        datetime: The published date as a UTC datetime object.
                  Returns the current time if no date is found.
    """
    # feedparser stores parsed dates in 'published_parsed' or 'updated_parsed'
    time_struct = getattr(entry, "published_parsed", None) or \
                  getattr(entry, "updated_parsed", None)

    if time_struct:
        # mktime() converts a time struct to a Unix timestamp (seconds since 1970)
        # datetime.fromtimestamp() converts that to a datetime object
        return datetime.fromtimestamp(mktime(time_struct), tz=timezone.utc).replace(tzinfo=None)

    # If no date found, use current time as a fallback
    logger.debug("No published date found in entry, using current time.")
    return datetime.utcnow()


def fetch_single_feed(source: dict, bot_id: str) -> list:
    """
    Fetches all articles from a single RSS feed URL.

    Connects to the RSS feed URL, downloads the feed data,
    and parses each entry into a clean article dictionary.

    Args:
        source (dict): A source dictionary with keys: name, rss_url, category, credibility.
        bot_id (str):  The ID of the bot this fetch is for (e.g. "ai_news").

    Returns:
        list: A list of article dictionaries. Each dictionary has:
              - bot_id (str): Which bot this article is for
              - title (str): Article headline
              - url (str): Link to the full article
              - source_name (str): Name of the news source
              - summary (str): Short description or first paragraph
              - published_at (datetime): When the article was published
              Returns empty list if the feed cannot be fetched.
    """
    rss_url = source.get("rss_url", "")
    source_name = source.get("name", "Unknown")

    if not rss_url:
        logger.warning("Source '%s' has no rss_url — skipping.", source_name)
        return []

    logger.info("Fetching feed: %s (%s)", source_name, rss_url)

    try:
        # feedparser.parse() downloads and parses the RSS feed
        # It handles all the different RSS/Atom format variations automatically
        feed = feedparser.parse(rss_url)

        # Check if the feed returned any entries
        if not feed.entries:
            logger.warning("No entries found in feed: %s", source_name)
            return []

        articles = []
        for entry in feed.entries:
            # Extract the article URL — try 'link' first, then 'id'
            url = getattr(entry, "link", None) or getattr(entry, "id", None)
            if not url:
                logger.debug("Skipping entry with no URL in feed: %s", source_name)
                continue

            # Extract the title — clean up any extra whitespace
            title = getattr(entry, "title", "").strip()
            if not title:
                logger.debug("Skipping entry with no title in feed: %s", source_name)
                continue

            # Extract the summary/description — some feeds use 'summary', others use 'description'
            summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
            # Limit summary length to avoid storing huge amounts of text
            summary = summary[:1000] if summary else ""

            # Build the clean article dictionary
            article = {
                "bot_id": bot_id,
                "title": title,
                "url": url,
                "source_name": source_name,
                "summary": summary,
                "published_at": parse_published_date(entry),
            }
            articles.append(article)

        logger.info(
            "Fetched %d articles from %s",
            len(articles), source_name
        )
        return articles

    except Exception as e:
        # Catch all errors so one broken feed doesn't stop the others
        logger.error("Failed to fetch feed '%s' (%s): %s", source_name, rss_url, str(e))
        return []


def fetch_articles_for_bot(bot_config: dict) -> list:
    """
    Fetches all articles from all RSS sources configured for a bot.

    This is the main function called by the pipeline.
    It loops through every source in the bot's sources file,
    fetches each feed, and combines all articles into one list.

    Args:
        bot_config (dict): The bot's configuration dictionary from bots.json.
                           Must include 'id' and 'sources_file' keys.

    Returns:
        list: A combined list of all article dictionaries fetched
              from all sources for this bot.
              Returns empty list if no sources are configured or all feeds fail.

    Example:
        >>> bot = {"id": "ai_news", "sources_file": "config/sources_ai.json", ...}
        >>> articles = fetch_articles_for_bot(bot)
        >>> print(f"Fetched {len(articles)} articles")
    """
    bot_id = bot_config.get("id", "unknown")
    sources_file = bot_config.get("sources_file", "")
    bot_name = bot_config.get("name", bot_id)

    logger.info("Starting RSS fetch for bot: %s", bot_name)

    # Load the list of sources for this bot
    sources = load_sources(sources_file)
    if not sources:
        logger.warning("No sources found for bot '%s'. Skipping fetch.", bot_name)
        return []

    all_articles = []

    # Fetch each source one by one
    for source in sources:
        articles = fetch_single_feed(source, bot_id)
        all_articles.extend(articles)

    logger.info(
        "RSS fetch complete for bot '%s': %d total articles from %d sources.",
        bot_name, len(all_articles), len(sources)
    )
    return all_articles
