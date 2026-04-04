"""
publisher/review_interface.py
──────────────────────────────
Human-in-the-loop review interface via Telegram bot.

What this file does:
  - Sends every newly generated post to YOU (the reviewer) in a private chat.
  - Shows the post with two inline buttons: ✅ Approve and ❌ Reject.
  - When you tap Approve → post is published to the Telegram channel immediately.
  - When you tap Reject → post is marked rejected, you enter a reason.
  - Also supports text commands for more control.
  - Works for ALL bots from a single reviewer chat — posts are clearly labelled.

How the review flow works:
  1. A post is generated and saved to DB with status 'pending_review'
  2. send_for_review(post) sends it to your private Telegram chat
  3. You see the post preview + Approve / Reject buttons
  4. You tap a button → the bot handles it automatically

Commands available in reviewer chat:
  /pending          → list all posts waiting for your review
  /preview <id>     → show a specific post by its DB ID
  /sources <id>     → show the original article that the post was based on
  /skip <id>        → skip a post (don't publish today, try again tomorrow)
  /reject <id>      → reject with reason (bot will ask you for the reason)

About async in python-telegram-bot v21:
  - All handler functions use 'async def' — this is required by the library.
  - 'await' is used before any Telegram API call (like sending a message).
  - The bot runs in its own event loop managed by Application.run_polling().
  - You don't need to understand async deeply — just follow the pattern shown.
"""

import asyncio
import logging
from datetime import datetime

from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

from config.settings import settings
from db.database import get_session
from db.models import Post, Article, PublishLog
from publisher.telegram_bot import publish_post, _publish_post_async, _to_html

logger = logging.getLogger("publisher.review_interface")

# ── Callback data prefixes ─────────────────────────────────────────────────
# When a button is tapped, Telegram sends back "callback data".
# We use these prefixes to know which button was tapped and for which post.
# e.g. "approve_5" means the Approve button was tapped for post ID 5.
APPROVE_PREFIX = "approve_"
REJECT_PREFIX  = "reject_"
SOURCES_PREFIX = "sources_"

# ── State tracking for multi-step reject flow ──────────────────────────────
# When reviewer taps Reject, we need to ask for a reason.
# This dict tracks which post is awaiting a reject reason from the reviewer.
# Key: reviewer's chat_id, Value: post_id waiting for reject reason
_awaiting_reject_reason: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# SENDING POSTS FOR REVIEW
# ─────────────────────────────────────────────────────────────────────────────

def send_for_review(post: Post) -> bool:
    """
    Sends a generated post to the reviewer's Telegram chat for approval.

    This is called by the scheduler after a post is generated.
    It sends the full post content with Approve / Reject buttons.

    Args:
        post (Post): The Post database object to send for review.
                     Must have status 'pending_review'.

    Returns:
        bool: True if the review message was sent successfully.
    """
    try:
        return asyncio.run(_send_review_message(post))
    except RuntimeError:
        # Already inside an event loop (e.g. called from async context)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_send_review_message(post))


