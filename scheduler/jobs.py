"""
scheduler/jobs.py
─────────────────
The brain of the AI News Bot — schedules and runs all pipeline jobs.

What this file does:
  - Reads active bots from config/bots.json on startup.
  - For each bot, registers APScheduler jobs based on its schedule_times.
  - Also runs the Telegram review bot in a background thread so the reviewer
    can tap Approve / Reject buttons at any time.
  - Manages the full 3-step pipeline for each bot:
      Step A (Fetch):   Fetches fresh RSS articles and saves them to the DB.
      Step B (Review):  Picks the best article, generates a post, sends to reviewer.
      Step C (Publish): Publishes any posts that the reviewer has approved.

Schedule (from CLAUDE.md):
  06:00 AM  →  Fetch + Save (all active bots)
  07:00 AM  →  Generate + Send for Review (all active bots)
  08:00 AM  →  Publish approved posts (all active bots)
  12:00 PM  →  Fetch + Save again (Bollywood bot only) + retry morning posts
  06:00 PM  →  Generate + Send for Review (Bollywood bot only)
  07:00 PM  →  Publish approved evening posts (Bollywood bot only)

How APScheduler works (simple explanation):
  - APScheduler is a Python library that runs functions at specific times.
  - We use BackgroundScheduler — it runs in a background thread so it doesn't
    block the review bot from listening for Telegram messages.
  - CronTrigger lets us say "run this at 06:00 AM every day".
  - Each job gets a unique job_id so APScheduler can track it.

How to read this file:
  1. start_scheduler(active_bots) — call this from main.py to start everything.
  2. It registers all the jobs and starts the scheduler.
  3. The scheduler then calls the job functions at the right times.
  4. Each job function runs the pipeline for the bots it is responsible for.
"""

import json
import logging
import threading
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from aggregator.rss_fetcher import fetch_articles_for_bot
from aggregator.dedup import filter_and_save_articles
from scoring.fallback import get_best_articles_for_bot
from generator.claude_client import generate_and_save_post, generate_digest_post
from publisher.review_interface import send_for_review, build_review_bot
from publisher.telegram_bot import publish_post
from db.database import get_session
from db.models import Post

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE STEP A — Fetch & Save
# ─────────────────────────────────────────────────────────────────────────────

def job_fetch_and_save(bot_configs: list) -> None:
    """
    Pipeline Step A: Fetches fresh articles from RSS feeds and saves them to the DB.

    This job runs BEFORE the generate job — it fills the database with
    fresh articles so the generate job has good content to work with.

    For each bot:
      1. Fetch raw articles from all its RSS feed sources.
      2. Filter out duplicates and articles that are too old (dedup).
      3. Save only the new, fresh articles to the database with status 'new'.

    Note: Guardrail checks and scoring happen in the generate step (Step B),
    not here. This step just pulls in raw content.

    Args:
        bot_configs (list): List of bot config dicts (from bots.json).
                            Each entry has: id, name, sources_file, etc.
    """
    logger.info(
        "=== JOB: Fetch & Save started for %d bot(s) ===",
        len(bot_configs)
    )

    for bot_config in bot_configs:
        bot_id = bot_config["id"]
        try:
            logger.info("Fetching articles for bot '%s'...", bot_id)

            # Fetch raw articles from all RSS sources defined for this bot
            raw_articles = fetch_articles_for_bot(bot_config)

            if not raw_articles:
                logger.warning(
                    "No articles fetched from RSS for bot '%s'. "
                    "Check your sources file or network connection.",
                    bot_id
                )
                continue

            logger.info(
                "Fetched %d raw articles for bot '%s'.",
                len(raw_articles), bot_id
            )

            # Filter out old/duplicate articles and save fresh ones to DB
            # filter_and_save_articles handles both dedup + age checks
            new_articles = filter_and_save_articles(raw_articles)

            logger.info(
                "Saved %d new article(s) to DB for bot '%s'.",
                len(new_articles), bot_id
            )

        except Exception as e:
            # Log the error but continue with other bots — one failure shouldn't stop others
            logger.error(
                "Fetch & Save failed for bot '%s': %s",
                bot_id, str(e), exc_info=True
            )

    logger.info("=== JOB: Fetch & Save complete ===")


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE STEP B — Generate & Send for Review
# ─────────────────────────────────────────────────────────────────────────────

