"""
guardrails/keyword_blocklist.py
────────────────────────────────
Loads and provides the blocked keyword lists from config/keywords.json.

What this file does:
  - Reads the blocked keyword categories from keywords.json.
  - Provides a function to check if any blocked keyword appears
    in a given piece of text.
  - Returns which category was matched, so the filter knows
    WHY the content was blocked (not just that it was blocked).

Categories of blocked keywords (defined in keywords.json):
  - hate_speech      → communal, religious, caste-based content
  - sexual_content   → explicit or adult content
  - violence         → graphic violence descriptions
  - political        → election propaganda, political targeting
  - clickbait_patterns → sensationalist headlines with no substance

How this is used:
  content_filter.py calls check_for_blocked_keywords() on every
  article title + summary before it enters the pipeline.
"""

import json
import logging

logger = logging.getLogger(__name__)

# Path to the keywords config file
KEYWORDS_FILE = "config/keywords.json"

# This will hold all the blocked keyword data after it's loaded
_blocked_keywords: dict = {}


def load_blocked_keywords() -> dict:
    """
    Loads the blocked keyword lists from config/keywords.json.

    This function is called once when the module is first imported.
    The result is stored in _blocked_keywords so we don't re-read
    the file on every check.

    Returns:
        dict: A dictionary where each key is a category name (e.g. "hate_speech")
              and each value is a list of blocked keyword strings.
              Returns empty dict if the file cannot be read.
    """
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_blocked = data.get("blocked_keywords", {})

        # Skip any keys starting with "_" — these are JSON comments, not categories
        # e.g. "_comment" is used in the JSON file to add human-readable notes
        blocked = {k: v for k, v in raw_blocked.items() if not k.startswith("_")}

        # Count total blocked keywords across all categories
        total = sum(len(kws) for kws in blocked.values())
        logger.debug(
            "Loaded %d blocked keywords across %d categories from %s",
            total, len(blocked), KEYWORDS_FILE
        )
        return blocked

    except FileNotFoundError:
        logger.error("Keywords file not found: %s", KEYWORDS_FILE)
        return {}
    except json.JSONDecodeError as e:
        logger.error("Failed to parse keywords file %s: %s", KEYWORDS_FILE, str(e))
        return {}


def check_for_blocked_keywords(text: str) -> tuple:
    """
    Scans a piece of text for any blocked keywords.

    Checks the text against every keyword in every blocked category.
    The check is case-insensitive, so "SHOCKING" matches "shocking".

    Args:
        text (str): The text to scan. Usually the article title + summary
                    combined, or the generated post content.

    Returns:
        tuple: A two-element tuple:
               - (False, None) if no blocked keywords found (text is clean)
               - (True, "category_name") if a blocked keyword was found,
                 where "category_name" is e.g. "hate_speech" or "violence"

    Example:
        >>> is_blocked, category = check_for_blocked_keywords("Some article text")
        >>> if is_blocked:
        ...     print(f"Blocked: {category}")
    """
    global _blocked_keywords

    # Load keywords on first use (lazy loading)
    if not _blocked_keywords:
        _blocked_keywords = load_blocked_keywords()

    if not text:
        return False, None

    # Convert text to lowercase once for efficient case-insensitive matching
    text_lower = text.lower()

    # Check each category's keywords
    for category, keywords in _blocked_keywords.items():
        for keyword in keywords:
            if keyword.lower() in text_lower:
                logger.debug(
                    "Blocked keyword found: '%s' in category '%s'",
                    keyword, category
                )
                return True, category

    return False, None


def get_trending_keywords(bot_id: str) -> list:
    """
    Returns the trending keywords for a given bot's domain.

    These keywords are used by the virality scoring engine to boost
    the score of articles that mention important trending topics.

    Args:
        bot_id (str): The bot ID, e.g. "ai_news" or "bollywood".
                      Maps to the domain key in keywords.json.

    Returns:
        list: A list of trending keyword strings for this bot's domain.
              Returns empty list if no keywords found for this bot.
    """
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        trending = data.get("trending_keywords", {})

        # Map bot_id to domain key in keywords.json
        domain_map = {
            "ai_news": "ai_technology",
            "bollywood": "bollywood",
            "astrology": "astrology",
        }
        domain = domain_map.get(bot_id, bot_id)
        keywords = trending.get(domain, [])

        logger.debug(
            "Loaded %d trending keywords for bot '%s'", len(keywords), bot_id
        )
        return keywords

    except Exception as e:
        logger.error("Failed to load trending keywords: %s", str(e))
        return []
