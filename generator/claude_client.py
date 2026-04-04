"""
generator/claude_client.py
───────────────────────────
Handles all AI content generation using Gemini models via the Euri API.

What this file does:
  - Connects to the Euri API gateway using the OpenAI-compatible SDK.
  - Generates post TEXT using gemini-2.5-pro.
  - Generates cover IMAGES using gemini-2-pro-image-preview.
  - Loads the correct prompt template based on the bot_id.
  - Runs a post-generation guardrail check on the output.
  - Saves the generated post to the database (posts table).
  - Returns the saved Post object ready for human review.

Why is this file called 'claude_client.py' if it uses Gemini?
  - The file name reflects the project's original design intention
    (Claude API). The actual implementation uses Gemini via Euri,
    which is OpenAI-compatible so the code structure is the same.

How Euri works:
  - Euri is an API gateway at https://api.euron.one/api/v1/euri
  - It accepts OpenAI-format API calls and routes them to Google Gemini
  - We use the standard 'openai' Python library with a custom base_url

Flow for each article:
  1. Load prompt template for the bot (ai_news → English, bollywood → Hindi)
  2. Send article content + prompt to gemini-2.5-pro → get post text
  3. Run guardrail check on generated text
  4. Send article title to gemini-2-pro-image-preview → get image URL
  5. Save post (text + image URL) to DB with status 'pending_review'
  6. Return the Post object
"""

import logging
import importlib
from datetime import datetime
from openai import OpenAI

from config.settings import settings
from db.database import get_session
from db.models import Post, Article
from guardrails.content_filter import check_generated_post

logger = logging.getLogger(__name__)

# ── Initialise the Euri/OpenAI client ─────────────────────────────────────
# We create one client instance and reuse it for all API calls.
# This is more efficient than creating a new client for every request.
_client = None


def get_client() -> OpenAI:
    """
    Returns the shared Euri API client, creating it on first use.

    Uses lazy initialisation — the client is only created when
    the first API call is made, not when the module is imported.

    Returns:
        OpenAI: A configured OpenAI client pointing at the Euri API.

    Raises:
        ValueError: If EURI_API_KEY is not set in the .env file.
    """
    global _client

    if _client is None:
        if not settings.EURI_API_KEY:
            raise ValueError(
                "EURI_API_KEY is not set. "
                "Please add it to your .env file."
            )
        _client = OpenAI(
            api_key=settings.EURI_API_KEY,
            base_url=settings.EURI_BASE_URL,
        )
        logger.debug("Euri API client initialised. Base URL: %s", settings.EURI_BASE_URL)

    return _client


def load_prompt_module(bot_id: str):
    """
    Dynamically loads the prompt module for a given bot.

    Each bot has its own prompt file:
      ai_news    → generator/prompts_ai.py
      bollywood  → generator/prompts_bollywood.py
      astrology  → generator/prompts_astrology.py

    Using dynamic loading means adding a new bot only requires
    creating a new prompts_<id>.py file — no changes here needed.

    Args:
        bot_id (str): The bot ID from bots.json (e.g. "ai_news").

    Returns:
        module: The loaded prompt module with build_prompt(),
                build_image_prompt(), SYSTEM_PROMPT, and POST_FORMAT.

    Raises:
        ImportError: If no prompt module exists for this bot_id.
    """
    module_name = f"generator.prompts_{bot_id}"
    try:
        module = importlib.import_module(module_name)
        logger.debug("Loaded prompt module: %s", module_name)
        return module
    except ModuleNotFoundError:
        raise ImportError(
            f"No prompt module found for bot '{bot_id}'. "
            f"Expected file: generator/prompts_{bot_id}.py"
        )


