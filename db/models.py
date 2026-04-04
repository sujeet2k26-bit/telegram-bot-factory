"""
db/models.py
────────────
Defines the database tables for the AI News Bot.

What this file does:
  - Describes the structure of 3 database tables using SQLAlchemy.
  - SQLAlchemy lets us work with the database using Python objects
    instead of writing raw SQL queries (like SELECT * FROM articles).

Think of each class here as one table in the database:
  - Article   → stores every raw news article fetched from RSS feeds
  - Post      → stores every AI-generated post (before and after review)
  - PublishLog → permanent record of every publish/reject action

How SQLAlchemy works (simple explanation):
  - Instead of writing SQL like:
      INSERT INTO articles (title, url) VALUES ('AI news', 'http://...')
  - You write Python like:
      article = Article(title='AI news', url='http://...')
      session.add(article)
      session.commit()
  - SQLAlchemy converts that Python into SQL automatically.
"""

from datetime import datetime
from sqlalchemy import (
    Column,        # Defines a column in a table
    Integer,       # Whole number column type
    String,        # Text column type
    Float,         # Decimal number column type
    DateTime,      # Date + time column type
    Text,          # Long text column type (for article summaries, post content)
    ForeignKey,    # Links one table to another
)
from sqlalchemy.orm import declarative_base, relationship

# Base is the parent class all our table models inherit from.
# SQLAlchemy uses it to keep track of all tables in the database.
Base = declarative_base()


# ─────────────────────────────────────────────────────────────────────────────
# TABLE 1: articles
# Stores every raw news article fetched from RSS feeds.
# One row = one article from one source.
# ─────────────────────────────────────────────────────────────────────────────
class Article(Base):
    """
    Represents one news article fetched from an RSS feed.

    Lifecycle of an article:
      1. Fetched from RSS → status = 'new'
      2. Passes guardrail check + gets virality score → status = 'scored'
      3. Selected as top story for the day → status = 'selected'
      4. Not selected (too low score) → status = 'skipped'
      5. Blocked by guardrails → status = 'blocked'
    """

    # The name of the database table this class maps to
    __tablename__ = "articles"

    # ── Primary Key ───────────────────────────────────────────────────────
    # Every table needs a unique ID column. SQLAlchemy auto-increments this.
    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Which bot this article belongs to ─────────────────────────────────
    # e.g. "ai_news" or "bollywood" — matches the 'id' field in bots.json
    bot_id = Column(String(50), nullable=False, index=True)

    # ── Article content ───────────────────────────────────────────────────
    title = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False, unique=True)  # unique=True prevents duplicates
    source_name = Column(String(100), nullable=False)        # e.g. "TechCrunch"
    summary = Column(Text, nullable=True)                    # Short description from RSS feed

    # ── Timestamps ────────────────────────────────────────────────────────
    # When the original article was published on the source website
    published_at = Column(DateTime, nullable=True)
    # When our app fetched this article
    fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # ── Scoring ───────────────────────────────────────────────────────────
    # Virality score calculated by scoring/virality.py (0–100)
    # NULL means not yet scored
    virality_score = Column(Float, nullable=True)

    # ── Status ────────────────────────────────────────────────────────────
    # Tracks where this article is in the pipeline
    # Values: 'new' | 'scored' | 'selected' | 'skipped' | 'blocked'
    status = Column(String(20), default="new", nullable=False, index=True)

    # ── Guardrail info ────────────────────────────────────────────────────
    # If the article was blocked, this stores the reason (e.g. "hate_speech")
    blocked_reason = Column(String(200), nullable=True)

    # ── Relationship ──────────────────────────────────────────────────────
    # This tells SQLAlchemy that one Article can have many Posts.
    # You can access article.posts to get all posts generated from this article.
    posts = relationship("Post", back_populates="article")

    def __repr__(self):
        """Shows a readable summary when you print an Article object."""
        return f"<Article id={self.id} bot='{self.bot_id}' status='{self.status}' title='{self.title[:50]}...'>"