async def _send_review_message(post: Post) -> bool:
    """
    Async implementation of send_for_review.

    Builds the review message with post preview and inline buttons,
    then sends it to the reviewer's private chat.

    Args:
        post (Post): The post to send for review.

    Returns:
        bool: True if sent successfully.
    """
    reviewer_chat_id = settings.TELEGRAM_REVIEWER_CHAT_ID
    if not reviewer_chat_id:
        logger.error("TELEGRAM_REVIEWER_CHAT_ID is not set — cannot send for review.")
        return False

    # ── Build the review message ───────────────────────────────────────────
    # Load the source article to show context to the reviewer
    source_title = "Unknown"
    source_name  = "Unknown"
    with get_session() as session:
        db_post = session.query(Post).filter(Post.id == post.id).first()
        if db_post and db_post.article:
            source_title = db_post.article.title
            source_name  = db_post.article.source_name

    # Format the review notification message
    bot_label = {
        "ai_news":   "🤖 AI News Bot",
        "bollywood": "🎬 Bollywood Buzz Bot",
        "astrology": "🕉️ Astrology Bot",
    }.get(post.bot_id, f"Bot: {post.bot_id}")

    review_header = (
        f"📬 *NEW POST FOR REVIEW*\n"
        f"Bot: {bot_label}\n"
        f"Post ID: `{post.id}`\n"
        f"Source: {source_name}\n"
        f"Article: _{source_title[:80]}_\n"
        f"{'─' * 35}\n\n"
    )

    full_message = _to_html(review_header + post.content)

    # ── Build inline buttons ───────────────────────────────────────────────
    # InlineKeyboardButton creates a clickable button in the chat.
    # callback_data is what gets sent back when the button is tapped.
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"{APPROVE_PREFIX}{post.id}"
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"{REJECT_PREFIX}{post.id}"
            ),
        ],
        [
            InlineKeyboardButton(
                "📰 View Source Article",
                callback_data=f"{SOURCES_PREFIX}{post.id}"
            ),
        ],
    ])

    # ── Send the message ───────────────────────────────────────────────────
    try:
        # Use the AI News bot token to send review messages
        # (any active bot token works for sending to reviewer's private chat)
        token = settings.TELEGRAM_AI_BOT_TOKEN or settings.TELEGRAM_BOLLYWOOD_BOT_TOKEN
        bot   = Bot(token=token)

        if post.image_url:
            # Send image with the review message as caption
            # Telegram caption limit is 1024 chars — truncate if needed
            caption = full_message[:1024] if len(full_message) > 1024 else full_message
            await bot.send_photo(
                chat_id=reviewer_chat_id,
                photo=post.image_url,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            await bot.send_message(
                chat_id=reviewer_chat_id,
                text=full_message,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )

        logger.info(
            "Sent post %d for review to chat %s (bot='%s')",
            post.id, reviewer_chat_id, post.bot_id
        )
        return True

    except TelegramError as e:
        logger.error("Failed to send post %d for review: %s", post.id, str(e))
        return False


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND HANDLERS
# These functions are called when the reviewer types a command in the chat.
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /pending — Lists all posts currently waiting for review.

    Shows post ID, bot name, and first 80 chars of content
    for each post with status 'pending_review'.
    """
    with get_session() as session:
        pending = (
            session.query(Post)
            .filter(Post.status == "pending_review")
            .order_by(Post.created_at.desc())
            .all()
        )
        session.expunge_all()

    if not pending:
        await update.message.reply_text("✅ No posts pending review.")
        return

    lines = [f"📋 *{len(pending)} post(s) pending review:*\n"]
    for p in pending:
        bot_label = p.bot_id.replace("_", " ").title()
        lines.append(
            f"• ID `{p.id}` | {bot_label}\n"
            f"  _{p.content[:80].strip()}..._\n"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML
    )


async def cmd_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /preview <id> — Shows the full content of a specific post.

    Usage: /preview 5
    """
    # context.args contains the arguments after the command
    # e.g. "/preview 5" → context.args = ["5"]
    if not context.args:
        await update.message.reply_text("Usage: /preview <post_id>\nExample: /preview 5")
        return

    try:
        post_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid post ID. Use a number. Example: /preview 5")
        return

    with get_session() as session:
        post = session.query(Post).filter(Post.id == post_id).first()
        if post:
            session.expunge(post)

    if not post:
        await update.message.reply_text(f"Post ID {post_id} not found.")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"{APPROVE_PREFIX}{post.id}"),
            InlineKeyboardButton("❌ Reject",  callback_data=f"{REJECT_PREFIX}{post.id}"),
        ]
    ])

    await update.message.reply_text(
        f"*Post ID {post.id}* | Status: `{post.status}`\n\n{post.content}",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def cmd_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /sources <id> — Shows the original source article for a post.

    Usage: /sources 5
    """
    if not context.args:
        await update.message.reply_text("Usage: /sources <post_id>\nExample: /sources 5")
        return

    try:
        post_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid post ID.")
        return

    with get_session() as session:
        post = session.query(Post).filter(Post.id == post_id).first()
        if post and post.article:
            article = post.article
            msg = (
                f"📰 *Source Article for Post {post_id}*\n\n"
                f"*Title:* {article.title}\n"
                f"*Source:* {article.source_name}\n"
                f"*Published:* {article.published_at}\n"
                f"*Virality Score:* {article.virality_score}\n"
                f"*URL:* {article.url}\n\n"
                f"*Summary:*\n_{article.summary[:300] if article.summary else 'N/A'}_"
            )
        else:
            msg = f"No source article found for post {post_id}."

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /skip <id> — Skips a post (marks as rejected with reason 'skipped by reviewer').

    Usage: /skip 5
    """
    if not context.args:
        await update.message.reply_text("Usage: /skip <post_id>\nExample: /skip 5")
        return

    try:
        post_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid post ID.")
        return

    _reject_post(post_id, reason="Skipped by reviewer")
    await update.message.reply_text(f"⏭️ Post {post_id} skipped.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /help — Shows all available reviewer commands.
    """
    help_text = (
        "🤖 *AI News Bot — Reviewer Commands*\n\n"
        "/pending — List all posts waiting for review\n"
        "/preview `<id>` — Show full post content\n"
        "/sources `<id>` — Show original source article\n"
        "/skip `<id>` — Skip this post (no publish)\n"
        "/help — Show this help message\n\n"
        "_You can also tap the ✅ Approve / ❌ Reject buttons directly on each post._"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────────────────────────────────────
# INLINE BUTTON HANDLERS
# Called when reviewer taps a button (not a text command).
# ─────────────────────────────────────────────────────────────────────────────

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles all inline button taps (Approve, Reject, View Source).

    When a button is tapped, Telegram sends a CallbackQuery with the
    callback_data we set when building the button. We parse the prefix
    to know which action to take.

    Args:
        update:  The Telegram update containing the button tap.
        context: The bot context (not used here directly).
    """
    query    = update.callback_query
    data     = query.data             # e.g. "approve_5" or "reject_5"
    chat_id  = query.message.chat_id

    # Always acknowledge the button tap — removes the loading spinner
    await query.answer()

    # ── Approve button ─────────────────────────────────────────────────────
    if data.startswith(APPROVE_PREFIX):
        post_id = int(data[len(APPROVE_PREFIX):])
        await _handle_approve(query, post_id)

    # ── Reject button ──────────────────────────────────────────────────────
    elif data.startswith(REJECT_PREFIX):
        post_id = int(data[len(REJECT_PREFIX):])
        # Ask the reviewer to type a reason
        _awaiting_reject_reason[chat_id] = post_id
        await query.edit_message_reply_markup(reply_markup=None)  # Remove buttons
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Rejecting post {post_id}.\n\nPlease type the reason for rejection:",
        )

    # ── Sources button ─────────────────────────────────────────────────────
    elif data.startswith(SOURCES_PREFIX):
        post_id = int(data[len(SOURCES_PREFIX):])
        with get_session() as session:
            post = session.query(Post).filter(Post.id == post_id).first()
            if post and post.article:
                article = post.article
                msg = (
                    f"📰 *Source Article*\n\n"
                    f"*Title:* {article.title}\n"
                    f"*Source:* {article.source_name}\n"
                    f"*Score:* {article.virality_score}\n"
                    f"*URL:* {article.url}"
                )
            else:
                msg = "Source article not found."
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML
        )