def generate_post_text(article: Article, bot_id: str) -> str | None:
    """
    Generates the Telegram post text for an article using Gemini 2.5 Pro.

    Loads the correct prompt template, sends the article content to the
    Gemini text model, and returns the generated post text.

    Args:
        article (Article): The Article database object to write a post about.
        bot_id (str):      The bot ID to determine prompt language and tone.

    Returns:
        str:  The generated post text if successful.
        None: If generation failed (API error, empty response, etc.)
    """
    logger.info(
        "Generating post text for bot '%s' | Article: %s",
        bot_id, article.title[:70]
    )

    try:
        # Load the prompt module for this bot
        prompt_module = load_prompt_module(bot_id)

        # Build the full prompt using the article's data
        user_prompt = prompt_module.build_prompt(
            title=article.title,
            summary=article.summary or "",
            source_name=article.source_name,
            url=article.url,
        )
        system_prompt = prompt_module.SYSTEM_PROMPT

        # Call the Gemini text model via Euri
        client = get_client()
        response = client.chat.completions.create(
            model=settings.TEXT_MODEL,          # gemini-2.5-pro
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            max_tokens=settings.TEXT_MAX_TOKENS,  # 4096 — required for thinking model
        )

        # Extract the generated text from the response
        generated_text = response.choices[0].message.content

        if not generated_text or not generated_text.strip():
            logger.warning(
                "Gemini returned empty text for article '%s'", article.title[:70]
            )
            return None

        logger.info(
            "Text generation successful for bot '%s' (%d chars)",
            bot_id, len(generated_text)
        )
        return generated_text.strip()

    except ImportError as e:
        logger.error("Prompt module error: %s", str(e))
        return None
    except Exception as e:
        logger.error(
            "Text generation failed for bot '%s', article '%s': %s",
            bot_id, article.title[:70], str(e)
        )
        return None


def generate_cover_image(article: Article, bot_id: str) -> str | None:
    """
    Generates a cover image for the post using Gemini image model.

    Creates a professional, visually appealing image relevant to
    the article topic. The image URL is stored in the post record
    and sent alongside the text on Telegram.

    Args:
        article (Article): The Article object — title and summary are used
                           to create a relevant image prompt.
        bot_id (str):      The bot ID to load the correct image prompt style.

    Returns:
        str:  The URL of the generated image if successful.
        None: If image generation failed. The post will still be created
              without an image — image is optional, not required.
    """
    logger.info("Generating cover image for bot '%s'...", bot_id)

    try:
        prompt_module = load_prompt_module(bot_id)
        image_prompt = prompt_module.build_image_prompt(
            title=article.title,
            summary=article.summary or "",
        )

        client = get_client()
        response = client.images.generate(
            model=settings.IMAGE_MODEL,   # gemini-2-pro-image-preview
            prompt=image_prompt,
            size=settings.IMAGE_SIZE,     # 1024x1024
            n=1,
        )

        image_url = response.data[0].url
        if image_url:
            logger.info("Cover image generated successfully: %s", image_url[:60])
            return image_url
        else:
            logger.warning("Image generation returned no URL.")
            return None

    except Exception as e:
        # Image generation failure is non-critical — post can still be published
        # without an image. We log the error but don't stop the pipeline.
        logger.warning(
            "Cover image generation failed for bot '%s' (non-critical): %s",
            bot_id, str(e)
        )
        return None


def _generate_digest_cover_image(articles_data: list, bot_id: str) -> str | None:
    """
    Generates a cover image for the digest post using a digest-specific prompt.

    Uses build_digest_image_prompt() which creates a visual based on today's
    top story themes rather than a single article title.

    Args:
        articles_data (list): List of article dicts (title, summary, source_name).
        bot_id (str):         Bot ID to load the correct prompt module.

    Returns:
        str:  URL of the generated image, or None if generation failed.
    """
    try:
        prompt_module = load_prompt_module(bot_id)

        if hasattr(prompt_module, "build_digest_image_prompt"):
            image_prompt = prompt_module.build_digest_image_prompt(articles_data)
        else:
            # Fallback: use the top article's single-image prompt
            image_prompt = prompt_module.build_image_prompt(
                title=articles_data[0]["title"],
                summary=articles_data[0]["summary"],
            )

        client = get_client()
        response = client.images.generate(
            model=settings.IMAGE_MODEL,
            prompt=image_prompt,
            size=settings.IMAGE_SIZE,
            n=1,
        )

        image_url = response.data[0].url
        if image_url:
            logger.info("Digest cover image generated successfully.")
            return image_url
        return None

    except Exception as e:
        logger.warning("Digest cover image generation failed (non-critical): %s", str(e))
        return None


