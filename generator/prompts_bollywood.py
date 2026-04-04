"""
generator/prompts_bollywood.py
───────────────────────────────
Prompt templates for the Bollywood Buzz Bot (Hindi/Hinglish posts).

What this file does:
  - Defines HOW Gemini should write Bollywood entertainment posts.
  - Language: Hindi mixed with Hinglish (Hindi + English blend)
  - Tone: Conversational, engaging, credible gossip — not tabloid
  - Format: Same 3-paragraph structure as AI posts, but in Hindi/Hinglish

What is Hinglish?
  - A natural mix of Hindi and English used in everyday Indian conversation
  - Example: "Shah Rukh Khan ka naya film ka trailer drop ho gaya!"
    (Shah Rukh Khan's new film's trailer has dropped!)
  - It feels natural and relatable to the Indian urban audience
"""


# ── System Prompt ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Aap ek experienced Bollywood entertainment news writer hain jo ek popular Telegram channel ke liye likhte hain.

Aapki writing style:
- Hindi aur Hinglish ka natural mix — jaise dost ko WhatsApp pe likhte hain
- Engaging aur conversational — reader ko lagey ki koi interesting baat bata raha hai
- Credible aur factual — sirf article mein diya gaya information use karein
- Thoda dramatic lekin exaggerated nahi — real gossip vibe
- Formal nahi, lekin unprofessional bhi nahi

Aapka audience:
- Bollywood fans jo latest news aur gossip follow karte hain
- Urban Indian audience jo Hindi aur English dono jaante hain
- Inhe chahiye: kya hua, kyun important hai, aur aage kya hoga

Aap hamesha ye rules follow karte hain:
- Sirf article ki verified information use karein — kuch bhi fabricate mat karein
- Unverified accusations ya rumors ko fact ki tarah mat likhein
- Post 250 words se zyada nahi hona chahiye
- Hashtags zaroor include karein
- Source ka naam mention karein
"""


# ── Post Format Template ───────────────────────────────────────────────────
POST_FORMAT = """
🎬 [HEADLINE — Hinglish mein, max 12 words, catchy aur specific]

[PARAGRAPH 1 — Kya hua: main news 2-3 sentences mein Hindi/Hinglish mein]

[PARAGRAPH 2 — Kyun important hai: context ya background 2-3 sentences mein]

[PARAGRAPH 3 — Aage kya: next step ya expectation 1-2 sentences mein]

📌 Source: {source_name}
#Bollywood #BollywoodNews #Entertainment
"""


def build_prompt(title: str, summary: str, source_name: str, url: str) -> str:
    """
    Builds the complete user prompt for generating a Bollywood post in Hindi/Hinglish.

    Args:
        title (str):       The article headline from the RSS feed.
        summary (str):     The article summary/description from the RSS feed.
        source_name (str): The name of the news source (e.g. "Bollywood Hungama").
        url (str):         The full URL of the original article.

    Returns:
        str: The complete prompt string to send to Gemini.
    """
    prompt = f"""Neeche diye gaye news article ke baare mein ek Telegram post likhein.

ARTICLE DETAILS:
Title: {title}
Source: {source_name}
Summary: {summary}

REQUIRED OUTPUT FORMAT:
{POST_FORMAT.format(source_name=source_name)}

IMPORTANT RULES:
- Sirf article mein diya gaya information use karein — bahar se kuch add mat karein
- Headline is specific story ke baare mein hona chahiye — generic mat likhein
- Total post 250 words se zyada nahi hona chahiye
- Hindi aur Hinglish ka natural mix use karein
- Hashtags bilkul format ke according likhein
- Article ka URL post body mein mat daalein
"""
    return prompt


def build_image_prompt(title: str, summary: str) -> str:
    """
    Builds a prompt for generating a cover image for the Bollywood post.

    Creates a vibrant, Bollywood-style image description suitable
    for an entertainment news Telegram channel.

    Args:
        title (str):   The article headline.
        summary (str): Brief article summary.

    Returns:
        str: An image generation prompt string.
    """
    prompt = (
        f"A vibrant, colourful Bollywood entertainment news illustration for: '{title}'. "
        "Style: bright colours, cinematic feel, Indian film aesthetic, "
        "golden and red accents, glamorous atmosphere. No text overlays. "
        "Suitable for an entertainment Telegram channel. High quality, 1024x1024."
    )
    return prompt
