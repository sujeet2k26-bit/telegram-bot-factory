"""
db/database.py
──────────────
Handles the database connection and table creation for the AI News Bot.

What this file does:
  - Creates a connection to the SQLite database file (db/ainews.db).
  - Creates all database tables automatically on first run.
  - Provides a 'get_session' function that other modules use to
    read from and write to the database.

What is SQLite?
  - SQLite is a simple database that stores all data in a single file.
  - It requires no installation or setup — perfect for local development.
  - The database file is created automatically at db/ainews.db when
    the app runs for the first time.
  - In the future, you can switch to PostgreSQL just by changing
    DATABASE_URL in your .env file — no other code changes needed.

How other modules use this file:
  >>> from db.database import get_session
  >>> with get_session() as session:
  ...     articles = session.query(Article).all()
  ...     print(articles)
"""

import logging
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from db.models import Base
from config.settings import settings

logger = logging.getLogger(__name__)


# ── Create the database engine ────────────────────────────────────────────────
# The engine is the connection to the database.
# It reads the DATABASE_URL from settings (default: sqlite:///db/ainews.db).
#
# connect_args={"check_same_thread": False} is required for SQLite when
# multiple parts of the app might access the database at the same time.
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,  # Set to True if you want to see every SQL query in the logs (very verbose)
)

# ── Create a session factory ──────────────────────────────────────────────────
# A session is like a temporary workspace for database operations.
# You open a session, do your reads/writes, then close it.
# SessionLocal is a factory that creates new sessions when called.
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,   # Changes are NOT saved until you call session.commit()
    autoflush=False,    # Changes are NOT sent to DB until you call session.flush() or commit()
)


def init_db() -> None:
    """
    Creates all database tables if they don't already exist.

    Call this ONCE when the application starts (from main.py).
    It is safe to call multiple times — it will not delete existing data
    or recreate tables that already exist.

    What it does:
      - Reads all the table definitions from db/models.py
      - Creates the db/ directory if it doesn't exist
      - Creates the SQLite database file (db/ainews.db)
      - Creates the articles, posts, and publish_log tables

    Returns:
        None
    """
    # Make sure the db/ folder exists before SQLite tries to create the file
    os.makedirs("db", exist_ok=True)

    logger.info("Initialising database at: %s", settings.DATABASE_URL)

    try:
        # This command creates all tables defined in db/models.py
        # checkfirst=True means: skip if the table already exists
        Base.metadata.create_all(bind=engine, checkfirst=True)
        logger.info("Database tables created (or already exist): articles, posts, publish_log")

    except Exception as e:
        logger.error("Failed to initialise database: %s", str(e))
        raise  # Re-raise the error so main.py knows something went wrong

    # ── Run column migrations for existing databases ───────────────────────
    # SQLAlchemy's create_all() only creates new tables — it never modifies
    # existing ones. We add new columns manually via ALTER TABLE.
    # Each ALTER TABLE is wrapped in try/except so it silently skips if the
    # column already exists (SQLite raises "duplicate column name" in that case).
    _run_migrations()


def _run_migrations() -> None:
    """
    Applies incremental column additions to existing database tables.

    SQLAlchemy's create_all() only creates new tables — it never alters
    existing ones to add new columns. This function fills that gap by
    running ALTER TABLE statements for each new column we've added.

    Each statement is safe to run multiple times — SQLite raises an error
    if the column already exists, which we catch and ignore.

    Returns:
        None
    """
    migrations = [
        # Added for A/B headline testing — stores an AI-generated alt headline
        "ALTER TABLE posts ADD COLUMN headline_b TEXT",
    ]

    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
                logger.info("Migration applied: %s", sql)
            except Exception:
                # Column already exists — safe to ignore
                pass


@contextmanager
def get_session() -> Session:
    """
    Provides a database session for reading and writing data.

    This is a 'context manager' — it's designed to be used with Python's
    'with' statement, which automatically handles opening and closing
    the session even if an error occurs.

    Usage example:
      >>> from db.database import get_session
      >>> from db.models import Article
      >>>
      >>> # Fetch all articles for the AI News bot
      >>> with get_session() as session:
      ...     articles = session.query(Article).filter_by(bot_id="ai_news").all()
      ...     for article in articles:
      ...         print(article.title)
      >>>
      >>> # Save a new article
      >>> with get_session() as session:
      ...     new_article = Article(bot_id="ai_news", title="GPT-5 released", url="http://...")
      ...     session.add(new_article)
      ...     # session.commit() is called automatically when the 'with' block ends

    Yields:
        Session: A SQLAlchemy session object for database operations.

    Raises:
        Exception: Any database error is logged, the session is rolled back,
                   and the error is re-raised for the caller to handle.
    """
    session = SessionLocal()
    try:
        yield session          # Give the session to the calling code
        session.commit()       # Save all changes if no errors occurred
    except Exception as e:
        session.rollback()     # Undo all changes if something went wrong
        logger.error("Database session error — changes rolled back: %s", str(e))
        raise
    finally:
        session.close()        # Always close the session when done


def check_db_health() -> bool:
    """
    Checks that the database is reachable and working correctly.

    Runs a simple 'SELECT 1' query — the database equivalent of a ping.
    Call this at startup to catch connection problems early.

    Returns:
        bool: True if the database is healthy, False if there is a problem.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database health check passed.")
        return True
    except Exception as e:
        logger.error("Database health check failed: %s", str(e))
        return False
