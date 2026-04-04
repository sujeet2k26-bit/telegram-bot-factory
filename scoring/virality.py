"""
scoring/virality.py
────────────────────
Calculates a virality score for each article to decide which stories
are worth generating a post for.

What this file does:
  - Scores every clean article (that passed guardrails) on 3 signals.
  - Saves the score back to the article in the database.
  - Returns articles sorted by score, highest first.
  - Articles scoring >= VIRALITY_THRESHOLD (60) are selected for posting.
  - If nothing hits the threshold, scoring/fallback.py handles it.

The 3 scoring signals (Phase 1):
  ┌─────────────────────┬──────────┬────────────────────────────────────┐
  │ Signal              │ Max pts  │ How it's measured                  │
  ├─────────────────────┼──────────┼────────────────────────────────────┤
  │ Recency             │   30     │ How recently the article published │
  │ Source Overlap      │   30     │ Same story covered by 2+ sources   │
  │ Keyword Weight      │   20     │ Contains trending keywords         │
  └─────────────────────┴──────────┴────────────────────────────────────┘
  Total max score: 80 (Reddit signal adds 20 more in Phase 2)
  Publish threshold: 60

Note on Reddit signal:
  Reddit upvote scoring is a Phase 2 feature.
  In Phase 1, the max possible score is 80.
  The threshold of 60 is still achievable: e.g. 30 (recency) + 15 (overlap) + 15 (keywords) = 60.
"""

import json
import logging
import os
from datetime import datetime, timedelta

from db.database import get_session
from db.models import Article
from guardrails.keyword_blocklist import get_trending_keywords
from config.settings import settings

logger = logging.getLogger(__name__)


# ── Scoring weights ────────────────────────────────────────────────────────
# These values control how much each signal contributes to the final score.
# Adjust these in config/settings.py if you want to rebalance them later.

MAX_RECENCY_SCORE = 30      # Full score for articles published in last 6 hours
MAX_OVERLAP_SCORE = 30      # Full score when 3+ sources cover the same story
MAX_KEYWORD_SCORE = 20      # Full score when 3+ trending keywords are matched
# MAX_REDDIT_SCORE = 20     # Phase 2 — not implemented yet

# ── Source category weight multipliers ────────────────────────────────────
# Official AI company blogs and research sources are more authoritative
# than community aggregators. This multiplier is applied to the final score
# so that a strong HN post still wins, but neutral articles don't flood
# the top 5 just because HN posts so many.
_SOURCE_CATEGORY_WEIGHT = {
    "ai_official":    1.5,   # OpenAI, Anthropic, DeepMind, etc.
    "ai_research":    1.3,   # ArXiv, MIT News, BAIR, Papers With Code
    "ai_newsletter":  1.2,   # TLDR AI, The Rundown, Ben's Bites
    "ai_technology":  1.0,   # TechCrunch, The Verge, Ars Technica (baseline)
    "ai_community":   0.7,   # Hacker News — reduce weight vs dedicated sources
}


def _load_source_weight_map() -> dict:
    """
    Loads a mapping of source_name → weight multiplier from sources_ai.json.

    Returns:
        dict: {source_name: multiplier float}
    """
    sources_file = os.path.join(
        os.path.dirname(__file__), "..", "config", "sources_ai.json"
    )
    try:
        with open(sources_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            s["name"]: _SOURCE_CATEGORY_WEIGHT.get(s.get("category", ""), 1.0)
            for s in data.get("sources", [])
        }
    except Exception as e:
        logger.warning("Could not load source weights: %s — using 1.0 for all", str(e))
        return {}


# Cache at module load — sources don't change at runtime
_SOURCE_WEIGHT_MAP = _load_source_weight_map()


def calculate_recency_score(published_at: datetime) -> float:
    """
    Scores an article based on how recently it was published.

    Fresher articles get higher scores. Articles published in the
    last 6 hours get the maximum score. Articles older than 48 hours
    get zero (they should have been filtered by dedup already).

    Score breakdown:
      0–6 hours old  → 30 points (maximum freshness)
      6–12 hours old → 20 points
      12–24 hours old→ 10 points
      24–48 hours old→  5 points
      > 48 hours old →  0 points

    Args:
        published_at (datetime): When the article was published (UTC).

    Returns:
        float: A recency score between 0 and 30.
    """
    if published_at is None:
        # Unknown publish time — give a low default score
        return 5.0

    # Calculate how many hours ago the article was published
    hours_ago = (datetime.utcnow() - published_at).total_seconds() / 3600

    if hours_ago <= 6:
        score = MAX_RECENCY_SCORE           # 30 points — very fresh
    elif hours_ago <= 12:
        score = MAX_RECENCY_SCORE * 0.67    # 20 points — fresh
    elif hours_ago <= 24:
        score = MAX_RECENCY_SCORE * 0.33    # 10 points — today
    elif hours_ago <= 48:
        score = MAX_RECENCY_SCORE * 0.17    # 5 points — yesterday
    else:
        score = 0.0                          # 0 points — too old

    logger.debug("Recency score: %.1f (published %.1f hours ago)", score, hours_ago)
    return score


