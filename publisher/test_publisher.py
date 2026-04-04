"""
publisher/test_publisher.py
────────────────────────────
Tests the Telegram publisher by sending a real post to your channel.

IMPORTANT: This will send a REAL message to your Telegram channel.
           Make sure you have set up the channel and added the bot as admin.

Run with:
  $ python publisher/test_publisher.py
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.logger import setup_logging
from db.database import init_db, get_session
from db.models import Post
from publisher.telegram_bot import publish_post

setup_logging("INFO")
import logging
logger = logging.getLogger(__name__)

init_db()

logger.info("=" * 60)
logger.info("TEST: Telegram Publisher")
logger.info("=" * 60)

# ── Find the most recent generated post ───────────────────────────────────
with get_session() as session:
    # Get the latest post that was generated (any status)
    post = (
        session.query(Post)
        .filter_by(bot_id="ai_news")
        .order_by(Post.created_at.desc())
        .first()
    )
    if post:
        session.expunge(post)

if not post:
    logger.error("No posts found in DB. Run generator/test_generator.py first.")
    sys.exit(1)

logger.info("Found post_id=%d | status='%s'", post.id, post.status)
logger.info("Content preview: %s...", post.content[:100])

# ── Temporarily set status to 'approved' for testing ──────────────────────
# In normal flow, the reviewer sets this via /approve command
logger.info("\nSetting post status to 'approved' for test...")
with get_session() as session:
    db_post = session.query(Post).filter(Post.id == post.id).first()
    if db_post:
        db_post.status = "approved"

# Re-fetch the updated post
with get_session() as session:
    post = session.query(Post).filter(Post.id == post.id).first()
    session.expunge(post)

# ── Publish it ────────────────────────────────────────────────────────────
logger.info("\nPublishing post to Telegram channel...")
success = publish_post(post)

if success:
    logger.info("\nSUCCESS — Check your Telegram channel for the post!")
    # Verify DB was updated
    with get_session() as session:
        updated = session.query(Post).filter(Post.id == post.id).first()
        logger.info("Post status in DB: %s", updated.status)
        logger.info("Published at: %s", updated.published_at)
else:
    logger.error("\nFAILED — Check your bot token and channel ID in .env")

logger.info("\n" + "=" * 60)
logger.info("TEST COMPLETE")
logger.info("=" * 60)