# ─────────────────────────────────────────────────────────────────────────────
# TABLE 2: posts
# Stores every AI-generated post, from creation through review to publish.
# One row = one generated post waiting for review or already published.
# ─────────────────────────────────────────────────────────────────────────────
class Post(Base):
    """
    Represents one AI-generated Telegram post.

    Lifecycle of a post:
      1. Generated by Claude → status = 'pending_review'
      2. Sent to reviewer in Telegram → status = 'pending_review'
      3. Reviewer approves → status = 'approved'
      4. Published to Telegram channel → status = 'published'
      5. Reviewer rejects → status = 'rejected'
    """

    __tablename__ = "posts"

    # ── Primary Key ───────────────────────────────────────────────────────
    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Links to the source article ───────────────────────────────────────
    # ForeignKey means this column must match an 'id' value in the articles table.
    # If you delete an article, its posts are also deleted (ondelete="CASCADE").
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False)

    # ── Which bot will publish this post ──────────────────────────────────
    bot_id = Column(String(50), nullable=False, index=True)

    # ── Generated content ─────────────────────────────────────────────────
    # The full post text as generated by Gemini (English or Hindi/Hinglish)
    content = Column(Text, nullable=False)

    # URL of the cover image generated by Gemini image model
    # NULL if image generation failed or wasn't attempted
    image_url = Column(String(1000), nullable=True)

    # ── Status ────────────────────────────────────────────────────────────
    # Values: 'pending_review' | 'approved' | 'rejected' | 'published'
    status = Column(String(20), default="pending_review", nullable=False, index=True)

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)   # Set when reviewer acts on it
    published_at = Column(DateTime, nullable=True)  # Set when post goes live

    # ── Review info ───────────────────────────────────────────────────────
    # If the reviewer rejects the post, their reason is stored here
    reject_reason = Column(String(500), nullable=True)

    # ── A/B Headline Testing ──────────────────────────────────────────────
    # An AI-generated alternative headline for the first story.
    # Shown in the review message as "Option B".
    # Cleared once the reviewer uses it or edits the post.
    headline_b = Column(Text, nullable=True)

    # ── Relationship ──────────────────────────────────────────────────────
    # Links back to the parent Article object
    article = relationship("Article", back_populates="posts")

    # Links to all publish log entries for this post
    publish_logs = relationship("PublishLog", back_populates="post")

    def __repr__(self):
        """Shows a readable summary when you print a Post object."""
        return f"<Post id={self.id} bot='{self.bot_id}' status='{self.status}'>"


# ─────────────────────────────────────────────────────────────────────────────
# TABLE 3: publish_log
# Permanent record of every action taken on a post (published, rejected, skipped).
# Used for auditing and future analytics.
# ─────────────────────────────────────────────────────────────────────────────
class PublishLog(Base):
    """
    Records every publish, rejection, or skip event.

    Why keep a separate log table?
      - The posts table only keeps the CURRENT status of a post.
      - This table keeps a FULL HISTORY of every action ever taken.
      - Useful for analytics: how many posts published per day? Per bot?
        How many were rejected and why?
    """

    __tablename__ = "publish_log"

    # ── Primary Key ───────────────────────────────────────────────────────
    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Which post this log entry is for ──────────────────────────────────
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)

    # ── Which bot performed the action ────────────────────────────────────
    bot_id = Column(String(50), nullable=False, index=True)

    # ── Which Telegram channel was published to ───────────────────────────
    # e.g. "@AINewsDaily" or "-100xxxxxxxxxx"
    channel_id = Column(String(100), nullable=True)

    # ── What action was taken ─────────────────────────────────────────────
    # Values: 'published' | 'rejected' | 'skipped'
    action = Column(String(20), nullable=False)

    # ── Optional notes ────────────────────────────────────────────────────
    # For rejections: the reason. For skips: why it was skipped.
    notes = Column(String(500), nullable=True)

    # ── When the action happened ──────────────────────────────────────────
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # ── Relationship ──────────────────────────────────────────────────────
    post = relationship("Post", back_populates="publish_logs")

    def __repr__(self):
        """Shows a readable summary when you print a PublishLog object."""
        return f"<PublishLog id={self.id} post_id={self.post_id} action='{self.action}' at={self.timestamp}>"
