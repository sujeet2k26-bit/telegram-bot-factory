"""
guardrails/source_whitelist.py
────────────────────────────────
Validates that articles come from trusted, whitelisted sources.

What this file does:
  - Maintains a list of all trusted source names across all bots.
  - Checks if an article's source is in the trusted list.
  - Articles from non-whitelisted sources are flagged for human review
    (not auto-blocked — they may still be valid but need verification).

Why source validation matters:
  - Our RSS fetcher only fetches from whitelisted sources, so in normal
    operation this check won't block anything.
  - But if someone manually adds an article, or a source URL redirects
    to a different domain, this catches it.
  - It's a safety net, not the main line of defence.
"""

import json
import logging

logger = logging.getLogger(__name__)

# Paths to all source config files
SOURCE_FILES = [
    "config/sources_ai.json",
    "config/sources_bollywood.json",
]

# Cache of trusted source names (loaded once)
_trusted_sources: set = set()


def load_trusted_sources() -> set:
    """
    Loads all trusted source names from all source config files.

    Reads every sources_*.json file and collects the 'name' field
    from each source entry into a set for fast lookup.

    Returns:
        set: A set of trusted source name strings.
             e.g. {"TechCrunch AI", "The Verge", "Bollywood Hungama", ...}
    """
    trusted = set()

    for source_file in SOURCE_FILES:
        try:
            with open(source_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for source in data.get("sources", []):
                name = source.get("name", "").strip()
                if name:
                    trusted.add(name)

        except FileNotFoundError:
            logger.warning("Source file not found: %s — skipping.", source_file)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse source file %s: %s", source_file, str(e))

    logger.debug("Loaded %d trusted source names.", len(trusted))
    return trusted


def is_trusted_source(source_name: str) -> bool:
    """
    Checks if a source name is in the trusted sources list.

    Args:
        source_name (str): The name of the news source to check.
                           e.g. "TechCrunch AI" or "NDTV Entertainment"

    Returns:
        bool: True if the source is trusted, False if it is not
              in our whitelisted sources list.
    """
    global _trusted_sources

    # Load on first use
    if not _trusted_sources:
        _trusted_sources = load_trusted_sources()

    is_trusted = source_name in _trusted_sources

    if not is_trusted:
        logger.warning(
            "Article from non-whitelisted source: '%s' — flagging for review.",
            source_name
        )

    return is_trusted
