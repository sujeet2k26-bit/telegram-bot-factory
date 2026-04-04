"""
publisher/telegram_bot.py
──────────────────────────
Publishes approved posts to Telegram channels.

What this file does:
  - Sends a post (text + optional cover image) to the correct Telegram channel.
  - Is completely bot-agnostic: it reads the bot token and channel ID
    from settings based on the bot_id — no hardcoding per bot.
  - Updates the post status in the database after publishing.
  - Logs every publish action to logs/publish_history.log.
  - Handles errors gracefully — if sending fails, the post stays
    as 'approved' in the DB so it can be retried.

How Telegram message sending works:
  - If the post has a cover image → sends as photo with caption (text below image)
  - If no image → sends as plain text message
  - Telegram supports Markdown formatting in messages

Adding a new bot:
  - No changes needed here. The publisher reads token/channel from settings
    using the bot_id. Just add the new bot's env vars and it works automatically.

About python-telegram-bot v21:
  - Version 21 uses async/await (asynchronous programming).
  - This means functions here use 'async def' and must be called with 'await'.
  - asyncio.run() is used to run async functions from synchronous code.
  - Don't worry if this looks unfamiliar — the comments explain each step.
"""

import asyncio
import logging
import re
from datetime import datetime

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from config.settings import settings
from db.database import get_session
from db.models import Post, PublishLog

# Use the publisher logger so publish events go to publish_history.log
logger = logging.getLogger("publisher.telegram_bot")


def _to_html(text: str) -> str:
    """
    Converts AI-generated markdown text to Telegram-safe HTML.

    Why HTML instead of Markdown?
      - Telegram's MarkdownV1 parser is strict — a lone * or _ from
        AI-generated content causes a parse error and the message fails.
      - HTML is more forgiving: unrecognised tags are ignored, and the
        only characters that need escaping are <, >, and &.

    Conversions applied (in order):
      1. Escape HTML special characters (&, <, >)
      2. ***text*** or **text** → <b>text</b>  (bold)
      3. *text*                 → <b>text</b>  (bold — single asterisk)
      4. _text_                 → <i>text</i>  (italic)
      5. `text`                 → <code>text</code> (inline code)

    Args:
        text (str): Raw post text that may contain markdown formatting.

    Returns:
        str: HTML-formatted text safe to send with ParseMode.HTML.
    """
    # Step 1: Escape HTML special characters first
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")

    # Step 2: Convert ***text*** and **text** → <b>text</b>
    text = re.sub(r'\*{2,3}(.+?)\*{2,3}', r'<b>\1</b>', text)

    # Step 3: Convert remaining *text* → <b>text</b>
    text = re.sub(r'\*(.+?)\*', r'<b>\1</b>', text)

    # Step 4: Convert _text_ → <i>text</i>
    text = re.sub(r'_(.+?)_', r'<i>\1</i>', text)

    # Step 5: Convert `text` → <code>text</code>
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)

    return text


# ── Bot token map ──────────────────────────────────────────────────────────
# Maps each bot_id to its Telegram bot token and channel ID from settings.
# When a new bot is added, add one entry here matching its bot_id in bots.json.
BOT_CONFIG_MAP = {
    "ai_news": {
        "token":      lambda: settings.TELEGRAM_AI_BOT_TOKEN,
        "channel_id": lambda: settings.TELEGRAM_AI_CHANNEL_ID,
    },
    "bollywood": {
        "token":      lambda: settings.TELEGRAM_BOLLYWOOD_BOT_TOKEN,
        "channel_id": lambda: settings.TELEGRAM_BOLLYWOOD_CHANNEL_ID,
    },
    "astrology": {
        "token":      lambda: settings.TELEGRAM_ASTROLOGY_BOT_TOKEN,
        "channel_id": lambda: settings.TELEGRAM_ASTROLOGY_CHANNEL_ID,
    },
}