def job_generate_and_review(bot_configs: list) -> None:
    """
    Pipeline Step B: Selects the best article, generates a post, sends to reviewer.

    This is the most important job — it runs the AI content generation
    and sends the result to you (the reviewer) on Telegram.

    For each bot:
      1. Get the best available article (virality scoring → fallback if needed).
         This internally runs guardrail checks and scoring.
      2. Generate the post text using Gemini 2.5 Pro.
      3. Generate a cover image using Gemini image model (optional).
      4. Save the post to the DB with status 'pending_review'.
      5. Send the post to the reviewer's Telegram chat with Approve / Reject buttons.

    If this is the Bollywood bot's second daily post, the selection logic
    automatically picks a DIFFERENT article than the morning one (because
    the morning article is already marked as 'selected' in the DB).

    Args:
        bot_configs (list): List of bot config dicts for bots to generate posts for.
    """
    logger.info(
        "=== JOB: Generate & Review started for %d bot(s) ===",
        len(bot_configs)
    )

    for bot_config in bot_configs:
        bot_id = bot_config["id"]
        try:
            logger.info("Running generate + review for bot '%s'...", bot_id)

            # ── How many articles to select? ───────────────────────────────
            # digest_count > 1 means this bot publishes a multi-story digest.
            # e.g. AI News: digest_count=5 → one post covering top 5 stories.
            # Bollywood: no digest_count → single story per post.
            digest_count = bot_config.get("digest_count", 1)

            # ── Select the best articles ───────────────────────────────────
            # get_best_articles_for_bot handles:
            #   - Guardrail pre-check on all 'new' articles in DB
            #   - Virality scoring → tries to pick viral articles
            #   - Fallback → if nothing is viral, picks the most recent articles
            articles, used_fallback = get_best_articles_for_bot(
                bot_id, posts_needed=digest_count
            )

            if not articles:
                logger.warning(
                    "No suitable articles found for bot '%s'. "
                    "No post will be generated this session.",
                    bot_id
                )
                continue

            logger.info(
                "Selected %d article(s) for bot '%s' (fallback=%s):",
                len(articles), bot_id, used_fallback
            )
            for i, a in enumerate(articles, 1):
                logger.info(
                    "  %d. [score=%.1f] %s", i, a.virality_score or 0, a.title[:70]
                )

            # ── Generate post ──────────────────────────────────────────────
            if digest_count > 1 and len(articles) > 1:
                # Digest mode: one post covering all selected articles
                logger.info(
                    "Digest mode: generating one post for %d articles.", len(articles)
                )
                post = generate_digest_post(articles, bot_id)
            else:
                # Single-story mode: one post for the top article
                post = generate_and_save_post(articles[0], bot_id)

            if not post:
                logger.error(
                    "Post generation failed for bot '%s', article_id=%d. "
                    "This may be a guardrail block or an API error.",
                    bot_id, article.id
                )
                continue

            logger.info(
                "Post generated successfully | post_id=%d | bot='%s'",
                post.id, bot_id
            )

            # ── Send to reviewer ───────────────────────────────────────────
            # Sends the post to your private Telegram chat with Approve / Reject buttons.
            # The reviewer bot (running in background) handles button taps.
            sent = send_for_review(post)

            if sent:
                logger.info(
                    "Post %d sent to reviewer for bot '%s'.",
                    post.id, bot_id
                )
            else:
                logger.error(
                    "Failed to send post %d to reviewer for bot '%s'. "
                    "Check TELEGRAM_REVIEWER_CHAT_ID in .env",
                    post.id, bot_id
                )

        except Exception as e:
            logger.error(
                "Generate & Review failed for bot '%s': %s",
                bot_id, str(e), exc_info=True
            )

    logger.info("=== JOB: Generate & Review complete ===")


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE STEP C — Publish Approved Posts
# ─────────────────────────────────────────────────────────────────────────────

