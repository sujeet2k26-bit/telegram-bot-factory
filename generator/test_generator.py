"""
generator/test_generator.py
────────────────────────────
Tests the full content generation pipeline end to end.

Run with:
  $ python generator/test_generator.py
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.logger import setup_logging
from db.database import init_db, get_session
from db.models import Article, Post
from scoring.fallback import get_best_articles_for_bot
from generator.claude_client import generate_and_save_post, generate_digest_post

setup_logging("INFO")
import logging
logger = logging.getLogger(__name__)

init_db()

logger.info("=" * 60)
logger.info("TEST: Content Generation Pipeline")
logger.info("=" * 60)

# ── Test: Generate a digest post for AI News bot (top 5 stories) ──────────
logger.info("\n[TEST 1] Selecting top 5 articles for AI News digest...")
articles, used_fallback = get_best_articles_for_bot("ai_news", posts_needed=5)

if not articles:
    logger.error("No articles available to generate post from. Run test_fetch.py first.")
    sys.exit(1)

logger.info("Selected %d article(s) (fallback=%s):", len(articles), used_fallback)
for i, a in enumerate(articles, 1):
    logger.info("  %d. [score=%.1f] %s", i, a.virality_score or 0, a.title[:70])

logger.info("\n[TEST 2] Generating digest post with Gemini...")
if len(articles) > 1:
    post = generate_digest_post(articles, "ai_news")
else:
    # Fallback to single-article if only 1 article available
    post = generate_and_save_post(articles[0], "ai_news")

if post:
    logger.info("\n✓ Digest post generated and saved to DB (post_id=%d)", post.id)
    logger.info("\n--- GENERATED DIGEST POST ---\n")
    sys.stdout.buffer.write((post.content + "\n").encode("utf-8", errors="replace"))
    print()
    logger.info("--- END OF POST ---\n")
    logger.info("Image URL: %s", post.image_url or "No image generated")
    logger.info("Post status: %s", post.status)
else:
    logger.error("Digest post generation failed.")

# ── Verify post is in DB ───────────────────────────────────────────────────
logger.info("\n[TEST 3] Verifying post saved in DB...")
with get_session() as session:
    count = session.query(Post).filter_by(bot_id="ai_news").count()
    logger.info("Total posts in DB for AI News bot: %d", count)

logger.info("\n" + "=" * 60)
logger.info("TEST COMPLETE")
logger.info("=" * 60)
