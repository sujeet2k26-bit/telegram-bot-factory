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


def _get_bot_token(bot_id: str) -> str:
    """
    Returns the Telegram bot token for the given bot_id.

    Each bot uses its own token for both sending review messages and
    polling for approve/reject callbacks. This ensures that tapping
    Approve on a Bollywood post triggers the Bollywood bot, not the
    AI News bot.

    Args:
        bot_id (str): The bot ID, e.g. "ai_news" or "bollywood".

    Returns:
        str: The bot token string from settings.
    """
    token_map = {
        "ai_news":   settings.TELEGRAM_AI_BOT_TOKEN,
        "bollywood": settings.TELEGRAM_BOLLYWOOD_BOT_TOKEN,
        "astrology": settings.TELEGRAM_ASTROLOGY_BOT_TOKEN,
    }
    token = token_map.get(bot_id) or settings.TELEGRAM_AI_BOT_TOKEN
    if not token:
        raise ValueError(f"No Telegram token found for bot_id='{bot_id}'. Check your .env file.")
    return token


def _get_channel_id(bot_id: str) -> str:
    """
    Returns the Telegram channel ID for the given bot_id.

    Used when publishing content directly to the channel (e.g. image cards).

    Args:
        bot_id (str): The bot ID, e.g. "ai_news", "bollywood", or "astrology".

    Returns:
        str: The channel ID string (e.g. "@astrochhayah").
    """
    channel_map = {
        "ai_news":   settings.TELEGRAM_AI_CHANNEL_ID,
        "bollywood": settings.TELEGRAM_BOLLYWOOD_CHANNEL_ID,
        "astrology": settings.TELEGRAM_ASTROLOGY_CHANNEL_ID,
    }
    channel_id = channel_map.get(bot_id)
    if not channel_id:
        raise ValueError(f"No channel ID found for bot_id='{bot_id}'. Check your .env file.")
    return channel_id


def _get_reviewer_chat_id(bot_id: str) -> str:
    """
    Returns the reviewer Telegram chat ID for the given bot_id.

    Each bot can optionally send review messages to a different reviewer account.
    If no bot-specific chat ID is set, falls back to the default TELEGRAM_REVIEWER_CHAT_ID.

    Args:
        bot_id (str): The bot ID, e.g. "ai_news", "bollywood", or "astrology".

    Returns:
        str: The reviewer chat ID string.
    """
    chat_id_map = {
        "astrology": settings.TELEGRAM_ASTROLOGY_REVIEWER_CHAT_ID,
    }
    # Use bot-specific chat ID if set, otherwise fall back to the default
    return chat_id_map.get(bot_id) or settings.TELEGRAM_REVIEWER_CHAT_ID


# ── Callback data prefixes ─────────────────────────────────────────────────
# When a button is tapped, Telegram sends back "callback data".
# We use these prefixes to know which button was tapped and for which post.
# e.g. "approve_5" means the Approve button was tapped for post ID 5.
APPROVE_PREFIX      = "approve_"
REJECT_PREFIX       = "reject_"
SOURCES_PREFIX      = "sources_"
USE_HEADLINE_B_PREFIX = "use_b_"   # Swap in the alternative headline (A/B test)

# ── State tracking for multi-step flows ───────────────────────────────────
# When reviewer taps Reject, we need to ask for a reason.
# Key: reviewer's chat_id, Value: post_id waiting for reject reason
_awaiting_reject_reason: dict = {}

# When reviewer types /edit, we need to wait for their edit instruction.
# Key: reviewer's chat_id, Value: post_id to be edited
_awaiting_edit_instruction: dict = {}


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


