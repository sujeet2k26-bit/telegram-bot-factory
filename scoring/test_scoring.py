"""
scoring/test_scoring.py
────────────────────────
Quick test for the virality scoring engine and fallback selection.

Run with:
  $ python scoring/test_scoring.py
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.logger import setup_logging
from db.database import init_db, get_session
from db.models import Article
from scoring.fallback import get_best_articles_for_bot

setup_logging("INFO")
import logging
logger = logging.getLogger(__name__)

init_db()

logger.info("=" * 60)
logger.info("TEST: Virality Scoring + Fallback Selection")
logger.info("=" * 60)

# ── Test 1: Score all new articles for AI News bot ─────────────────────────
logger.info("\n[TEST 1] Scoring AI News articles...")
articles, used_fallback = get_best_articles_for_bot("ai_news", posts_needed=1)

if articles:
    logger.info("\nSelected article(s):")
    for a in articles:
        logger.info("  Title   : %s", a.title)
        logger.info("  Source  : %s", a.source_name)
        logger.info("  Score   : %.1f", a.virality_score or 0)
        logger.info("  Status  : %s", a.status)
        logger.info("  Fallback: %s", used_fallback)
else:
    logger.warning("No articles selected.")

# ── Test 2: Check score distribution in DB ────────────────────────────────
logger.info("\n[TEST 2] Score distribution in DB...")
with get_session() as session:
    scored = (
        session.query(Article)
        .filter(Article.virality_score.isnot(None))
        .order_by(Article.virality_score.desc())
        .limit(10)
        .all()
    )
    logger.info("Top 10 scored articles:")
    for i, a in enumerate(scored, 1):
        logger.info(
            "  %2d. [%5.1f] %-12s — %s",
            i, a.virality_score, a.source_name, a.title[:60]
        )

logger.info("\n" + "=" * 60)
logger.info("TEST COMPLETE")
logger.info("=" * 60)
