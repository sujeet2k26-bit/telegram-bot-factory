"""
guardrails/test_guardrails.py
──────────────────────────────
Quick test for the guardrails content filter.

Run with:
  $ python guardrails/test_guardrails.py
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.logger import setup_logging
from db.database import init_db, get_session
from db.models import Article
from guardrails.content_filter import check_article, check_generated_post, filter_articles

setup_logging("INFO")
import logging
logger = logging.getLogger(__name__)

init_db()

logger.info("=" * 60)
logger.info("TEST: Guardrails Content Filter")
logger.info("=" * 60)

# ── Test 1: Check real articles from DB ────────────────────────────────────
logger.info("\n[TEST 1] Running guardrails on articles already in DB...")
with get_session() as session:
    articles = session.query(Article).filter_by(status="new").limit(10).all()
    session.expunge_all()

clean, blocked = filter_articles(articles)
logger.info("Result: %d clean | %d blocked out of %d checked", len(clean), len(blocked), len(articles))

# ── Test 2: Simulate a blocked article ─────────────────────────────────────
logger.info("\n[TEST 2] Testing with a fake article containing blocked keywords...")
fake_blocked = Article(
    id=99999,
    bot_id="ai_news",
    title="SHOCKING: Graphic violence exposed in leaked video — watch before deleted",
    url="http://fake-test-url.com/blocked",
    source_name="TechCrunch AI",
    summary="This contains some graphic murder details that should be blocked.",
    status="new",
)
result = check_article(fake_blocked)
logger.info("Blocked article result: is_blocked=%s | category=%s | action=%s",
            result["is_blocked"], result["category"], result["action"])

# ── Test 3: Simulate a clean article ───────────────────────────────────────
logger.info("\n[TEST 3] Testing with a clean fake article...")
fake_clean = Article(
    id=99998,
    bot_id="ai_news",
    title="Google DeepMind releases new AI model with improved reasoning",
    url="http://fake-test-url.com/clean",
    source_name="TechCrunch AI",
    summary="Google's DeepMind lab announced a new large language model today.",
    status="new",
)
result = check_article(fake_clean)
logger.info("Clean article result: is_blocked=%s", result["is_blocked"])

# ── Test 4: Post-generation check ──────────────────────────────────────────
logger.info("\n[TEST 4] Testing post-generation guardrail check...")
clean_post = "OpenAI has released GPT-5 with improved capabilities in reasoning and coding."
blocked_post = "This article contains explicit sexual content that should be blocked."

r1 = check_generated_post(clean_post, "ai_news")
r2 = check_generated_post(blocked_post, "ai_news")
logger.info("Clean post   → is_blocked=%s", r1["is_blocked"])
logger.info("Blocked post → is_blocked=%s | category=%s", r2["is_blocked"], r2["category"])

# ── Test 5: Untrusted source ───────────────────────────────────────────────
logger.info("\n[TEST 5] Testing untrusted source check...")
fake_untrusted = Article(
    id=99997,
    bot_id="ai_news",
    title="Some article from an unknown blog",
    url="http://fake-test-url.com/untrusted",
    source_name="RandomBlog.com",
    summary="This source is not in our trusted list.",
    status="new",
)
result = check_article(fake_untrusted)
logger.info("Untrusted source result: is_blocked=%s | action=%s", result["is_blocked"], result["action"])

logger.info("\n" + "=" * 60)
logger.info("TEST COMPLETE — check logs/guardrail_violations.log for violation entries")
logger.info("=" * 60)
