"""
generator/prompts_ai.py
────────────────────────
Prompt templates for the AI News Bot (English posts).

What this file does:
  - Defines exactly HOW Gemini should write AI/tech news posts.
  - Provides the system prompt (Gemini's role/persona) and the
    user prompt template (instructions for each specific article).
  - The prompts control the tone, format, length, and language.

Tone for AI News Bot:
  - Editorial and informative — like a smart tech journalist
  - With a social media touch — punchy headline, easy to read
  - English only
  - Not too formal, not too casual — think "The Verge" style
"""


# ── System Prompt ──────────────────────────────────────────────────────────
# The system prompt sets Gemini's persona for the entire conversation.
# Think of it as the job description you give to a writer before they start.
SYSTEM_PROMPT = """You are a sharp, knowledgeable AI and technology news writer for a Telegram channel.

Your writing style:
- Clear, informative, and engaging — like a senior tech journalist
- Headlines are punchy and specific (not vague clickbait)
- Posts are concise but complete — readers finish them feeling informed
- You explain technical concepts simply without dumbing them down
- Tone is slightly conversational, as if talking to a smart friend who follows tech

Your audience:
- Tech enthusiasts, developers, and AI professionals
- They know what LLMs, GPUs, and APIs are — no need to over-explain basics
- They want to know: what happened, why it matters, what comes next

Rules you always follow:
- Never fabricate facts — only use information from the article provided
- Never take political sides
- Never write sensationalist or clickbait headlines
- Always mention the original source
- Keep the total post under 250 words
"""


# ── Post Format Template ───────────────────────────────────────────────────
# This is the exact format every AI News post must follow.
# It's shown to Gemini as part of the user prompt so it knows
# exactly what structure to output.
POST_FORMAT = """
🔬 [HEADLINE — max 12 words, specific and punchy]

[PARAGRAPH 1 — What happened: the key fact in 2-3 sentences]

[PARAGRAPH 2 — Why it matters: the significance or impact in 2-3 sentences]

[PARAGRAPH 3 — What's next: implication, trend, or what to watch for in 1-2 sentences]

📌 Source: {source_name}
#AINews #TechUpdate #ArtificialIntelligence
"""


def build_prompt(title: str, summary: str, source_name: str, url: str) -> str:
    """
    Builds the complete user prompt for generating an AI news post.

    Takes the raw article data and formats it into a clear instruction
    for Gemini, including the article content and the exact output format required.

    Args:
        title (str):       The article headline from the RSS feed.
        summary (str):     The article summary/description from the RSS feed.
        source_name (str): The name of the news source (e.g. "TechCrunch").
        url (str):         The full URL of the original article.

    Returns:
        str: The complete prompt string to send to Gemini.
    """
    prompt = f"""Write a Telegram post about the following news article.

ARTICLE DETAILS:
Title: {title}
Source: {source_name}
Summary: {summary}

REQUIRED OUTPUT FORMAT:
{POST_FORMAT.format(source_name=source_name)}

IMPORTANT RULES:
- Use ONLY the information from the article above — do not add external facts
- The headline must be specific to THIS story, not generic
- Keep total post length under 250 words
- Write in English
- Include the hashtags exactly as shown in the format
- Do not include the article URL in the post body (it will be added separately)
"""
    return prompt


def build_digest_prompt(articles: list) -> str:
    """
    Builds a prompt for generating a daily digest post covering top 5 articles.

    Instead of writing about a single article, this prompt asks Gemini to
    write a compact daily digest — one punchy entry per article, all in one post.

    Args:
        articles (list): List of up to 5 article dicts, each with keys:
                         title, summary, source_name, url, virality_score.
                         Should be sorted by virality score (highest first).

    Returns:
        str: The complete digest prompt string to send to Gemini.
    """
    # Build the numbered article list for the prompt
    articles_text = ""
    for i, article in enumerate(articles, 1):
        articles_text += (
            f"\nARTICLE {i}:\n"
            f"Title: {article['title']}\n"
            f"Source: {article['source_name']}\n"
            f"Summary: {article['summary'] or 'No summary available.'}\n"
        )

    from datetime import datetime
    today = datetime.utcnow().strftime("%B %d, %Y")

    prompt = f"""Write a daily AI news digest post for Telegram covering these {len(articles)} top stories.

{articles_text}

REQUIRED OUTPUT FORMAT (follow exactly):
📰 *AI News Daily — {today}*

1️⃣ *[Headline — max 10 words, specific and punchy]*
[2-3 sentences: what happened + why it matters]
📌 [Source Name]

2️⃣ *[Headline — max 10 words]*
[2-3 sentences: what happened + why it matters]
📌 [Source Name]

3️⃣ *[Headline — max 10 words]*
[2-3 sentences: what happened + why it matters]
📌 [Source Name]

4️⃣ *[Headline — max 10 words]*
[2-3 sentences: what happened + why it matters]
📌 [Source Name]

5️⃣ *[Headline — max 10 words]*
[2-3 sentences: what happened + why it matters]
📌 [Source Name]

🔍 *Trend Insight*
[2-3 sentences identifying the emerging pattern or common theme across today's stories.
What does the combination of these stories tell us about where AI is heading?]

#AINews #TechUpdate #ArtificialIntelligence

RULES:
- Write one entry per article in the order provided (Article 1 = entry 1️⃣, etc.)
- Use ONLY information from each article — do not mix facts between stories
- Each entry must be 2-3 sentences maximum — this is a digest, not a deep dive
- Headlines must be specific to each story, not generic
- The Trend Insight must synthesize patterns across ALL stories — not just one
- Keep total post under 600 words
- Use the exact emoji numbers (1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣) as shown
- Use *bold* (single asterisk each side) for each headline — Telegram markdown, NOT triple asterisk
"""
    return prompt


