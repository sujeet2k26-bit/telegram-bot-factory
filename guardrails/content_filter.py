"""
guardrails/content_filter.py
─────────────────────────────
The main content safety filter for the AI News Bot.

What this file does:
  - Runs TWO rounds of safety checks:
      1. PRE-GENERATION: Checks raw article (title + summary) BEFORE
         sending it to Gemini for content generation.
      2. POST-GENERATION: Checks the AI-generated post text BEFORE
         sending it to the human reviewer.
  - Uses keyword matching for fast, reliable blocking.
  - Logs every violation to logs/guardrail_violations.log.
  - Updates the article's status in the database to 'blocked' if rejected.

The 6 guardrail categories (all hard blocks except clickbait):
  1. hate_speech      → skip + log
  2. sexual_content   → skip + log
  3. violence         → skip + log
  4. political        → skip + log
  5. defamation       → skip + log (unverified celebrity accusations)
  6. clickbait        → FLAG for human review (not auto-skip)

Why two rounds of checks?
  - Pre-generation: Stops bad content from being sent to the AI model.
    Saves API tokens and prevents the model from processing harmful input.
  - Post-generation: Catches cases where the AI model accidentally
    includes problematic content in its output (rare but possible).

How to use:
  >>> from guardrails.content_filter import check_article, check_generated_post
  >>>
  >>> # Before generating content:
  >>> result = check_article(article)
  >>> if result["is_blocked"]:
  ...     print(f"Blocked: {result['reason']}")
  ...
  >>> # After generating content:
  >>> result = check_generated_post(post_text, bot_id)
  >>> if result["is_blocked"]:
  ...     print(f"Post blocked: {result['reason']}")
"""

import json
import logging
import os
from datetime import datetime

from guardrails.keyword_blocklist import check_for_blocked_keywords
from guardrails.source_whitelist import is_trusted_source
from db.database import get_session
from db.models import Article

# Use the guardrails logger so violations go to guardrail_violations.log
logger = logging.getLogger("guardrails.content_filter")

# ── AI relevance keywords ──────────────────────────────────────────────────
# Articles from community sources (e.g. Hacker News) are only kept if they
# mention at least one of these keywords — otherwise they are off-topic.
_AI_RELEVANCE_KEYWORDS = [
    # Core AI / ML concepts
    "artificial intelligence", " ai ", "machine learning", "deep learning",
    "neural network", "large language model", "llm", "generative ai",
    "foundation model", "transformer", "diffusion model",
    # Popular models & products
    "chatgpt", "gpt-4", "gpt-5", "gpt-o", "o1 ", "o3 ", "o4 ",
    "claude", "gemini", "gemma", "llama", "mistral", "qwen", "grok",
    "phi-", "falcon", "mixtral", "deepseek", "yi-",
    "copilot", "midjourney", "stable diffusion", "dall-e", "sora", "flux",
    "openai", "anthropic", "deepmind", "hugging face", "replicate",
    "cursor ", "windsurf", "devin", "codex",
    # AI sub-fields
    "natural language processing", "nlp", "computer vision", "robotics",
    "reinforcement learning", "rlhf", "fine-tuning", "fine tuning",
    "retrieval augmented", "rag", "multimodal", "reasoning model",
    "inference", "training", "benchmark", "alignment",
    # Industry / tech context
    "gpu", "nvidia", "tpu", "cuda", "ai chip", "ai regulation",
    "ai safety", "ai ethics", "ai governance", "ai agent", "agentic",
    "automation", "autonomous", "voice assistant", "image generation",
    "text to image", "text-to-image", "text to video", "text-to-video",
]

# Source categories that must pass the AI relevance check.
# - ai_official, ai_research, ai_newsletter → always AI-relevant, skip check
# - ai_technology (TechCrunch, The Verge, etc.) → general tech feeds, must check
# - ai_community (Hacker News) → all-topics feed, must check
_REQUIRES_RELEVANCE_CHECK = {"ai_technology", "ai_community"}