def job_publish_approved(bot_configs: list) -> None:
    """
    Pipeline Step C: Publishes any posts that the reviewer has approved.

    This job runs 1 hour after the generate job. By that time, the reviewer
    should have tapped the Approve button. Any approved post gets published
    to the Telegram channel immediately.

    What happens if the reviewer hasn't responded?
      - Posts still in 'pending_review' status are left alone.
      - The 12 PM midday job retries sending them for review.
      - The reviewer can always use /pending to see what's waiting.

    Args:
        bot_configs (list): List of bot config dicts.
    """
    logger.info(
        "=== JOB: Publish Approved Posts started for %d bot(s) ===",
        len(bot_configs)
    )

    for bot_config in bot_configs:
        bot_id = bot_config["id"]
        try:
            _publish_approved_for_bot(bot_id)
        except Exception as e:
            logger.error(
                "Publish job failed for bot '%s': %s",
                bot_id, str(e), exc_info=True
            )

    logger.info("=== JOB: Publish Approved Posts complete ===")


def _publish_approved_for_bot(bot_id: str) -> None:
    """
    Finds all approved-but-not-yet-published posts for a bot and publishes them.

    Looks in the DB for posts with:
      - status = 'approved'   (reviewer approved it)
      - published_at = None   (not yet sent to Telegram)
      - bot_id matches this bot

    Args:
        bot_id (str): The bot ID to publish posts for.
    """
    # Find posts that are approved but not yet published
    with get_session() as session:
        approved_posts = (
            session.query(Post)
            .filter(
                Post.bot_id == bot_id,
                Post.status == "approved",
                Post.published_at == None,  # noqa: E711 — SQLAlchemy requires == None
            )
            .all()
        )
        # Detach from session so we can use the objects after session closes
        session.expunge_all()

    if not approved_posts:
        logger.info("No approved posts to publish for bot '%s'.", bot_id)
        return

    logger.info(
        "Found %d approved post(s) to publish for bot '%s'.",
        len(approved_posts), bot_id
    )

    for post in approved_posts:
        success = publish_post(post)
        if success:
            logger.info(
                "POST PUBLISHED | bot='%s' | post_id=%d",
                bot_id, post.id
            )
        else:
            logger.error(
                "PUBLISH FAILED | bot='%s' | post_id=%d — will retry next cycle.",
                bot_id, post.id
            )


# ─────────────────────────────────────────────────────────────────────────────
# RETRY JOB — Resend posts that haven't been reviewed yet
# ─────────────────────────────────────────────────────────────────────────────

def job_retry_pending(bot_configs: list) -> None:
    """
    Resends posts that are still waiting for review after the first attempt.

    This job runs at 12:00 PM (midday). If a post was sent for review at 7 AM
    but the reviewer hasn't responded by noon, we send a reminder.

    This also runs after the midday Bollywood fetch so the reviewer sees
    both the morning reminder (if any) and the new afternoon post.

    Args:
        bot_configs (list): List of bot config dicts.
    """
    logger.info("=== JOB: Retry Pending Reviews started ===")

    for bot_config in bot_configs:
        bot_id = bot_config["id"]
        try:
            _retry_pending_for_bot(bot_id)
        except Exception as e:
            logger.error(
                "Retry job failed for bot '%s': %s",
                bot_id, str(e), exc_info=True
            )

    logger.info("=== JOB: Retry Pending Reviews complete ===")