def generate_and_save_post(article: Article, bot_id: str) -> Post | None:
    """
    Full content generation pipeline for one article.

    Orchestrates the complete generation process:
      1. Generate post text with Gemini 2.5 Pro
      2. Run post-generation guardrail check on the text
      3. Generate cover image with Gemini image model
      4. Save the post to the database with status 'pending_review'
      5. Return the saved Post object

    This is the main function called by the pipeline scheduler.

    Args:
        article (Article): The selected Article to generate a post from.
        bot_id (str):      The bot ID for prompt selection and DB tagging.

    Returns:
        Post:  The saved Post database object if generation succeeded.
        None:  If generation failed or guardrails blocked the output.

    Example:
        >>> post = generate_and_save_post(selected_article, "ai_news")
        >>> if post:
        ...     print(f"Post ready for review: {post.id}")
    """
    logger.info(
        "Starting full content generation | bot='%s' | article_id=%d",
        bot_id, article.id
    )

    # ── Step 1: Generate post text ─────────────────────────────────────────
    post_text = generate_post_text(article, bot_id)

    if not post_text:
        logger.error(
            "Text generation failed for article %d — skipping post creation.",
            article.id
        )
        return None

    # ── Step 2: Post-generation guardrail check ────────────────────────────
    # Check the generated text BEFORE saving or sending to reviewer
    guardrail_result = check_generated_post(post_text, bot_id)

    if guardrail_result["is_blocked"]:
        logger.warning(
            "Generated post blocked by guardrails | category='%s' | article_id=%d",
            guardrail_result["category"], article.id
        )
        return None

    # ── Step 3: Generate cover image (non-blocking) ────────────────────────
    image_url = generate_cover_image(article, bot_id)
    # image_url may be None if image generation fails — that's acceptable

    # ── Step 4: Generate alternative headline for A/B testing ─────────────
    # Skipped for astrology — the tithi header is factual, not creative copy.
    headline_b = None
    if bot_id != "astrology":
        headline_b = _generate_headline_variant(post_text, bot_id)

    # ── Step 5: Save post to database ─────────────────────────────────────
    post = _save_post_to_db(
        article_id=article.id,
        bot_id=bot_id,
        content=post_text,
        image_url=image_url,
        headline_b=headline_b,
    )

    if post:
        logger.info(
            "Post saved to DB | post_id=%d | bot='%s' | has_image=%s",
            post.id, bot_id, image_url is not None
        )

    return post


