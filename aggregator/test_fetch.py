"""
aggregator/test_fetch.py
────────────────────────
Quick manual test for the RSS fetcher and deduplication pipeline.

Run this to verify fetching and dedup work correctly:
  $ python aggregator/test_fetch.py

Delete this file after testing if you want to keep the project clean.
"""

import sys
import os
import logging

# Add project root to path so imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.logger import setup_logging
from db.database import init_db
from aggregator.rss_fetcher import fetch_articles_for_bot
from aggregator.dedup import filter_and_save_articles
from db.database import get_session
from db.models import Article

setup_logging("INFO")
logger = logging.getLogger(__name__)

# Initialise DB first
init_db()

# Use the AI News bot config for the test
test_bot = {
    "id": "ai_news",
    "name": "AI News Bot (TEST)",
    "sources_file": "config/sources_ai.json",
}

logger.info("=" * 60)
logger.info("TEST: RSS Fetch + Deduplication")
logger.info("=" * 60)

# Step 1: Fetch raw articles from RSS feeds
logger.info("\n[STEP 1] Fetching RSS feeds...")
raw_articles = fetch_articles_for_bot(test_bot)
logger.info("Total raw articles fetched: %d", len(raw_articles))

if raw_articles:
    logger.info("Sample article:")
    sample = raw_articles[0]
    logger.info("  Title      : %s", sample["title"])
    logger.info("  URL        : %s", sample["url"])
    logger.info("  Source     : %s", sample["source_name"])
    logger.info("  Published  : %s", sample["published_at"])
    logger.info("  Summary    : %s", sample["summary"][:100])

# Step 2: Filter duplicates and save to DB
logger.info("\n[STEP 2] Running deduplication + saving to DB...")
new_articles = filter_and_save_articles(raw_articles)
logger.info("New articles saved to DB: %d", len(new_articles))

# Step 3: Verify what's in the DB
logger.info("\n[STEP 3] Verifying DB contents...")
with get_session() as session:
    total = session.query(Article).count()
    ai_articles = session.query(Article).filter_by(bot_id="ai_news").count()
    logger.info("Total articles in DB  : %d", total)
    logger.info("AI News articles in DB: %d", ai_articles)

    # Show the 3 most recent articles
    recent = session.query(Article).order_by(Article.fetched_at.desc()).limit(3).all()
    logger.info("\nMost recent 3 articles in DB:")
    for i, a in enumerate(recent, 1):
        logger.info("  %d. [%s] %s", i, a.source_name, a.title[:70])

# Step 4: Run fetch again to test deduplication
logger.info("\n[STEP 4] Running fetch again to test dedup (should save 0 new articles)...")
raw_articles_2 = fetch_articles_for_bot(test_bot)
new_articles_2 = filter_and_save_articles(raw_articles_2)
logger.info("New articles saved on second run: %d (expected: 0)", len(new_articles_2))

logger.info("\n" + "=" * 60)
logger.info("TEST COMPLETE")
logger.info("=" * 60)