def _load_source_categories() -> dict:
    """
    Loads a mapping of source_name → category from sources_ai.json.

    Returns:
        dict: {source_name: category} for all sources in the file.
              Returns empty dict if the file cannot be read.
    """
    sources_file = os.path.join(
        os.path.dirname(__file__), "..", "config", "sources_ai.json"
    )
    try:
        with open(sources_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {s["name"]: s.get("category", "") for s in data.get("sources", [])}
    except Exception as e:
        logger.warning("Could not load source categories: %s", str(e))
        return {}


# Cache the source→category map at module load time (it never changes at runtime)
_SOURCE_CATEGORY_MAP = _load_source_categories()


def is_ai_relevant(article: Article) -> bool:
    """
    Checks whether an article from a community or general-purpose source
    is actually about AI or technology topics.

    Articles from dedicated AI sources (ai_official, ai_research,
    ai_technology, ai_newsletter) are assumed relevant and always pass.

    Articles from community sources (ai_community, e.g. Hacker News)
    must contain at least one AI relevance keyword to pass. This prevents
    off-topic stories like finance, politics, or celebrity news from
    entering the digest just because they were popular on HN.

    Args:
        article (Article): The article to check.

    Returns:
        bool: True if the article is AI-relevant (or from a dedicated AI source).
              False if it's from a community source and contains no AI keywords.
    """
    # Look up this source's category
    category = _SOURCE_CATEGORY_MAP.get(article.source_name, "")

    # Only apply the relevance filter to general/mixed tech sources.
    # Official AI blogs, research sources, and newsletters are always relevant.
    if category not in _REQUIRES_RELEVANCE_CHECK:
        return True  # Dedicated AI source — always relevant

    # Community source: require at least one AI keyword in title + summary
    combined = f"{article.title} {article.summary or ''}".lower()
    for keyword in _AI_RELEVANCE_KEYWORDS:
        if keyword in combined:
            return True

    logger.debug(
        "AI relevance check FAILED for community article: '%s' (source=%s)",
        article.title[:80], article.source_name
    )
    return False


def _build_check_result(is_blocked: bool, category: str = None,
                         reason: str = None, action: str = None) -> dict:
    """
    Builds a standardised result dictionary for a guardrail check.

    Using a consistent structure makes it easy for the calling code
    to always know what fields to expect in the result.

    Args:
        is_blocked (bool): Whether the content should be blocked.
        category (str):    The guardrail category that triggered, e.g. "hate_speech".
        reason (str):      A human-readable explanation of why it was blocked.
        action (str):      What to do — "block", "flag_for_review", or None.

    Returns:
        dict: A result dictionary with keys: is_blocked, category, reason, action.
    """
    return {
        "is_blocked": is_blocked,
        "category": category,
        "reason": reason,
        "action": action,
    }


def _log_violation(content_type: str, identifier: str,
                    category: str, reason: str) -> None:
    """
    Logs a guardrail violation to the guardrail_violations.log file.

    Every blocked piece of content gets a log entry so you can review
    what was blocked and why. This helps you tune the keyword list over time.

    Args:
        content_type (str): "article" or "generated_post"
        identifier (str):   The article title or post preview (first 100 chars)
        category (str):     The guardrail category that triggered
        reason (str):       Human-readable reason for blocking
    """
    logger.warning(
        "BLOCKED | type=%-15s | category=%-20s | reason=%s | content='%s'",
        content_type, category, reason, identifier[:100]
    )


def check_article(article: Article) -> dict:
    """
    PRE-GENERATION CHECK: Runs safety checks on a raw article.

    Called BEFORE the article is sent to Gemini for content generation.
    Checks the article title and summary against all guardrail rules.

    If the article fails any check:
      - Its status in the database is updated to 'blocked'
      - The violation is logged to guardrail_violations.log
      - Returns is_blocked=True so the pipeline skips it

    Args:
        article (Article): An Article database object to check.
                           Uses the title, summary, and source_name fields.

    Returns:
        dict: A result dictionary with keys:
              - is_blocked (bool): True if article should be skipped
              - category (str):    Which guardrail triggered (or None)
              - reason (str):      Why it was blocked (or None)
              - action (str):      "block", "flag_for_review", or None

    Example:
        >>> result = check_article(article)
        >>> if result["is_blocked"]:
        ...     continue  # skip this article
    """
    # Combine title and summary for a thorough check
    combined_text = f"{article.title} {article.summary or ''}"
    identifier = article.title

    # ── Check 1: Source whitelist ──────────────────────────────────────────
    # Articles from non-trusted sources are flagged for human review,
    # not automatically blocked.
    if not is_trusted_source(article.source_name):
        _log_violation("article", identifier, "untrusted_source",
                       f"Source '{article.source_name}' is not in the whitelist")
        return _build_check_result(
            is_blocked=True,
            category="untrusted_source",
            reason=f"Source '{article.source_name}' is not whitelisted",
            action="flag_for_review"
        )

    # ── Check 2: AI relevance (community sources only) ────────────────────
    # Community sources like Hacker News cover all topics. Only keep articles
    # that are actually about AI/tech — ignore finance, politics, etc.
    if not is_ai_relevant(article):
        _log_violation(
            "article", identifier, "off_topic",
            f"Community source article contains no AI keywords — skipping"
        )
        _update_article_status(article.id, "blocked", "off_topic")
        return _build_check_result(
            is_blocked=True,
            category="off_topic",
            reason="Community source article is not AI-relevant",
            action="block"
        )

    # ── Check 3: Blocked keywords ──────────────────────────────────────────
    is_blocked, category = check_for_blocked_keywords(combined_text)

    if is_blocked:
        # Clickbait gets flagged for review, not auto-blocked
        if category == "clickbait_patterns":
            _log_violation("article", identifier, category,
                           "Clickbait pattern detected — flagging for review")
            _update_article_status(article.id, "blocked", category)
            return _build_check_result(
                is_blocked=True,
                category=category,
                reason="Clickbait headline pattern detected",
                action="flag_for_review"
            )

        # All other categories are hard blocks
        reason = f"Blocked keyword found in category: {category}"
        _log_violation("article", identifier, category, reason)
        _update_article_status(article.id, "blocked", category)
        return _build_check_result(
            is_blocked=True,
            category=category,
            reason=reason,
            action="block"
        )

    # ── All checks passed ──────────────────────────────────────────────────
    logger.debug("Article passed all guardrail checks: %s", identifier[:80])
    return _build_check_result(is_blocked=False)


def check_generated_post(post_text: str, bot_id: str) -> dict:
    """
    POST-GENERATION CHECK: Runs safety checks on AI-generated post text.

    Called AFTER Gemini generates a post, BEFORE it is sent to the reviewer.
    This is the second line of defence — catches any problematic content
    that the AI model may have introduced in its output.

    Args:
        post_text (str): The full text of the generated Telegram post.
        bot_id (str):    The bot ID, used for logging context.

    Returns:
        dict: A result dictionary with keys:
              - is_blocked (bool): True if post should be discarded
              - category (str):    Which guardrail triggered (or None)
              - reason (str):      Why it was blocked (or None)
              - action (str):      "block" or None

    Example:
        >>> result = check_generated_post(generated_text, "ai_news")
        >>> if result["is_blocked"]:
        ...     # Discard this post, do not send to reviewer
        ...     pass
    """
    if not post_text or not post_text.strip():
        logger.warning("Generated post is empty for bot '%s' — blocking.", bot_id)
        return _build_check_result(
            is_blocked=True,
            category="empty_content",
            reason="Generated post is empty",
            action="block"
        )

    # Check the generated text against blocked keywords
    is_blocked, category = check_for_blocked_keywords(post_text)

    if is_blocked:
        reason = f"Generated post contains blocked content in category: {category}"
        _log_violation("generated_post", post_text[:100], category, reason)
        return _build_check_result(
            is_blocked=True,
            category=category,
            reason=reason,
            action="block"
        )

    logger.debug("Generated post passed all guardrail checks for bot '%s'.", bot_id)
    return _build_check_result(is_blocked=False)


def filter_articles(articles: list) -> tuple:
    """
    Runs guardrail checks on a list of articles and splits them into
    clean (passed) and blocked lists.

    This is a convenience function that processes a whole batch of
    articles at once, which is how the pipeline uses it.

    Args:
        articles (list): List of Article database objects to check.

    Returns:
        tuple: A two-element tuple:
               - clean_articles (list):   Articles that passed all checks
               - blocked_articles (list): Articles that were blocked

    Example:
        >>> clean, blocked = filter_articles(new_articles)
        >>> print(f"{len(clean)} clean, {len(blocked)} blocked")
    """
    clean_articles = []
    blocked_articles = []

    for article in articles:
        result = check_article(article)

        if result["is_blocked"]:
            blocked_articles.append({
                "article": article,
                "result": result
            })
        else:
            clean_articles.append(article)

    logger.info(
        "Guardrail filter complete: %d passed | %d blocked",
        len(clean_articles), len(blocked_articles)
    )

    return clean_articles, blocked_articles


def _update_article_status(article_id: int, status: str, blocked_reason: str = None) -> None:
    """
    Updates an article's status in the database after a guardrail check.

    This keeps the database in sync with what happened to each article.
    You can query for 'blocked' articles later to review or analyse them.

    Args:
        article_id (int):      The ID of the article to update.
        status (str):          The new status, e.g. "blocked".
        blocked_reason (str):  The guardrail category that triggered the block.

    Returns:
        None
    """
    try:
        with get_session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if article:
                article.status = status
                article.blocked_reason = blocked_reason
    except Exception as e:
        # Non-critical — log the error but don't crash the pipeline
        logger.error(
            "Failed to update article %d status to '%s': %s",
            article_id, status, str(e)
        )