def _retry_pending_for_bot(bot_id: str) -> None:
    """
    Finds and resends review messages for posts still pending approval.

    A post is considered 'stuck' if:
      - Its status is 'pending_review'
      - It was created more than 1 hour ago (reviewer had enough time)

    Args:
        bot_id (str): The bot ID to check for stuck pending posts.
    """
    # Consider a post "stuck" if it's been pending for more than 1 hour
    cutoff_time = datetime.utcnow() - timedelta(hours=1)

    with get_session() as session:
        pending_posts = (
            session.query(Post)
            .filter(
                Post.bot_id == bot_id,
                Post.status == "pending_review",
                Post.created_at < cutoff_time,
            )
            .all()
        )
        session.expunge_all()

    if not pending_posts:
        logger.info(
            "No stuck pending posts found for bot '%s'.", bot_id
        )
        return

    logger.info(
        "Found %d stuck pending post(s) for bot '%s' — resending for review.",
        len(pending_posts), bot_id
    )

    for post in pending_posts:
        logger.info(
            "Retrying review for post_id=%d (created at %s)",
            post.id,
            post.created_at.strftime("%Y-%m-%d %H:%M UTC")
        )
        sent = send_for_review(post)
        if not sent:
            logger.error(
                "Failed to resend review for post_id=%d | bot='%s'",
                post.id, bot_id
            )


# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULER SETUP
# ─────────────────────────────────────────────────────────────────────────────

def _get_bot_by_id(active_bots: list, bot_id: str) -> dict | None:
    """
    Finds a bot config by its ID from the active bots list.

    Args:
        active_bots (list): List of all active bot config dicts.
        bot_id (str):       The bot ID to find (e.g. "bollywood").

    Returns:
        dict: The bot config dict if found, None otherwise.
    """
    for bot in active_bots:
        if bot["id"] == bot_id:
            return bot
    return None


