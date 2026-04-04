"""
publisher/test_review_interface.py
────────────────────────────────────
Tests the full human review flow.

What this test does:
  1. Generates a fresh AI News post (fetch → score → generate).
  2. Sends it to your Telegram reviewer chat with Approve / Reject buttons.
  3. Starts the review bot so you can tap the buttons and see what happens.

When you tap Approve → the post is published to your channel immediately.
When you tap Reject → the bot asks you for a reason, then marks it rejected.

You can also type these commands in the reviewer chat:
  /pending   → see all posts waiting for review
  /preview 5 → see post #5 in full
  /sources 5 → see the original article for post #5
  /skip 5    → skip post #5

Press Ctrl+C in this terminal to stop the review bot.

Run with:
  $ python publisher/test_review_interface.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.logger import setup_logging
from db.database import init_db, get_session
from db.models import Post, Article
from publisher.review_interface import send_for_review, start_review_bot
from scoring.fallback import get_best_articles_for_bot
from generator.claude_client import generate_and_save_post, generate_digest_post

setup_logging("INFO")
import logging
logger = logging.getLogger(__name__)

init_db()

logger.info("=" * 60)
logger.info("TEST: Human Review Interface")
logger.info("=" * 60)

# ── Step 1: Find or generate a pending_review post ────────────────────────────
# First, look for an existing pending post so we don't generate unnecessarily
with get_session() as session:
    post = (
        session.query(Post)
        .filter_by(bot_id="ai_news", status="pending_review")
        .order_by(Post.created_at.desc())
        .first()
    )
    if post:
        session.expunge(post)

if post:
    logger.info("Found existing pending post: post_id=%d", post.id)
    logger.info("Content preview: %s...", post.content[:100])
else:
    # No pending post — generate a fresh digest (top 5 articles)
    logger.info("No pending posts found. Generating a fresh digest post (top 5)...")

    articles, used_fallback = get_best_articles_for_bot("ai_news", posts_needed=5)

    if not articles:
        logger.error(
            "No articles available. Run aggregator/test_fetch.py first to fetch articles."
        )
        sys.exit(1)

    logger.info("Selected %d article(s) (fallback=%s):", len(articles), used_fallback)
    for i, a in enumerate(articles, 1):
        logger.info("  %d. [score=%.1f] %s", i, a.virality_score or 0, a.title[:70])

    if len(articles) > 1:
        post = generate_digest_post(articles, "ai_news")
    else:
        post = generate_and_save_post(articles[0], "ai_news")

    if not post:
        logger.error("Post generation failed. Check your EURI_API_KEY in .env")
        sys.exit(1)

    logger.info("Digest post generated: post_id=%d", post.id)

# ── Step 2: Send the post to the reviewer's Telegram chat ─────────────────────
logger.info("\nSending post %d to reviewer chat...", post.id)
sent = send_for_review(post)

if sent:
    logger.info(
        "✓ Review message sent! Check your Telegram reviewer chat."
    )
    logger.info(
        "  You should see the post with ✅ Approve and ❌ Reject buttons."
    )
else:
    logger.error(
        "Failed to send review message. Check TELEGRAM_REVIEWER_CHAT_ID in .env"
    )
    sys.exit(1)

# ── Step 3: Start the review bot to listen for button taps ───────────────────
logger.info("\n" + "=" * 60)
logger.info("Review bot is now running and listening for your response.")
logger.info("Go to your Telegram reviewer chat and tap Approve or Reject.")
logger.info("Press Ctrl+C here to stop.")
logger.info("=" * 60 + "\n")

# start_review_bot() runs forever (blocking) — it listens for Telegram updates.
# Press Ctrl+C to stop.
start_review_bot()