def calculate_keyword_score(article_text: str, bot_id: str) -> float:
    """
    Scores an article based on how many trending keywords it contains.

    Articles that mention hot topics (e.g. GPT-5, Shah Rukh Khan,
    box office) get a higher score because readers are more likely
    to care about them right now.

    Score breakdown:
      3+ keyword matches → 20 points (maximum)
      2 keyword matches  → 13 points
      1 keyword match    → 7 points
      0 keyword matches  → 0 points

    Args:
        article_text (str): The article title + summary combined.
        bot_id (str):       The bot ID to load the right keyword list.
                            e.g. "ai_news" uses AI/tech keywords.

    Returns:
        float: A keyword score between 0 and 20.
    """
    trending_keywords = get_trending_keywords(bot_id)
    if not trending_keywords:
        logger.debug("No trending keywords found for bot '%s' — keyword score: 0", bot_id)
        return 0.0

    text_lower = article_text.lower()

    # Count how many trending keywords appear in the text
    matched_keywords = [kw for kw in trending_keywords if kw.lower() in text_lower]
    match_count = len(matched_keywords)

    if match_count >= 3:
        score = MAX_KEYWORD_SCORE           # 20 points
    elif match_count == 2:
        score = MAX_KEYWORD_SCORE * 0.65    # 13 points
    elif match_count == 1:
        score = MAX_KEYWORD_SCORE * 0.35    # 7 points
    else:
        score = 0.0

    if matched_keywords:
        logger.debug(
            "Keyword score: %.1f — matched: %s",
            score, matched_keywords[:5]  # Show up to 5 matched keywords in logs
        )

    return score


def calculate_source_overlap_score(article: Article, all_articles: list) -> float:
    """
    Scores an article based on how many different sources are covering
    the same story at the same time.

    When multiple trusted sources all write about the same event,
    it's a strong signal that the story is genuinely important.

    How "same story" is detected:
      We look for significant word overlap between article titles.
      If 3 or more words from one title appear in another title
      (excluding common words like "the", "a", "is"), we consider
      them to be covering the same story.

    Score breakdown:
      3+ sources covering same story → 30 points
      2 sources covering same story  → 15 points
      Only 1 source (unique story)   → 0 points

    Args:
        article (Article):     The article to score.
        all_articles (list):   All other articles fetched in this batch,
                               used to find overlapping stories.

    Returns:
        float: A source overlap score between 0 and 30.
    """
    # Words to ignore when comparing titles (too common to be meaningful)
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "has", "have", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "shall", "can", "need",
        "to", "of", "in", "on", "at", "by", "for", "with", "about",
        "as", "into", "through", "during", "before", "after", "above",
        "below", "from", "up", "down", "out", "off", "over", "under",
        "and", "but", "or", "nor", "so", "yet", "both", "either",
        "not", "no", "its", "it", "this", "that", "these", "those",
        "new", "says", "say", "said", "report", "reports", "latest"
    }

    def get_meaningful_words(title: str) -> set:
        """Extracts meaningful (non-stop) words from a title."""
        words = title.lower().split()
        # Keep only words longer than 3 characters that aren't stop words
        return {w.strip(".,!?\"'") for w in words
                if len(w) > 3 and w not in stop_words}

    # Get the meaningful words from this article's title
    article_words = get_meaningful_words(article.title)

    if len(article_words) < 2:
        # Title too short to compare meaningfully
        return 0.0

    # Count how many other articles (from different sources) share 3+ words
    overlapping_sources = set()
    for other in all_articles:
        # Don't compare the article to itself
        if other.id == article.id:
            continue
        # Don't count the same source twice (same source re-posting the story)
        if other.source_name == article.source_name:
            continue

        other_words = get_meaningful_words(other.title)
        # Count how many meaningful words the two titles share
        shared_words = article_words.intersection(other_words)

        if len(shared_words) >= 3:
            overlapping_sources.add(other.source_name)

    overlap_count = len(overlapping_sources) + 1  # +1 for this article's own source

    if overlap_count >= 3:
        score = MAX_OVERLAP_SCORE           # 30 points — confirmed big story
    elif overlap_count == 2:
        score = MAX_OVERLAP_SCORE * 0.5     # 15 points — covered by 2 sources
    else:
        score = 0.0                          # 0 points — only one source

    if overlap_count >= 2:
        logger.debug(
            "Source overlap score: %.1f — covered by %d sources",
            score, overlap_count
        )

    return score