def build_scheduler(active_bots: list) -> BackgroundScheduler:
    """
    Creates and configures the APScheduler with all pipeline jobs.

    Reads the schedule from the CLAUDE.md design:
      - 06:00 AM: Fetch & Save (all active bots)
      - 07:00 AM: Generate & Review (all active bots)
      - 08:00 AM: Publish Approved (all active bots)
      - 12:00 PM: Fetch & Save (Bollywood only) + Retry pending (all bots)
      - 06:00 PM: Generate & Review (Bollywood only)
      - 07:00 PM: Publish Approved (Bollywood only)

    The Bollywood bot is the only bot that has an evening session.
    Any bot with a second schedule_time (like ["07:00", "18:00"]) will be
    included in the evening jobs. Bots with only ["07:00"] are morning-only.

    Args:
        active_bots (list): List of active bot config dicts from bots.json.

    Returns:
        BackgroundScheduler: A configured scheduler, not yet started.
    """
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    # Separate bots by their schedule:
    # Morning-only bots: schedule_times has only one entry (e.g. ["07:00"])
    # Full-day bots: schedule_times has two entries (e.g. ["07:00", "18:00"])
    morning_bots  = active_bots   # All active bots run in the morning
    full_day_bots = [
        bot for bot in active_bots
        if len(bot.get("schedule_times", [])) >= 2
    ]

    logger.info(
        "Setting up schedule for %d morning bot(s) and %d full-day bot(s).",
        len(morning_bots), len(full_day_bots)
    )

    # ── MORNING BATCH ──────────────────────────────────────────────────────

    # 06:00 AM — Fetch & Save (all bots)
    scheduler.add_job(
        func=job_fetch_and_save,
        trigger=CronTrigger(hour=6, minute=0),
        args=[morning_bots],
        id="morning_fetch",
        name="Morning Fetch & Save (all bots)",
        replace_existing=True,
        max_instances=1,  # Prevent overlapping runs
    )
    logger.info("Registered: 06:00 AM — Fetch & Save for %d bot(s)", len(morning_bots))

    # 07:00 AM — Generate & Review (all bots)
    scheduler.add_job(
        func=job_generate_and_review,
        trigger=CronTrigger(hour=7, minute=0),
        args=[morning_bots],
        id="morning_review",
        name="Morning Generate & Review (all bots)",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Registered: 07:00 AM — Generate & Review for %d bot(s)", len(morning_bots))

    # 08:00 AM — Publish Approved (all bots)
    scheduler.add_job(
        func=job_publish_approved,
        trigger=CronTrigger(hour=8, minute=0),
        args=[morning_bots],
        id="morning_publish",
        name="Morning Publish Approved (all bots)",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Registered: 08:00 AM — Publish Approved for %d bot(s)", len(morning_bots))

    # ── MIDDAY BATCH (Bollywood only + retry) ─────────────────────────────

    if full_day_bots:
        # 12:00 PM — Fetch & Save (full-day bots only) + retry all pending
        scheduler.add_job(
            func=_midday_batch,
            trigger=CronTrigger(hour=12, minute=0),
            args=[morning_bots, full_day_bots],
            id="midday_batch",
            name="Midday Fetch + Retry (Bollywood + all bots)",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Registered: 12:00 PM — Midday Fetch for %d bot(s) + retry",
            len(full_day_bots)
        )

        # 06:00 PM — Generate & Review (full-day bots only)
        scheduler.add_job(
            func=job_generate_and_review,
            trigger=CronTrigger(hour=18, minute=0),
            args=[full_day_bots],
            id="evening_review",
            name="Evening Generate & Review (Bollywood only)",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Registered: 06:00 PM — Generate & Review for %d bot(s)",
            len(full_day_bots)
        )

        # 07:00 PM — Publish Approved (full-day bots only)
        scheduler.add_job(
            func=job_publish_approved,
            trigger=CronTrigger(hour=19, minute=0),
            args=[full_day_bots],
            id="evening_publish",
            name="Evening Publish Approved (Bollywood only)",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Registered: 07:00 PM — Publish Approved for %d bot(s)",
            len(full_day_bots)
        )

    return scheduler


def _midday_batch(all_bots: list, full_day_bots: list) -> None:
    """
    Runs the 12:00 PM midday batch:
      1. Retry any morning posts still pending review (all bots).
      2. Fetch & Save fresh articles for full-day bots (e.g. Bollywood).

    This is a combined job so both tasks run in one scheduled slot.

    Args:
        all_bots (list):       All active bot configs (for retry logic).
        full_day_bots (list):  Bots with an evening session (for afternoon fetch).
    """
    logger.info("=== JOB: Midday Batch started ===")

    # Step 1: Retry any morning posts the reviewer hasn't acted on yet
    job_retry_pending(all_bots)

    # Step 2: Fetch fresh articles for Bollywood (for the evening session)
    job_fetch_and_save(full_day_bots)

    logger.info("=== JOB: Midday Batch complete ===")


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW BOT (runs in background thread)
# ─────────────────────────────────────────────────────────────────────────────

def start_review_bot_thread() -> threading.Thread:
    """
    Starts Telegram review bots for all configured bots in separate threads.

    Starts one review bot per bot_id so that each bot's reviewer can receive
    Approve / Reject callbacks, /generate, and /card commands independently.
    Active bots (ai_news, bollywood) AND inactive bots with a valid token
    (e.g. astrology) all get a review thread so on-demand commands work.

    Returns:
        threading.Thread: The first started background thread (ai_news).
    """
    from publisher.review_interface import start_review_bot
    from config.settings import settings

    # Map bot_id → env var name that holds its token
    # Add an entry here whenever a new bot is added
    bot_token_map = {
        "ai_news":   settings.TELEGRAM_AI_BOT_TOKEN,
        "bollywood": settings.TELEGRAM_BOLLYWOOD_BOT_TOKEN,
        "astrology": settings.TELEGRAM_ASTROLOGY_BOT_TOKEN,
    }

    first_thread = None
    for bot_id, token in bot_token_map.items():
        if not token:
            logger.debug("Skipping review bot for '%s' — no token configured.", bot_id)
            continue

        def run_review_bot(bid=bot_id):
            """Target function for the background thread."""
            logger.info("Review bot thread starting for bot_id='%s'...", bid)
            try:
                start_review_bot(bid)
            except Exception as e:
                logger.error(
                    "Review bot thread crashed (bot_id='%s'): %s", bid, str(e), exc_info=True
                )

        thread = threading.Thread(
            target=run_review_bot,
            name=f"ReviewBotThread-{bot_id}",
            daemon=True,
        )
        thread.start()
        logger.info("Review bot started for bot_id='%s'.", bot_id)

        if first_thread is None:
            first_thread = thread

    return first_thread


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def start_scheduler(active_bots: list) -> BackgroundScheduler:
    """
    Starts the full scheduling system for the AI News Bot.

    This is the only function you need to call from main.py.
    It does three things:
      1. Starts the Telegram review bot in a background thread
         (so the reviewer can tap Approve / Reject at any time).
      2. Builds the APScheduler with all pipeline jobs registered.
      3. Starts the scheduler (jobs begin running at their scheduled times).

    How to call from main.py:
        from scheduler.jobs import start_scheduler
        scheduler = start_scheduler(active_bots)
        # The scheduler runs in the background from this point on.
        # Keep the main thread alive with a loop to let it keep running.

    Args:
        active_bots (list): List of active bot config dicts from bots.json.
                            Only bots with 'active': true should be passed here.

    Returns:
        BackgroundScheduler: The running scheduler instance.
                             You can call scheduler.shutdown() to stop it cleanly.
    """
    if not active_bots:
        raise ValueError("No active bots provided — cannot start scheduler.")

    logger.info(
        "Starting AI News Bot scheduler for %d active bot(s): %s",
        len(active_bots),
        [bot["name"] for bot in active_bots]
    )

    # ── Step 1: Start the review bot in a background thread ────────────────
    # This must start BEFORE the scheduler so the reviewer can respond
    # to any review messages that were sent before the app restarted.
    logger.info("Starting Telegram review bot in background thread...")
    review_thread = start_review_bot_thread()

    # Brief pause to let the review bot initialise before we start sending messages
    import time
    time.sleep(2)

    if not review_thread.is_alive():
        logger.warning(
            "Review bot thread may not have started correctly. "
            "Check your Telegram bot token in .env"
        )

    # ── Step 2: Build the scheduler with all jobs ─────────────────────────
    logger.info("Building job schedule...")
    scheduler = build_scheduler(active_bots)

    # ── Step 3: Start the scheduler ───────────────────────────────────────
    scheduler.start()
    logger.info("Scheduler started. Jobs registered:")

    # Print a summary of all registered jobs
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        next_run_str = next_run.strftime("%Y-%m-%d %H:%M %Z") if next_run else "N/A"
        logger.info(
            "  %-45s | Next run: %s",
            job.name, next_run_str
        )

    logger.info("All systems running. Press Ctrl+C to stop.")
    return scheduler


def list_scheduled_jobs(scheduler: BackgroundScheduler) -> None:
    """
    Logs a summary of all currently scheduled jobs and their next run times.

    Call this any time to see the current state of the scheduler.

    Args:
        scheduler (BackgroundScheduler): The running scheduler instance.
    """
    jobs = scheduler.get_jobs()
    if not jobs:
        logger.info("No jobs currently scheduled.")
        return

    logger.info("Currently scheduled jobs (%d total):", len(jobs))
    for job in jobs:
        next_run = job.next_run_time
        next_run_str = next_run.strftime("%Y-%m-%d %H:%M %Z") if next_run else "Not scheduled"
        logger.info("  • %s → next run at %s", job.name, next_run_str)