def get_bot_credentials(bot_id: str) -> tuple:
    """
    Retrieves the Telegram bot token and channel ID for a given bot.

    Args:
        bot_id (str): The bot ID from bots.json (e.g. "ai_news").

    Returns:
        tuple: A two-element tuple (token, channel_id).

    Raises:
        ValueError: If bot_id is not in BOT_CONFIG_MAP or token is missing.
    """
    if bot_id not in BOT_CONFIG_MAP:
        raise ValueError(
            f"Unknown bot_id '{bot_id}'. "
            f"Add it to BOT_CONFIG_MAP in publisher/telegram_bot.py"
        )

    config = BOT_CONFIG_MAP[bot_id]
    token = config["token"]()           # Call the lambda to get current value
    channel_id = config["channel_id"]() # Call the lambda to get current value

    if not token:
        raise ValueError(
            f"Telegram token for bot '{bot_id}' is not set. "
            f"Check your .env file for the correct token variable."
        )
    if not channel_id:
        raise ValueError(
            f"Telegram channel ID for bot '{bot_id}' is not set. "
            f"Check your .env file for the correct channel ID variable."
        )

    return token, channel_id


def _build_short_caption(text: str) -> str:
    """
    Builds a short image caption from the post text when the full text
    exceeds Telegram's 1024-character caption limit.

    The date is always computed fresh at publish time (not extracted from the
    stored post content) so it never shows a stale/past date.

    Strategy:
      - Header line with TODAY's date (built fresh, not from post content)
      - First story headline extracted from the post (starts with 1️⃣)
      - Hashtags
      - A nudge so subscribers know the full digest follows below

    Args:
        text (str): The full post text.

    Returns:
        str: A caption under 1024 characters.
    """
    from datetime import datetime, timezone, timedelta

    # Use IST (UTC+5:30) so the date matches what Indian users see
    IST = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(IST).strftime("%B %d, %Y")

    # Build a fresh header — never rely on the date baked into the stored content
    caption = f"📰 *AI News Daily — {today}*"

    # Extract the first story headline from the post body (line starting with 1️⃣)
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("1️⃣"):
            # Clean up any triple-asterisk markdown Gemini sometimes adds (***text***)
            clean_line = line.replace("***", "*")
            candidate = f"{caption}\n{clean_line}"
            if len(candidate) <= 900:
                caption = candidate
            break

    caption += "\n\n#AINews #TechUpdate\n👇 Full digest below"
    return caption


async def _send_with_image(bot: Bot, channel_id: str,
                            text: str, image_url: str) -> bool:
    """
    Sends a Telegram message with a photo and caption.

    The image appears at the top and the post text appears as a caption below.
    Telegram captions are limited to 1024 characters — if the text is longer,
    it is automatically sent as a separate message after the image.

    Args:
        bot (Bot):         The Telegram Bot object to send the message with.
        channel_id (str):  The channel to post to (e.g. "@AINewsDaily").
        text (str):        The post text (caption for the image).
        image_url (str):   The URL of the cover image to send.

    Returns:
        bool: True if the message was sent successfully, False on error.
    """
    try:
        # Telegram captions have a 1024-character limit
        if len(text) <= 1024:
            # Short enough — use full text as caption directly under the image
            await bot.send_photo(
                chat_id=channel_id,
                photo=image_url,
                caption=_to_html(text),
                parse_mode=ParseMode.HTML,
            )
        else:
            # Text too long for a caption — build a short teaser caption from
            # the first 2 lines of the post (header + first story headline),
            # then send the full text as a follow-up message.
            short_caption = _build_short_caption(text)
            await bot.send_photo(
                chat_id=channel_id,
                photo=image_url,
                caption=_to_html(short_caption),
                parse_mode=ParseMode.HTML,
            )
            await bot.send_message(
                chat_id=channel_id,
                text=_to_html(text),
                parse_mode=ParseMode.HTML,
            )

        logger.info("Sent message with image to channel '%s'", channel_id)
        return True

    except TelegramError as e:
        logger.error("Failed to send image message to '%s': %s", channel_id, str(e))
        return False


async def _send_text_only(bot: Bot, channel_id: str, text: str) -> bool:
    """
    Sends a plain text Telegram message (no image).

    Used as a fallback when no cover image is available.

    Args:
        bot (Bot):         The Telegram Bot object.
        channel_id (str):  The channel to post to.
        text (str):        The post text to send.

    Returns:
        bool: True if sent successfully, False on error.
    """
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=_to_html(text),
            parse_mode=ParseMode.HTML,
        )
        logger.info("Sent text-only message to channel '%s'", channel_id)
        return True

    except TelegramError as e:
        logger.error("Failed to send text message to '%s': %s", channel_id, str(e))
        return False