def score_article(article: Article, all_articles: list) -> float:
    """
    Calculates the total virality score for a single article.

    Adds up all three signal scores (recency + overlap + keywords)
    and saves the result to the database.

    Args:
        article (Article):     The article to score.
        all_articles (list):   All articles in this batch (used for overlap scoring).

    Returns:
        float: The total virality score (0–80 in Phase 1, 0–100 in Phase 2).
    """
    # Combine title and summary for keyword matching
    article_text = f"{article.title} {article.summary or ''}"

    # Calculate each signal score
    recency_score  = calculate_recency_score(article.published_at)
    keyword_score  = calculate_keyword_score(article_text, article.bot_id)
    overlap_score  = calculate_source_overlap_score(article, all_articles)

    # Phase 2 will add:
    # reddit_score = calculate_reddit_score(article)  # Not yet implemented

    raw_score = recency_score + keyword_score + overlap_score

    # Apply source category weight — official AI sources score higher,
    # community aggregators (Hacker News) score lower.
    weight = _SOURCE_WEIGHT_MAP.get(article.source_name, 1.0)
    total_score = raw_score * weight

    logger.debug(
        "Score for '%s': %.1f total (raw=%.1f × weight=%.1fx, "
        "recency=%.1f, keywords=%.1f, overlap=%.1f) [%s]",
        article.title[:55], total_score, raw_score, weight,
        recency_score, keyword_score, overlap_score, article.source_name
    )

    # Save the score back to the database
    _save_score(article.id, total_score)

    return total_score


def score_and_select(articles: list, posts_needed: int = 1) -> list:
    """
    Scores all articles and selects the top ones for content generation.

    This is the main function called by the pipeline.
    It scores every article, then selects the top N articles
    that meet the virality threshold.

    Args:
        articles (list):     List of Article objects that passed guardrails.
        posts_needed (int):  How many top articles to return.
                             AI bot needs 1, Bollywood bot needs 2 per session.

    Returns:
        list: The top N Article objects sorted by virality score.
              May return fewer than posts_needed if not enough articles pass.
              Returns empty list if no articles are provided.

    Example:
        >>> selected = score_and_select(clean_articles, posts_needed=1)
        >>> for article in selected:
        ...     print(f"Score {article.virality_score}: {article.title}")
    """
    if not articles:
        logger.warning("No articles to score.")
        return []

    logger.info("Scoring %d articles...", len(articles))

    # Score every article and pair it with its score for sorting
    scored = []
    for article in articles:
        score = score_article(article, articles)
        scored.append((score, article))

    # Sort by score — highest first
    scored.sort(key=lambda x: x[0], reverse=True)

    # Log the top 5 scores so you can see what's happening
    logger.info("Top scored articles:")
    for i, (score, article) in enumerate(scored[:5], 1):
        status = "✓ SELECTED" if score >= settings.VIRALITY_THRESHOLD else "  below threshold"
        logger.info(
            "  %d. [%.1f] %s — %s",
            i, score, article.title[:65], status
        )

    # Select articles that meet the threshold, enforcing source diversity:
    # at most 2 articles from the same source in the final selection.
    MAX_PER_SOURCE = 2
    source_counts: dict = {}
    selected = []

    for score, article in scored:
        if score < settings.VIRALITY_THRESHOLD:
            continue
        source = article.source_name
        if source_counts.get(source, 0) >= MAX_PER_SOURCE:
            logger.debug(
                "Source diversity cap: skipping '%s' (already have %d from %s)",
                article.title[:60], MAX_PER_SOURCE, source
            )
            continue
        source_counts[source] = source_counts.get(source, 0) + 1
        selected.append(article)
        if len(selected) >= posts_needed:
            break

    if selected:
        logger.info(
            "%d article(s) selected (threshold=%d, diversity cap=%d per source).",
            len(selected), settings.VIRALITY_THRESHOLD, MAX_PER_SOURCE
        )
        for article in selected:
            _save_article_status(article.id, "selected")
        return selected

    else:
        logger.warning(
            "No articles met the virality threshold (%d). "
            "Fallback scoring will be used.",
            settings.VIRALITY_THRESHOLD
        )
        return []


def _save_score(article_id: int, score: float) -> None:
    """
    Saves a virality score to an article in the database.

    Args:
        article_id (int): The ID of the article to update.
        score (float):    The calculated virality score.
    """
    try:
        with get_session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if article:
                article.virality_score = round(score, 2)
                article.status = "scored"
    except Exception as e:
        logger.error("Failed to save score for article %d: %s", article_id, str(e))


def _save_article_status(article_id: int, status: str) -> None:
    """
    Updates an article's status in the database.

    Args:
        article_id (int): The ID of the article to update.
        status (str):     The new status string, e.g. "selected".
    """
    try:
        with get_session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if article:
                article.status = status
    except Exception as e:
        logger.error("Failed to update status for article %d: %s", article_id, str(e))