def _generate_headline_variant(content: str, bot_id: str) -> str | None:
    """
    Generates one alternative headline for the first story in a digest post.

    Used for A/B headline testing in the review interface. The reviewer
    sees both headlines and can choose which one to publish with.

    Only called for digest bots (ai_news, bollywood). Skipped for astrology
    because the tithi header is factual data, not creative copy.

    Args:
        content (str): The full generated post text (first ~400 chars are used).
        bot_id (str):  The bot ID — affects language/tone of the alt headline.

    Returns:
        str:  A single alternative headline (no prefix, just the text).
        None: If generation failed.
    """
    try:
        preview = content[:400]
        lang_note = "Hinglish (Hindi+English mix)" if bot_id == "bollywood" else "English"

        prompt = (
            f"Here is a news post:\n\n{preview}\n\n"
            f"Write ONE alternative headline for the FIRST numbered story (1️⃣).\n"
            f"Rules:\n"
            f"- Language: {lang_note}\n"
            f"- Max 12 words\n"
            f"- Same tone as the original but a different angle or word choice\n"
            f"- Output ONLY the headline text — no prefix, no explanation, nothing else"
        )

        client = get_client()
        response = client.chat.completions.create(
            model=settings.TEXT_MODEL,
            messages=[
                {"role": "system", "content": "You are a headline writer. Output only the requested headline, nothing else."},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=80,  # Headlines are short — no need for more
        )

        result = response.choices[0].message.content
        if result and result.strip():
            # Strip any accidental quotes or asterisks the model may wrap around it
            return result.strip().strip("*\"'")
        return None

    except Exception as e:
        # Non-critical — post still works fine without a headline variant
        logger.warning("Headline variant generation failed (non-critical): %s", str(e))
        return None


def apply_edit_instruction(content: str, instruction: str, bot_id: str) -> str | None:
    """
    Applies a reviewer's edit instruction to a post using Gemini.

    Called by the /edit command flow in review_interface.py when the
    reviewer describes what they want changed (e.g. "make the headline
    more dramatic" or "shorten the remedy section").

    Args:
        content (str):     The current full post text to be edited.
        instruction (str): Free-text description of what to change.
        bot_id (str):      Used to load the correct system prompt for tone.

    Returns:
        str:  The edited post content if successful.
        None: If the API call failed.
    """
    try:
        prompt_module = load_prompt_module(bot_id)
        system_prompt = prompt_module.SYSTEM_PROMPT

        user_prompt = (
            f"Here is a Telegram post that needs a small edit:\n\n"
            f"---\n{content}\n---\n\n"
            f"Apply this change: {instruction}\n\n"
            f"Rules:\n"
            f"- Return ONLY the updated post content\n"
            f"- Keep the same format, structure, and emojis\n"
            f"- Apply ONLY the requested change — do not rewrite unrelated sections\n"
            f"- Do not add any preamble, explanation, or 'Here is the updated post' prefix"
        )

        client = get_client()
        response = client.chat.completions.create(
            model=settings.TEXT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            max_tokens=settings.TEXT_MAX_TOKENS,
        )

        result = response.choices[0].message.content
        if result and result.strip():
            logger.info("Edit applied successfully for bot '%s' (%d chars)", bot_id, len(result))
            return result.strip()
        return None

    except Exception as e:
        logger.error("apply_edit_instruction failed for bot '%s': %s", bot_id, str(e))
        return None


def _inject_article_urls(content: str, articles_data: list) -> str:
    """
    Injects a clickable "Read more" link after each 📌 source line in a digest.

    The digest AI generates entries numbered 1️⃣–5️⃣ and each ends with a
    📌 Source line. This function appends a [🔗 Read more](url) link after
    each 📌 line so Telegram users can tap through to the full article.

    Matching logic:
      - Tracks which numbered entry (1️⃣, 2️⃣ …) we are currently inside.
      - When a 📌 line is found, uses the current entry index to look up
        the matching article URL from articles_data.
      - Resets the index after each 📌 line so entries don't bleed into each other.

    Args:
        content (str):        The raw digest text from Gemini.
        articles_data (list): List of article dicts with 'url' keys,
                              in the same order as the digest entries.

    Returns:
        str: Digest text with [🔗 Read more](url) appended after each 📌 line.
    """
    # Emoji numbers that mark the start of each digest entry
    emoji_numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    lines = content.split('\n')
    result = []
    current_entry_idx = -1  # Which numbered entry we're currently inside (-1 = none)

    for line in lines:
        result.append(line)

        # Check if this line starts a new numbered entry (e.g. "1️⃣ *Headline*")
        for idx, emoji in enumerate(emoji_numbers):
            if line.strip().startswith(emoji):
                current_entry_idx = idx
                break

        # Check if this line is a 📌 source line — inject link after it
        if line.strip().startswith('📌') and 0 <= current_entry_idx < len(articles_data):
            url = articles_data[current_entry_idx].get('url', '')
            if url:
                # Replace the last appended line (the 📌 line) with itself + link inline
                result[-1] = result[-1] + f'  |  [🔗 Read more]({url})'
            current_entry_idx = -1  # Reset — next 📌 belongs to next entry

    return '\n'.join(result)


def generate_digest_post(articles: list, bot_id: str) -> Post | None:
    """
    Generates a single digest post covering multiple articles (e.g. top 5).

    Used when a bot has 'digest_count' set in bots.json — instead of one post
    per article, one combined post is generated covering all top articles.

    Flow:
      1. Build a digest prompt from all articles
      2. Call Gemini to generate the combined digest text
      3. Run post-generation guardrail check
      4. Generate a cover image based on the top article
      5. Save one Post to DB (linked to the top-ranked article)
      6. Return the Post object

    Args:
        articles (list): List of Article DB objects, sorted best-first.
                         Typically the top 5 by virality score.
        bot_id (str):    The bot ID — used to load the correct prompt module.

    Returns:
        Post:  The saved Post database object if generation succeeded.
        None:  If generation failed or guardrails blocked the content.
    """
    if not articles:
        logger.error("generate_digest_post called with empty articles list.")
        return None

    logger.info(
        "Generating digest post for bot '%s' covering %d articles...",
        bot_id, len(articles)
    )

    # ── Step 1: Build digest prompt ───────────────────────────────────────
    try:
        prompt_module = load_prompt_module(bot_id)
        if not hasattr(prompt_module, "build_digest_prompt"):
            logger.error(
                "Prompt module for bot '%s' has no build_digest_prompt() function. "
                "Add it to generator/prompts_%s.py",
                bot_id, bot_id
            )
            return None

        # Convert Article objects to plain dicts for the prompt builder
        articles_data = [
            {
                "title":          a.title,
                "summary":        a.summary or "",
                "source_name":    a.source_name,
                "url":            a.url,
                "virality_score": a.virality_score or 0,
            }
            for a in articles
        ]

        user_prompt  = prompt_module.build_digest_prompt(articles_data)
        system_prompt = prompt_module.SYSTEM_PROMPT

    except ImportError as e:
        logger.error("Prompt module error for bot '%s': %s", bot_id, str(e))
        return None

    # ── Step 2: Generate digest text ──────────────────────────────────────
    try:
        client = get_client()
        response = client.chat.completions.create(
            model=settings.TEXT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            max_tokens=settings.TEXT_MAX_TOKENS,
        )

        digest_text = response.choices[0].message.content
        if not digest_text or not digest_text.strip():
            logger.error("Gemini returned empty digest text for bot '%s'.", bot_id)
            return None

        digest_text = digest_text.strip()
        digest_text = _inject_article_urls(digest_text, articles_data)
        logger.info(
            "Digest text generated for bot '%s' (%d chars, %d articles)",
            bot_id, len(digest_text), len(articles)
        )

    except Exception as e:
        logger.error("Digest text generation failed for bot '%s': %s", bot_id, str(e))
        return None

    # ── Step 3: Post-generation guardrail check ───────────────────────────
    guardrail_result = check_generated_post(digest_text, bot_id)
    if guardrail_result["is_blocked"]:
        logger.warning(
            "Digest post blocked by guardrails | category='%s' | bot='%s'",
            guardrail_result["category"], bot_id
        )
        return None

    # ── Step 4: Cover image (digest-specific prompt) ─────────────────────
    top_article = articles[0]
    image_url = _generate_digest_cover_image(articles_data, bot_id)

    # ── Step 5: Generate alternative headline for A/B testing ─────────────
    headline_b = _generate_headline_variant(digest_text, bot_id)

    # ── Step 6: Save to DB (linked to the top article) ────────────────────
    post = _save_post_to_db(
        article_id=top_article.id,
        bot_id=bot_id,
        content=digest_text,
        image_url=image_url,
        headline_b=headline_b,
    )

    if post:
        logger.info(
            "Digest post saved | post_id=%d | bot='%s' | articles=%d | has_image=%s",
            post.id, bot_id, len(articles), image_url is not None
        )

    return post


def _save_post_to_db(article_id: int, bot_id: str,
                      content: str, image_url: str | None,
                      headline_b: str | None = None) -> Post | None:
    """
    Saves a generated post to the posts table in the database.

    Args:
        article_id (int):        ID of the source article.
        bot_id (str):            ID of the bot that will publish this post.
        content (str):           The generated post text.
        image_url (str | None):  URL of the generated cover image, or None.
        headline_b (str | None): Alternative headline for A/B testing, or None.

    Returns:
        Post:  The newly created Post database object.
        None:  If saving to the database failed.
    """
    try:
        with get_session() as session:
            post = Post(
                article_id=article_id,
                bot_id=bot_id,
                content=content,
                image_url=image_url,
                headline_b=headline_b,
                status="pending_review",
                created_at=datetime.utcnow(),
            )
            session.add(post)
            session.flush()
            session.expunge(post)

        return post

    except Exception as e:
        logger.error(
            "Failed to save post to DB for article %d: %s",
            article_id, str(e)
        )
        return None
