"""
generator/prompts_astrology.py
───────────────────────────────
Prompt templates for the Daily Astrology Bot (Hindi posts).

STATUS: PLACEHOLDER — This bot is inactive in Phase 1.
        Fill in the prompts below when you are ready to activate it.

What this bot will do when activated:
  - Generate daily horoscope / panchang updates in Hindi
  - Based on the Hindu calendar (tithi, nakshatra, festivals)
  - One post per day at 6:00 AM

To activate this bot:
  1. Set "active": true in config/bots.json
  2. Fill in the SYSTEM_PROMPT and POST_FORMAT below
  3. Add sources to config/sources_astrology.json
  4. Add TELEGRAM_ASTROLOGY_BOT_TOKEN to your .env file
"""


# ── System Prompt (TO BE FILLED IN) ───────────────────────────────────────
SYSTEM_PROMPT = """
TODO: Write the system prompt for the Astrology bot here.

Example guidance:
  - Role: A knowledgeable Jyotish (Vedic astrology) writer
  - Language: Pure Hindi
  - Tone: Respectful, spiritual, informative
  - Coverage: Daily panchang, tithi, nakshatra, auspicious times, festivals
"""


# ── Post Format Template (TO BE FILLED IN) ────────────────────────────────
POST_FORMAT = """
TODO: Define the post format for the Astrology bot here.

Suggested format:
🕉️ [Aaj ka Panchang — Date]

📅 Tithi: ...
⭐ Nakshatra: ...
🌅 Shubh Muhurat: ...

[2-3 sentences about today's astrological significance]

#DailyPanchang #HinduCalendar #Astrology
"""


def build_prompt(title: str, summary: str, source_name: str, url: str) -> str:
    """
    Builds the prompt for generating a daily astrology post.

    TODO: Implement this function when the Astrology bot is activated.

    Args:
        title (str):       Article/source title.
        summary (str):     Article summary or panchang data.
        source_name (str): Source name.
        url (str):         Source URL.

    Returns:
        str: The complete prompt string to send to Gemini.
    """
    # Placeholder — implement when bot is activated
    return f"Write a daily astrology post in Hindi based on: {title}. {summary}"


def build_image_prompt(title: str, summary: str) -> str:
    """
    Builds an image prompt for the daily astrology post.

    TODO: Implement this function when the Astrology bot is activated.

    Args:
        title (str):   Title or date.
        summary (str): Panchang summary.

    Returns:
        str: Image generation prompt string.
    """
    return (
        "A serene, spiritual Indian astrology illustration. "
        "Style: mandala patterns, deep blue and gold colours, "
        "stars and planets, sacred geometry. No text. 1024x1024."
    )