async def _handle_approve(query, post_id: int) -> None:
    """
    Processes an Approve button tap.

    Sets post status to 'approved', publishes it immediately,
    and updates the button message to show the result.

    Args:
        query:   The callback query from the button tap.
        post_id: The ID of the post to approve.
    """
    # Set status to approved in DB and commit
    with get_session() as session:
        post = session.query(Post).filter(Post.id == post_id).first()
        if not post:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"Post {post_id} not found.")
            return
        if post.status == "published":
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"Post {post_id} was already published.")
            return
        post.status      = "approved"
        post.reviewed_at = datetime.utcnow()
        # No expunge here — let the session commit the status change on exit

    logger.info("Post %d approved by reviewer.", post_id)

    # Remove the inline buttons from the review message
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(f"✅ Post {post_id} approved — publishing now...")

    # Re-fetch after commit so publish_post sees the updated status
    with get_session() as session:
        post = session.query(Post).filter(Post.id == post_id).first()
        if post:
            session.expunge(post)

    # Use the async publish function directly — we're already inside the event loop
    success = await _publish_post_async(post)

    if success:
        await query.message.reply_text(
            f"🚀 Post {post_id} published to @{post.bot_id} channel!"
        )
        logger.info("Post %d published successfully after reviewer approval.", post_id)
    else:
        await query.message.reply_text(
            f"⚠️ Post {post_id} approved but publishing failed. "
            f"Use /preview {post_id} to retry."
        )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles plain text messages from the reviewer.

    This is used to capture reject reasons after the reviewer taps
    the Reject button. If we're not waiting for a reject reason,
    we show a help prompt instead.

    Args:
        update:  The Telegram update containing the text message.
        context: The bot context.
    """
    chat_id = update.message.chat_id
    text    = update.message.text.strip()

    # Check if we're waiting for a reject reason for this reviewer
    if chat_id in _awaiting_reject_reason:
        post_id = _awaiting_reject_reason.pop(chat_id)  # Remove from waiting state
        _reject_post(post_id, reason=text)
        await update.message.reply_text(
            f"❌ Post {post_id} rejected.\nReason: _{text}_",
            parse_mode=ParseMode.HTML
        )
        logger.info("Post %d rejected by reviewer. Reason: %s", post_id, text)
    else:
        # Not a command, not a reject reason — show help
        await update.message.reply_text(
            "Use /help to see available commands.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# DATABASE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _reject_post(post_id: int, reason: str) -> None:
    """
    Marks a post as rejected in the database and logs the action.

    Args:
        post_id (int): The ID of the post to reject.
        reason (str):  The reason for rejection (stored in DB).
    """
    try:
        with get_session() as session:
            post = session.query(Post).filter(Post.id == post_id).first()
            if post:
                post.status       = "rejected"
                post.reviewed_at  = datetime.utcnow()
                post.reject_reason = reason

                log_entry = PublishLog(
                    post_id=post_id,
                    bot_id=post.bot_id,
                    action="rejected",
                    notes=reason,
                    timestamp=datetime.utcnow(),
                )
                session.add(log_entry)

        logger.info("Post %d rejected. Reason: %s", post_id, reason)

    except Exception as e:
        logger.error("Failed to reject post %d: %s", post_id, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# BOT APPLICATION
# ─────────────────────────────────────────────────────────────────────────────

def build_review_bot() -> Application:
    """
    Builds and configures the Telegram bot application for reviewing posts.

    Creates an Application instance with all command and callback handlers
    registered. This is called once from the scheduler/main.py to start
    the review bot.

    Returns:
        Application: A configured python-telegram-bot Application ready to run.
    """
    token = settings.TELEGRAM_AI_BOT_TOKEN or settings.TELEGRAM_BOLLYWOOD_BOT_TOKEN

    if not token:
        raise ValueError("No Telegram bot token found. Check your .env file.")

    # Build the application
    app = Application.builder().token(token).build()

    # Register command handlers
    # Each handler listens for a specific /command from the reviewer
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("preview", cmd_preview))
    app.add_handler(CommandHandler("sources", cmd_sources))
    app.add_handler(CommandHandler("skip",    cmd_skip))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("start",   cmd_help))  # /start shows help too

    # Register inline button handler
    app.add_handler(CallbackQueryHandler(handle_button))

    # Register plain text handler (for reject reasons)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    logger.info("Review bot application built with all handlers registered.")
    return app


def start_review_bot() -> None:
    """
    Starts the review bot and begins polling for messages.

    This runs INDEFINITELY — it blocks the current thread and keeps
    listening for messages from the reviewer.

    In production this will be run in a background thread by the scheduler.
    In development you can run it directly to test the review interface.

    Call this from main.py or run publisher/test_review_bot.py directly.
    """
    logger.info("Starting review bot (polling for messages)...")
    app = build_review_bot()

    # Python 3.10+ requires an explicit event loop.
    # asyncio.run() creates one, runs the bot, and cleans up on exit.
    import asyncio

    async def _run():
        async with app:
            await app.initialize()
            await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            await app.start()
            # Keep running until Ctrl+C
            await asyncio.Event().wait()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("Review bot stopped by user (Ctrl+C).")
