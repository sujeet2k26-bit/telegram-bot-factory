"""
aggregator/dedup.py
───────────────────
Filters out duplicate and stale articles before they enter the pipeline.

What this file does:
  - Checks each newly fetched article against the database.
  - Skips articles that were already fetched before (same URL).
  - Skips articles that are too old (older than MAX_ARTICLE_AGE_HOURS).
  - Saves new, unique articles to the database.
  - Returns only the fresh, unique articles for further processing.

Why deduplication matters:
  - RSS feeds keep old articles for days or weeks.
  - Every time we fetch a feed, we'd see the same articles again.
  - Without deduplication, we'd generate and publish the same post twice!

How URL-based deduplication works:
  - Every article has a unique URL.
  - Before saving an article, we check: "Is this URL already in our DB?"
  - If yes → skip it. If no → save it and pass it along.
"""

import logging
from datetime import datetime, timedelta

from db.database import get_session
from db.models import Article
from config.settings import settings

logger = logging.getLogger(__name__)


def is_article_too_old(published_at: datetime) -> bool:
    """
    Checks if an article is older than the maximum allowed age.

    We don't want to publish news that's already several days old —
    it wouldn't feel fresh or relevant to readers.

    Args:
        published_at (datetime): The date the article was published.

    Returns:
        bool: True if the article is too old and should be skipped.
              False if the article is recent enough to process.
    """
    if published_at is None:
        # If we don't know when it was published, assume it's recent
        return False

    # Calculate the cutoff time: anything older than this is too old
    cutoff_time = datetime.utcnow() - timedelta(hours=settings.MAX_ARTICLE_AGE_HOURS)

    is_old = published_at < cutoff_time

    if is_old:
        logger.debug(
            "Article is too old (published: %s, cutoff: %s) — skipping.",
            published_at.strftime("%Y-%m-%d %H:%M"),
            cutoff_time.strftime("%Y-%m-%d %H:%M"),
        )

    return is_old


def is_duplicate(url: str) -> bool:
    """
    Checks if an article URL already exists in the database.

    We use the URL as the unique identifier for each article.
    If the same URL appears again in a future RSS fetch, we skip it.

    Args:
        url (str): The full URL of the article to check.

    Returns:
        bool: True if this URL is already in the database (duplicate).
              False if this is a new article we haven't seen before.
    """
    with get_session() as session:
        # Query the database: does any article with this URL exist?
        existing = session.query(Article).filter(Article.url == url).first()
        return existing is not None


def save_article(article_data: dict) -> Article:
    """
    Saves a new article to the database.

    Takes a raw article dictionary (from the RSS fetcher) and creates
    a new Article record in the database.

    Args:
        article_data (dict): Dictionary with article details:
                             bot_id, title, url, source_name, summary, published_at.

    Returns:
        Article: The newly created Article database object.
    """
    with get_session() as session:
        article = Article(
            bot_id=article_data["bot_id"],
            title=article_data["title"],
            url=article_data["url"],
            source_name=article_data["source_name"],
            summary=article_data.get("summary", ""),
            published_at=article_data.get("published_at"),
            fetched_at=datetime.utcnow(),
            status="new",
        )
        session.add(article)
        session.flush()  # Flush to get the auto-generated ID before commit

        # Detach from session so the object can be used after session closes
        session.expunge(article)

    logger.debug("Saved new article: [%s] %s", article_data["bot_id"], article_data["title"][:80])
    return article


def filter_and_save_articles(raw_articles: list) -> list:
    """
    Filters a list of raw articles and saves only the new, fresh ones.

    This is the main function called by the pipeline after RSS fetching.
    It runs every article through two checks:
      1. Is it too old? → skip
      2. Is it a duplicate (URL already in DB)? → skip
    Articles that pass both checks are saved to the database.

    Args:
        raw_articles (list): List of article dictionaries from rss_fetcher.py.
                             Each dict must have: bot_id, title, url,
                             source_name, summary, published_at.

    Returns:
        list: List of newly saved Article database objects.
              Only contains articles that passed both checks.

    Example:
        >>> new_articles = filter_and_save_articles(raw_articles)
        >>> print(f"{len(new_articles)} new articles saved to DB")
    """
    if not raw_articles:
        logger.info("No raw articles to filter.")
        return []

    logger.info("Running deduplication on %d raw articles...", len(raw_articles))

    new_articles = []
    skipped_old = 0
    skipped_duplicate = 0

    for article_data in raw_articles:
        url = article_data.get("url", "")
        title = article_data.get("title", "")
        published_at = article_data.get("published_at")

        # ── Check 1: Is the article too old? ──────────────────────────────
        if is_article_too_old(published_at):
            skipped_old += 1
            continue

        # ── Check 2: Is the article a duplicate? ──────────────────────────
        if is_duplicate(url):
            logger.debug("Duplicate skipped: %s", title[:80])
            skipped_duplicate += 1
            continue

        # ── Passed both checks: save to database ──────────────────────────
        try:
            saved_article = save_article(article_data)
            new_articles.append(saved_article)
        except Exception as e:
            # If saving one article fails, log it and continue with the rest
            logger.error("Failed to save article '%s': %s", title[:80], str(e))

    logger.info(
        "Deduplication complete: %d new | %d too old | %d duplicates | %d total processed",
        len(new_articles), skipped_old, skipped_duplicate, len(raw_articles)
    )

    return new_articles