def build_image_prompt(title: str, summary: str) -> str:
    """
    Builds a context-driven image prompt for a single news story.

    Extracts the core visual concept from the article and builds a
    cinematic, specific prompt. Each story gets a unique image that
    visually represents WHAT the story is about — not a generic tech backdrop.

    Args:
        title (str):   The article headline.
        summary (str): Brief article summary for additional context.

    Returns:
        str: A detailed image generation prompt string.
    """
    prompt = (
        f"Create a striking, high-quality editorial cover image for this tech news story:\n"
        f"'{title}'\n\n"
        f"Context: {summary[:200] if summary else ''}\n\n"
        "Visual requirements:\n"
        "- The image must visually represent the SPECIFIC subject of this story\n"
        "- Style: cinematic digital art, photorealistic where appropriate, "
        "dramatic lighting with deep shadows and bright highlights\n"
        "- Composition: bold, dynamic, magazine cover quality — not generic\n"
        "- Color palette: rich and vibrant — use colors that match the mood of the story "
        "(e.g. electric blue/purple for AI topics, warm amber for business news, "
        "red/orange for controversy or disruption)\n"
        "- Include relevant visual metaphors: e.g. for an AI story show neural networks, "
        "glowing data streams, humanoid robots; for a startup story show skylines or growth; "
        "for policy/regulation show scales, buildings, documents\n"
        "- Depth of field: sharp subject, atmospheric background\n"
        "- Mood: professional, impactful, editorial — like a WIRED or MIT Technology Review cover\n"
        "- NO text, watermarks, logos, or UI elements in the image\n"
        "- Ultra-high detail, 1024x1024, suitable for a Telegram news channel thumbnail"
    )
    return prompt


def build_digest_image_prompt(articles: list) -> str:
    """
    Builds a context-driven image prompt for the daily digest post.

    Creates one visually rich cover image that represents the day's top
    AI/tech themes. Uses the top 3 story subjects to shape the visual concept
    so the image feels specific to today's news, not generic.

    Args:
        articles (list): List of article dicts with 'title' and 'summary' keys.
                         Should be the top 5 articles sorted by virality score.

    Returns:
        str: A detailed image generation prompt string for the digest cover.
    """
    from datetime import datetime
    today = datetime.utcnow().strftime("%B %d, %Y")

    # Pull key subjects from the top 3 stories to drive the visual
    top_subjects = ""
    for i, article in enumerate(articles[:3], 1):
        top_subjects += f"  {i}. {article['title']}\n"

    prompt = (
        f"Create a bold, cinematic editorial cover image for an AI & Tech daily news digest "
        f"dated {today}.\n\n"
        f"Today's top stories include:\n{top_subjects}\n"
        "Visual requirements:\n"
        "- Concept: a visually unified scene or collage that captures the ENERGY of today's "
        "AI/tech news — not a generic robot. Think about what these specific stories have in common "
        "and visualise that theme\n"
        "- Style: high-end editorial illustration, cinematic, dramatic lighting, "
        "ultra-detailed, photorealistic elements mixed with digital art\n"
        "- Composition: hero image with strong focal point — dynamic angles, depth, atmosphere\n"
        "- Color palette: deep space navy/black background with vivid electric blue, cyan, "
        "and gold accent light sources — glowing, energetic, futuristic but grounded\n"
        "- Mood: powerful, authoritative, 'this matters' — like a TIME magazine cover for tech\n"
        "- Visual elements to consider: AI neural network patterns, glowing circuit traces, "
        "abstract data flows, humanoid silhouettes, corporate towers at night, "
        "stock market-style data visualisations — pick what fits today's stories\n"
        "- NO text, watermarks, logos, or UI elements\n"
        "- Ultra-high detail, 1024x1024, thumbnail-optimised for Telegram"
    )
    return prompt