async def _publish_post_async(post: Post) -> bool:
    """
    The async core of the publish function.

    Sends the post to Telegram and updates the database.
    Called internally by publish_post() via asyncio.run().

    Args:
        post (Post): The Post database object to publish.
                     Must have status 'approved'.

    Returns:
        bool: True if the post was published successfully.
    """
    bot_id = post.bot_id

    # ── Get bot credentials ────────────────────────────────────────────────
    try:
        token, channel_id = get_bot_credentials(bot_id)
    except ValueError as e:
        logger.error("Cannot publish post %d: %s", post.id, str(e))
        return False

    # ── Create the Telegram bot instance ──────────────────────────────────
    # We create a new Bot object for each publish call.
    # This is safe and avoids any state issues between publishes.
    bot = Bot(token=token)

    # ── Send the message ───────────────────────────────────────────────────
    logger.info(
        "Publishing post_id=%d to channel '%s' (bot='%s') ...",
        post.id, channel_id, bot_id
    )

    if post.image_url:
        # Try sending with image first
        success = await _send_with_image(bot, channel_id, post.content, post.image_url)

        if not success:
            # Image send failed — fall back to text only
            logger.warning(
                "Image send failed for post %d — retrying as text only.", post.id
            )
            success = await _send_text_only(bot, channel_id, post.content)
    else:
        # No image available — send text only
        success = await _send_text_only(bot, channel_id, post.content)

    # ── Update database ────────────────────────────────────────────────────
    if success:
        _mark_post_published(post.id, channel_id)
        logger.info(
            "POST PUBLISHED | post_id=%d | bot='%s' | channel='%s'",
            post.id, bot_id, channel_id
        )
    else:
        logger.error(
            "PUBLISH FAILED | post_id=%d | bot='%s' — post remains 'approved' for retry.",
            post.id, bot_id
        )

    return success


def publish_post(post: Post) -> bool:
    """
    Publishes an approved post to its Telegram channel.

    This is the main function called by the pipeline.
    It is synchronous (no async/await needed from the caller).
    Internally it uses asyncio.run() to execute the async Telegram call.

    The post must have status 'approved' — set by the reviewer
    using the /approve command.

    Args:
        post (Post): The Post database object to publish.
                     Must be in 'approved' status.

    Returns:
        bool: True if the post was published successfully.
              False if publishing failed (post remains 'approved' for retry).

    Example:
        >>> from publisher.telegram_bot import publish_post
        >>> success = publish_post(approved_post)
        >>> if success:
        ...     print("Post is live on Telegram!")
    """
    if post.status != "approved":
        logger.warning(
            "Attempted to publish post %d with status '%s' — must be 'approved'.",
            post.id, post.status
        )
        return False

    # asyncio.run() runs the async function and waits for it to finish
    # It handles creating and closing the event loop automatically
    try:
        return asyncio.run(_publish_post_async(post))
    except RuntimeError as e:
        # asyncio.run() fails if there's already a running event loop
        # This can happen in Jupyter notebooks or some async frameworks
        logger.error("asyncio error while publishing post %d: %s", post.id, str(e))
        return False


def _mark_post_published(post_id: int, channel_id: str) -> None:
    """
    Updates the post status to 'published' and creates a publish log entry.

    Args:
        post_id (int):    ID of the post that was published.
        channel_id (str): The Telegram channel it was published to.
    """
    try:
        with get_session() as session:
            # Update the post record
            post = session.query(Post).filter(Post.id == post_id).first()
            if post:
                post.status = "published"
                post.published_at = datetime.utcnow()

                # Create a publish log entry for the history record
                log_entry = PublishLog(
                    post_id=post_id,
                    bot_id=post.bot_id,
                    channel_id=channel_id,
                    action="published",
                    timestamp=datetime.utcnow(),
                )
                session.add(log_entry)

    except Exception as e:
        logger.error("Failed to update post %d status after publish: %s", post_id, str(e))
