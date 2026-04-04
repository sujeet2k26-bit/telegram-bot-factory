"""
scoring/fallback.py
────────────────────
Fallback selection when no article meets the virality threshold.

What this file does:
  - Called only when virality.py finds NO article scoring >= 60.
  - On slow news days, the virality threshold may not be met.
  - Instead of publishing nothing, we pick the best available article
    using a simpler fallback strategy: most recent article first.
  - The fallback article is tagged differently in the DB so you know
    it was selected via fallback, not because it was genuinely viral.

Fallback strategy (in priority order):
  1. Most recently published article (freshest news, even if not viral)
  2. Highest virality score even if below threshold (best of what we have)

The fallback post still goes through the full human review step —
the reviewer can reject it if they don't think it's worth publishing.
"""

import logging
from db.database import get_session
from db.models import Article

logger = logging.getLogger(__name__)


def select_fallback_articles(bot_id: str, posts_needed: int = 1) -> list:
    """
    Selects the best available articles when virality threshold is not met.

    Queries the database for all scored articles for this bot
    and picks the top N by a fallback ranking:
      - Primary sort: highest virality score (even if below threshold)
      - Secondary sort: most recently published

    Args:
        bot_id (str):       The bot ID to select fallback articles for.
                            e.g. "ai_news" or "bollywood"
        posts_needed (int): How many articles to return.

    Returns:
        list: A list of Article objects selected as fallback.
              Returns empty list if no scored articles exist for this bot.

    Example:
        >>> fallback = select_fallback_articles("ai_news", posts_needed=1)
        >>> if fallback:
        ...     print(f"Fallback article: {fallback[0].title}")
    """
    logger.info(
        "Running fallback selection for bot '%s' (need %d article(s))...",
        bot_id, posts_needed
    )

    try:
        with get_session() as session:
            # Fetch a larger pool so we can apply the diversity cap without
            # running out of candidates (fetch up to 5× what we need).
            pool_limit = max(posts_needed * 5, 20)
            pool = (
                session.query(Article)
                .filter(
                    Article.bot_id == bot_id,
                    Article.status == "scored",        # Only scored articles
                    Article.virality_score.isnot(None) # Must have a score
                )
                .order_by(
                    Article.virality_score.desc(),     # Highest score first
                    Article.published_at.desc()        # Most recent first (tiebreaker)
                )
                .limit(pool_limit)
                .all()
            )

            # Detach from session so we can use the objects after session closes
            session.expunge_all()

        # Apply source diversity cap: at most 2 articles per source
        MAX_PER_SOURCE = 2
        source_counts: dict = {}
        candidates = []
        for article in pool:
            source = article.source_name
            if source_counts.get(source, 0) >= MAX_PER_SOURCE:
                continue
            source_counts[source] = source_counts.get(source, 0) + 1
            candidates.append(article)
            if len(candidates) >= posts_needed:
                break

        if not candidates:
            logger.warning(
                "No fallback candidates found for bot '%s'. "
                "Nothing to publish today.",
                bot_id
            )
            return []

        # Mark fallback articles in the DB with a special status
        # "selected_fallback" vs "selected" so you can track this in analytics later
        for article in candidates:
            _mark_as_fallback(article.id)

        logger.info(
            "Fallback selected %d article(s) for bot '%s':",
            len(candidates), bot_id
        )
        for i, article in enumerate(candidates, 1):
            logger.info(
                "  %d. [score=%.1f] %s",
                i,
                article.virality_score or 0,
                article.title[:70]
            )

        return candidates

    except Exception as e:
        logger.error(
            "Fallback selection failed for bot '%s': %s", bot_id, str(e)
        )
        return []


def _mark_as_fallback(article_id: int) -> None:
    """
    Marks an article as selected via fallback in the database.

    Using a distinct status ("selected_fallback") lets you later
    analyse how often the virality threshold is being met vs missed.

    Args:
        article_id (int): The ID of the article to mark.
    """
    try:
        with get_session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if article:
                article.status = "selected_fallback"
    except Exception as e:
        logger.error(
            "Failed to mark article %d as fallback: %s", article_id, str(e)
        )


def get_best_articles_for_bot(bot_id: str, posts_needed: int) -> tuple:
    """
    Master selection function: tries virality first, falls back if needed.

    This is the single function the pipeline calls to get the day's
    articles for a bot. It handles both the normal case (viral articles
    found) and the fallback case (nothing viral today).

    Args:
        bot_id (str):       The bot ID to select articles for.
        posts_needed (int): How many articles the bot needs today.

    Returns:
        tuple: A two-element tuple:
               - articles (list): The selected Article objects
               - used_fallback (bool): True if fallback was used

    Example:
        >>> articles, used_fallback = get_best_articles_for_bot("ai_news", 1)
        >>> if used_fallback:
        ...     print("Using fallback — no viral stories today")
    """
    from scoring.virality import score_and_select
    from guardrails.content_filter import filter_articles
    from db.database import get_session
    from db.models import Article

    # Fetch today's unscored articles for this bot from DB
    with get_session() as session:
        unscored = (
            session.query(Article)
            .filter(
                Article.bot_id == bot_id,
                Article.status == "new"
            )
            .all()
        )
        session.expunge_all()

    if not unscored:
        logger.warning("No unscored articles in DB for bot '%s'.", bot_id)
        # Try fallback with already-scored articles
        fallback_articles = select_fallback_articles(bot_id, posts_needed)
        return fallback_articles, True

    # Run guardrail checks first
    clean_articles, _ = filter_articles(unscored)

    if not clean_articles:
        logger.warning("All articles for bot '%s' were blocked by guardrails.", bot_id)
        return [], False

    # Try virality scoring first
    selected = score_and_select(clean_articles, posts_needed)

    if selected:
        return selected, False  # Viral articles found — no fallback needed

    # No viral articles — use fallback
    logger.info("No viral articles found for bot '%s'. Activating fallback.", bot_id)
    fallback_articles = select_fallback_articles(bot_id, posts_needed)
    return fallback_articles, True