async def _send_review_message(
    post: Post,
    override_bot=None,
    override_chat_id=None,
) -> bool:
    """
    Async implementation of send_for_review.

    Builds the review message with post preview and inline buttons,
    then sends it to the reviewer's private chat.

    Args:
        post (Post):          The post to send for review.
        override_bot:         Optional Bot instance to use instead of the post's own bot token.
                              Pass context.bot from cmd_generate so the message goes through
                              the bot the reviewer is already talking to (avoids 403 errors
                              when reviewing cross-bot posts from a single reviewer chat).
        override_chat_id:     Optional chat ID to send to instead of the default reviewer chat.
                              Pass update.effective_chat.id from cmd_generate so the reply
                              arrives in the same chat where /generate was typed.

    Returns:
        bool: True if sent successfully.
    """
    reviewer_chat_id = override_chat_id or _get_reviewer_chat_id(post.bot_id)
    if not reviewer_chat_id:
        logger.error("No reviewer chat ID set for bot '%s' — cannot send for review.", post.bot_id)
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

    # ── Load headline_b from DB (for A/B testing) ─────────────────────────
    headline_b = None
    with get_session() as session:
        db_post = session.query(Post).filter(Post.id == post.id).first()
        if db_post:
            headline_b = db_post.headline_b

    # Convert post content markdown to HTML so bold/italic render correctly
    # in the reviewer's Telegram chat (same conversion applied on publish).
    content_html = _to_html(post.content)

    # Append alt headline note if one was generated
    content_with_ab = content_html
    if headline_b:
        content_with_ab += (
            f"\n\n{'─' * 35}\n"
            f"💡 <b>Alt Headline (B):</b> <i>{headline_b}</i>\n"
            f"<i>Tap \"📝 Use Alt Headline (B)\" to swap it in before approving.</i>"
        )

    full_message = _to_html(review_header) + content_with_ab

    # ── Build inline buttons ───────────────────────────────────────────────
    # InlineKeyboardButton creates a clickable button in the chat.
    # callback_data is what gets sent back when the button is tapped.
    keyboard_rows = [
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
    ]

    # Add "Use Alt Headline" button if an alternative was generated
    if headline_b:
        keyboard_rows.append([
            InlineKeyboardButton(
                "📝 Use Alt Headline (B)",
                callback_data=f"{USE_HEADLINE_B_PREFIX}{post.id}"
            ),
        ])

    keyboard = InlineKeyboardMarkup(keyboard_rows)

    # ── Send the message ───────────────────────────────────────────────────
    try:
        # Use override_bot if provided (e.g. from cmd_generate, so the message
        # arrives via the bot the reviewer is already chatting with).
        # Otherwise fall back to the post's own bot token — used by the scheduler
        # where each bot sends its own review messages.
        if override_bot is not None:
            bot = override_bot
        else:
            token = _get_bot_token(post.bot_id)
            bot   = Bot(token=token)

        if post.image_url:
            # Try to send the cover image. Image URLs from the generation API
            # can expire — if the send fails, fall back to text-only gracefully.
            try:
                short_caption = _to_html(review_header.strip())
                await bot.send_photo(
                    chat_id=reviewer_chat_id,
                    photo=post.image_url,
                    caption=short_caption,
                    parse_mode=ParseMode.HTML,
                )
                # Send full post content + buttons as a follow-up text message
                await bot.send_message(
                    chat_id=reviewer_chat_id,
                    text=content_with_ab,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
            except TelegramError as img_err:
                # Image URL likely expired — fall back to text-only review message
                logger.warning(
                    "Image send failed for post %d (%s) — sending text-only fallback.",
                    post.id, str(img_err)
                )
                await bot.send_message(
                    chat_id=reviewer_chat_id,
                    text=full_message,
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
        f"<b>Post ID {post.id}</b> | Status: <code>{post.status}</code>\n\n{_to_html(post.content)}",
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


async def cmd_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /generate [bot_id] — Generates a new digest post on demand.

    Runs the full pipeline: fetch best articles → generate digest → send for review.
    The generated post appears in this chat with Approve / Reject buttons, just like
    a scheduled post would.

    Usage:
      /generate             → generates for the bot currently running this review session
      /generate bollywood   → generates for the Bollywood bot
      /generate ai_news     → generates for the AI News bot
    """
    # Determine which bot to generate for
    if context.args:
        bot_id = context.args[0].lower().strip()
    else:
        # Default to the bot_id this review session was started with
        bot_id = context.bot_data.get("bot_id", "ai_news")

    valid_bots = {"ai_news", "bollywood", "astrology"}
    if bot_id not in valid_bots:
        await update.message.reply_text(
            f"❌ Unknown bot: '{bot_id}'\n"
            f"Valid options: ai_news, bollywood, astrology\n"
            f"Example: /generate bollywood"
        )
        return

    bot_label = {
        "ai_news":   "🤖 AI News Bot",
        "bollywood": "🎬 Bollywood Buzz Bot",
        "astrology": "🕉️ Astrology Bot",
    }.get(bot_id, bot_id)

    # Send an initial status message — we'll edit it when done
    status_msg = await update.message.reply_text(
        f"⏳ Generating post for {bot_label}...\n"
        f"Fetching articles and calling AI. This takes about 30–60 seconds."
    )

    try:
        # Generation involves blocking API calls (Euri/Gemini).
        # Run it in a thread executor so it doesn't freeze the Telegram event loop.
        loop = asyncio.get_event_loop()
        post = await loop.run_in_executor(None, _run_generation, bot_id)

        if not post:
            if bot_id == "astrology":
                await status_msg.edit_text(
                    f"❌ Could not generate a post for {bot_label}.\n\n"
                    f"Possible reasons:\n"
                    f"• Gemini API rate limit reached — wait a few minutes and try again\n"
                    f"• Panchang scraping failed — AI will use today's date as fallback\n"
                    f"Check logs for details."
                )
            else:
                await status_msg.edit_text(
                    f"❌ Could not generate a post for {bot_label}.\n\n"
                    f"Possible reasons:\n"
                    f"• No articles in the database yet — run the fetcher first:\n"
                    f"  python aggregator/test_fetch.py {bot_id}\n"
                    f"• All articles were blocked by guardrails\n"
                    f"• Gemini API rate limit reached — wait a few minutes and try again"
                )
            return

        # Post generated — send it to THIS chat for review (with Approve/Reject buttons).
        # Pass context.bot + current chat_id so the message is delivered through the
        # bot the reviewer is already talking to, regardless of which bot owns the post.
        # This avoids 403 Forbidden errors when generating cross-bot posts (e.g. typing
        # /generate bollywood in the astrology reviewer chat).
        sent = await _send_review_message(
            post,
            override_bot=context.bot,
            override_chat_id=update.effective_chat.id,
        )

        if sent:
            await status_msg.edit_text(
                f"✅ Post generated for {bot_label}! (ID: {post.id})\n"
                f"Review it in the message above. 👆"
            )
        else:
            await status_msg.edit_text(
                f"⚠️ Post generated (ID: {post.id}) but failed to send review message.\n"
                f"Use /preview {post.id} to review it."
            )

    except Exception as e:
        logger.error("cmd_generate failed for bot '%s': %s", bot_id, str(e))
        await status_msg.edit_text(
            f"❌ Generation failed with an error:\n{str(e)[:300]}"
        )


def _run_generation(bot_id: str) -> "Post | None":
    """
    Synchronous helper that runs the full article selection + generation pipeline.

    Designed to be called via asyncio.run_in_executor() so it runs in a
    background thread without blocking the Telegram bot's event loop.

    For the astrology bot, uses the panchang pipeline instead of RSS articles.
    For all other bots, uses the standard virality-scored article pipeline.

    Args:
        bot_id (str): The bot to generate a post for.

    Returns:
        Post:  The generated and saved Post object, ready for review.
        None:  If no articles were available or generation failed.
    """
    from generator.claude_client import generate_digest_post, generate_and_save_post

    logger.info("cmd_generate: Starting pipeline for bot '%s'", bot_id)

    # Astrology bot uses today's panchang data, not RSS articles
    if bot_id == "astrology":
        from aggregator.panchang_fetcher import get_today_panchang_article
        article = get_today_panchang_article()
        if not article:
            logger.warning("cmd_generate: Panchang fetch failed for astrology bot")
            return None
        logger.info("cmd_generate: Panchang article ready (id=%d)", article.id)
        return generate_and_save_post(article, bot_id)

    # All other bots: standard RSS article pipeline
    from scoring.fallback import get_best_articles_for_bot

    articles, used_fallback = get_best_articles_for_bot(bot_id, posts_needed=5)

    if not articles:
        logger.warning("cmd_generate: No articles found for bot '%s'", bot_id)
        return None

    logger.info(
        "cmd_generate: Got %d articles for bot '%s' (fallback=%s)",
        len(articles), bot_id, used_fallback
    )

    if len(articles) > 1:
        return generate_digest_post(articles, bot_id)
    else:
        return generate_and_save_post(articles[0], bot_id)


def _swap_first_headline(content: str, new_headline: str) -> str:
    """
    Replaces the first story's bold headline in a digest post.

    Finds the line starting with 1️⃣ and swaps the text between
    the first pair of asterisks (*...*) with new_headline.

    Args:
        content (str):      Full post text.
        new_headline (str): Replacement headline text (no asterisks).

    Returns:
        str: Updated post content with the headline swapped.
    """
    import re
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.strip().startswith('1️⃣'):
            # Replace text between first *...* pair on this line
            lines[i] = re.sub(
                r'\*([^*\n]+)\*',
                lambda m: f'*{new_headline}*',
                line,
                count=1
            )
            break
    return '\n'.join(lines)


async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /edit [post_id] — Edits a pending post using a natural language instruction.

    Opens an edit session for the specified post (or the most recent pending
    post if no ID is given). The reviewer then types what they want changed
    — Gemini applies the edit and re-sends the post for review.

    Usage:
      /edit        → edit the most recent pending post for this bot
      /edit 27     → edit post #27

    After typing /edit, the bot asks: "What would you like to change?"
    The reviewer can then type e.g.:
      "Make the headline more dramatic"
      "Shorten the remedy section"
      "Change 'GPT-5' to 'OpenAI's latest model'"
    """
    chat_id = update.message.chat_id
    bot_id  = context.bot_data.get("bot_id", "ai_news")

    # Resolve post_id — from argument or most recent pending
    post_id = None
    if context.args:
        try:
            post_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Usage: /edit <post_id>\nExample: /edit 27")
            return
    else:
        with get_session() as session:
            post = (
                session.query(Post)
                .filter_by(bot_id=bot_id, status="pending_review")
                .order_by(Post.created_at.desc())
                .first()
            )
            if post:
                post_id = post.id

    if not post_id:
        await update.message.reply_text(
            "No pending posts found to edit.\n"
            "Use /edit <post_id> to edit a specific post."
        )
        return

    # Fetch and show a preview of the post
    with get_session() as session:
        post = session.query(Post).filter(Post.id == post_id).first()
        if not post:
            await update.message.reply_text(f"Post {post_id} not found.")
            return
        preview = post.content[:200]

    # Set state — next text message from this chat will be the edit instruction
    _awaiting_edit_instruction[chat_id] = post_id

    await update.message.reply_text(
        f"✏️ *Editing post {post_id}*\n\n"
        f"_{preview}..._\n\n"
        f"What would you like to change? Type your instruction:",
        parse_mode=ParseMode.MARKDOWN
    )


def _apply_edit_sync(post_id: int, instruction: str) -> "Post | None":
    """
    Synchronous helper — applies an edit instruction to a post via Gemini.

    Designed to be called via asyncio.run_in_executor() so the blocking
    API call doesn't freeze the Telegram event loop.

    Args:
        post_id (int):     ID of the post to edit.
        instruction (str): Free-text description of what to change.

    Returns:
        Post:  The updated Post object with new content.
        None:  If the post was not found or the API call failed.
    """
    from generator.claude_client import apply_edit_instruction

    # Read current content
    current_content = None
    bot_id = None
    with get_session() as session:
        post = session.query(Post).filter(Post.id == post_id).first()
        if not post:
            return None
        current_content = post.content
        bot_id = post.bot_id

    # Generate edited content (blocking API call)
    new_content = apply_edit_instruction(current_content, instruction, bot_id)
    if not new_content:
        return None

    # Save updated content to DB
    with get_session() as session:
        post = session.query(Post).filter(Post.id == post_id).first()
        if not post:
            return None
        post.content    = new_content
        post.headline_b = None   # Clear alt headline — content has changed
        session.flush()
        session.expunge(post)

    return post


async def cmd_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /card [full] — Generates a shareable image card and publishes it to @astrochhayah.

    Only works for the astrology bot (card feature is astrology-only).
    Uses the most recently published or pending_review astrology post.

    Usage:
      /card        → 1080x1350 Instagram/Facebook-compatible card (default)
      /card full   → Full auto-height card (all content, best for WhatsApp)

    Steps:
      1. Fetch latest astrology post from DB
      2. Generate the image card
      3. Publish to @astrochhayah channel
      4. Send preview to this reviewer chat
    """
    bot_id  = context.bot_data.get("bot_id", "astrology")
    chat_id = update.effective_chat.id

    if bot_id != "astrology":
        await update.message.reply_text(
            "⚠️ /card is only available for the Astrology bot.\n"
            "Run the review bot with `python test_review_interface.py astrology`."
        )
        return

    status_msg = await update.message.reply_text("🎨 Generating image card...")

    try:
        # ── Fetch the latest astrology post ───────────────────────────────────
        with get_session() as session:
            post = (
                session.query(Post)
                .filter(
                    Post.bot_id == "astrology",
                    Post.status.in_(["published", "pending_review", "approved"])
                )
                .order_by(Post.id.desc())
                .first()
            )
            if not post:
                await status_msg.edit_text("❌ No astrology post found. Run /generate first.")
                return

            post_id   = post.id
            image_url = post.image_url
            content   = post.content
            summary   = post.article.summary if post.article else ""

        if not image_url:
            await status_msg.edit_text(
                f"❌ Post {post_id} has no image URL. Cannot generate card."
            )
            return

        # ── Generate card in thread executor (download + Pillow = blocking) ───
        use_full  = context.args and context.args[0].lower() == "full"
        loop      = asyncio.get_event_loop()

        import importlib, generator.image_card as _ic_mod
        importlib.reload(_ic_mod)

        if use_full:
            card_path = await loop.run_in_executor(
                None, _ic_mod.generate_astrology_card, image_url, content, summary
            )
        else:
            card_path = await loop.run_in_executor(
                None, _ic_mod.generate_social_card, image_url, content, summary
            )

        if not card_path:
            await status_msg.edit_text(
                "❌ Card generation failed. Check logs for details."
            )
            return

        # ── Publish card to @astrochhayah channel ─────────────────────────────
        token      = _get_bot_token(bot_id)
        channel_id = _get_channel_id(bot_id)
        pub_bot    = Bot(token=token)

        with open(card_path, "rb") as f:
            channel_msg = await pub_bot.send_photo(
                chat_id=channel_id,
                photo=f,
            )

        logger.info(
            "cmd_card: Card published to %s (message_id=%d, post_id=%d)",
            channel_id, channel_msg.message_id, post_id,
        )

        # ── Send preview to reviewer chat ──────────────────────────────────────
        await status_msg.edit_text(
            f"✅ Card published to {channel_id}!\n"
            f"Post ID: {post_id} | Message ID: {channel_msg.message_id}\n\n"
            f"Preview sent below 👇"
        )

        with open(card_path, "rb") as f:
            await context.bot.send_photo(chat_id=chat_id, photo=f)

    except Exception as e:
        logger.error("cmd_card failed: %s", e)
        await status_msg.edit_text(f"❌ Error generating card: {e}")


async def cmd_killstale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /killstale — Kills all stale Python processes except this one.

    Use this when /card or /generate freeze or fail due to a ghost process
    (e.g. a previous main.py run that wasn't cleanly stopped).

    What it does:
      1. Lists all running python.exe / python3.exe processes on this machine.
      2. Excludes the current process (the one running this bot).
      3. Force-kills all others.
      4. Reports what was killed.

    After running /killstale, retry /card or /generate.
    """
    import os
    import subprocess

    my_pid = os.getpid()
    killed = []
    failed = []

    try:
        # Use PowerShell Get-Process for clean, unambiguous PID output.
        # tasklist CSV parsing is fragile on some Windows locales due to quoting
        # and number formatting differences. PowerShell returns one integer PID
        # per line with no formatting — safe to parse directly.
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-Process python,python3 -ErrorAction SilentlyContinue"
                " | Select-Object -ExpandProperty Id"
            ],
            capture_output=True, text=True, timeout=10
        )

        pids_to_kill = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pid = int(line)
                if pid != my_pid:
                    pids_to_kill.append(pid)
            except ValueError:
                continue

        if not pids_to_kill:
            await update.message.reply_text(
                f"No stale Python processes found.\n"
                f"(Current PID: {my_pid})"
            )
            return

        # Kill each stale PID
        for pid in pids_to_kill:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True, timeout=5
                )
                killed.append(pid)
                logger.info("cmd_killstale: killed PID %d", pid)
            except Exception as e:
                failed.append((pid, str(e)))
                logger.warning("cmd_killstale: failed to kill PID %d: %s", pid, e)

        lines_out = [f"Killed {len(killed)} stale process(es). Current PID: {my_pid}\n"]
        if killed:
            lines_out.append("Stopped: " + ", ".join(str(p) for p in killed))
        if failed:
            lines_out.append("Failed: " + ", ".join(f"{p}({e})" for p, e in failed))
        lines_out.append("\nYou can now retry /card or /generate.")

        await update.message.reply_text("\n".join(lines_out))

    except Exception as e:
        logger.error("cmd_killstale failed: %s", e)
        await update.message.reply_text(f"Error running killstale: {e}")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /help — Shows all available reviewer commands.
    """
    help_text = (
        "🤖 *AI News Bot — Reviewer Commands*\n\n"
        "/generate `[bot_id]` — Generate a new post now\n"
        "     e.g. /generate bollywood\n\n"
        "/card — Instagram/Facebook card (astrology only)\n"
        "/card full — Full WhatsApp card (all content, auto-height)\n\n"
        "/edit `[post_id]` — Edit a post before approving\n"
        "     e.g. /edit 27  (or just /edit for latest)\n\n"
        "/pending — List all posts waiting for review\n"
        "/preview `<id>` — Show full post content\n"
        "/sources `<id>` — Show original source article\n"
        "/skip `<id>` — Skip this post (no publish)\n"
        "/killstale — Kill stale Python processes (fix 409/freeze issues)\n"
        "/help — Show this help message\n\n"
        "_Tap ✅ Approve / ❌ Reject / 📝 Use Alt Headline on any post._"
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

    # Always acknowledge the button tap — removes the loading spinner.
    # Wrapped in try/except because Telegram expires callback queries after ~30s.
    # If the query is too old, we log it and continue — the approve/reject still works.
    try:
        await query.answer()
    except Exception:
        logger.debug("query.answer() timed out (query too old) — continuing anyway.")

    # ── Approve button ─────────────────────────────────────────────────────
    if data.startswith(APPROVE_PREFIX):
        post_id = int(data[len(APPROVE_PREFIX):])
        await _handle_approve(query, post_id)

    # ── Reject button ──────────────────────────────────────────────────────
    elif data.startswith(REJECT_PREFIX):
        post_id = int(data[len(REJECT_PREFIX):])
        # Set state FIRST so the reason handler works even if later calls fail
        _awaiting_reject_reason[chat_id] = post_id
        # Try to remove buttons — non-critical if network hiccup prevents it
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            logger.debug("Could not remove buttons on reject — continuing.")
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

    # ── Use Alt Headline (B) button ────────────────────────────────────────
    elif data.startswith(USE_HEADLINE_B_PREFIX):
        post_id = int(data[len(USE_HEADLINE_B_PREFIX):])

        updated_post = None
        with get_session() as session:
            post = session.query(Post).filter(Post.id == post_id).first()
            if not post or not post.headline_b:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Alt headline no longer available for this post."
                )
                return
            # Swap the first story's headline in the post content
            post.content  = _swap_first_headline(post.content, post.headline_b)
            post.headline_b = None   # Clear — used it, no longer needed
            session.flush()
            session.expunge(post)
            updated_post = post

        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Headline swapped to Option B for post {post_id}.\nSending updated post for review..."
        )
        await _send_review_message(updated_post)


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

    # Remove the inline buttons from the review message.
    # Wrapped in try/except because Telegram can reject edits on old messages
    # (e.g. message too old, or a network hiccup) — this must not abort the approval.
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError as e:
        logger.warning("Could not remove buttons from review message (post %d): %s", post_id, e)

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

    # ── Edit instruction flow ──────────────────────────────────────────────
    if chat_id in _awaiting_edit_instruction:
        post_id = _awaiting_edit_instruction.pop(chat_id)
        status_msg = await update.message.reply_text(
            f"⏳ Applying edit to post {post_id}...\nCalling AI — takes ~20–40 seconds."
        )
        try:
            loop = asyncio.get_event_loop()
            updated_post = await loop.run_in_executor(None, _apply_edit_sync, post_id, text)

            if not updated_post:
                await status_msg.edit_text(
                    f"❌ Edit failed for post {post_id}.\n"
                    f"Possible reasons: API rate limit, or post not found.\n"
                    f"Check logs for details."
                )
                return

            await status_msg.edit_text(
                f"✅ Edit applied to post {post_id}.\nSending updated post for review..."
            )
            await _send_review_message(updated_post)

        except Exception as e:
            logger.error("Edit flow failed for post %d: %s", post_id, str(e))
            await status_msg.edit_text(f"❌ Edit failed with error:\n{str(e)[:300]}")
        return

    # ── Reject reason flow ────────────────────────────────────────────────
    if chat_id in _awaiting_reject_reason:
        post_id = _awaiting_reject_reason.pop(chat_id)
        _reject_post(post_id, reason=text)
        await update.message.reply_text(
            f"❌ Post {post_id} rejected.\nReason: _{text}_",
            parse_mode=ParseMode.HTML
        )
        logger.info("Post %d rejected by reviewer. Reason: %s", post_id, text)
        return

    # Not a command, not in any flow — show help
    await update.message.reply_text("Use /help to see available commands.")


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

def build_review_bot(bot_id: str = "ai_news") -> Application:
    """
    Builds and configures the Telegram bot application for reviewing posts.

    Creates an Application instance with all command and callback handlers
    registered. Uses the token for the given bot_id so that Approve/Reject
    callbacks are routed to the correct bot.

    Args:
        bot_id (str): The bot whose token to use for polling.
                      e.g. "ai_news" or "bollywood". Defaults to "ai_news".

    Returns:
        Application: A configured python-telegram-bot Application ready to run.
    """
    token = _get_bot_token(bot_id)

    if not token:
        raise ValueError("No Telegram bot token found. Check your .env file.")

    # Build the application
    app = Application.builder().token(token).build()

    # Store bot_id so /generate (with no args) defaults to this bot
    app.bot_data["bot_id"] = bot_id

    # Register command handlers
    # Each handler listens for a specific /command from the reviewer
    app.add_handler(CommandHandler("generate",  cmd_generate))
    app.add_handler(CommandHandler("card",      cmd_card))
    app.add_handler(CommandHandler("edit",      cmd_edit))
    app.add_handler(CommandHandler("pending",   cmd_pending))
    app.add_handler(CommandHandler("preview",   cmd_preview))
    app.add_handler(CommandHandler("sources",   cmd_sources))
    app.add_handler(CommandHandler("skip",      cmd_skip))
    app.add_handler(CommandHandler("killstale", cmd_killstale))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("start",     cmd_help))  # /start shows help too

    # Register inline button handler
    app.add_handler(CallbackQueryHandler(handle_button))

    # Register plain text handler (for reject reasons)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    logger.info("Review bot application built with all handlers registered.")
    return app


def start_review_bot(bot_id: str = "ai_news") -> None:
    """
    Starts the review bot and begins polling for messages.

    This runs INDEFINITELY — it blocks the current thread and keeps
    listening for messages from the reviewer.

    In production this will be run in a background thread by the scheduler.
    In development you can run it directly to test the review interface.

    Args:
        bot_id (str): Which bot's token to use for polling.
                      Must match the bot whose review messages are being sent.
                      e.g. "ai_news" or "bollywood". Defaults to "ai_news".

    Call this from main.py or run publisher/test_review_interface.py directly.
    """
    logger.info("Starting review bot (polling for messages, bot_id='%s')...", bot_id)
    app = build_review_bot(bot_id)

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
