"""
generator/prompts_astrology.py
───────────────────────────────
Prompt templates for the Daily Astrology Bot (Hindi/Hinglish posts).

What this file does:
  - Defines HOW Gemini should write daily panchang/astrology posts.
  - Input: today's tithi, nakshatra, and panchang data from Drik Panchang.
  - Output: a short, engaging Hinglish post with spiritual meaning,
    daily life insights, a remedy, and a CTA.

Post structure (for virality):
  Hook      → "Aaj ka tithi bahut powerful hai…"
  Meaning   → Why this tithi is spiritually significant
  Life angle → Real-world insight (career / health / relationships)
  Remedy    → Simple action (mantra, donation, ritual)
  CTA       → "Aaj yeh try karo"

Tone:
  - Hinglish (natural Hindi + English mix, like WhatsApp messages)
  - Warm, spiritual, and relatable — like advice from a wise elder
  - Short and punchy — 5 to 7 lines total
  - Emojis: 🌙 ✨ 🙏 🪔 🔮 used purposefully, not excessively
"""


# ── System Prompt ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Aap ek experienced Vedic astrology aur Jyotish writer hain jo ek popular Telegram channel ke liye daily panchang posts likhte hain.

Aapki writing style:
- Hinglish mein — Hindi aur English ka natural, warm mix (jaise koi wise dost WhatsApp pe likhe)
- Spiritual lekin grounded — readers ko feel ho ki yeh unki real life se connected hai
- Informative lekin readable — har section 3-4 lines, total 15-20 lines
- Emojis ka smart use: 🌙 ✨ 🙏 🪔 🔮 — meaningful, overdone nahi
- Engaging hook se shuru karein — reader ko pehli line mein hi pakad lena hai

Aapka audience:
- Hindu calendar aur astrology mein interested Indian urban audience
- Hinglish naturally samajhte hain
- Practical tips, remedies, aur daily guidance chahiye
- Spiritual content like karte hain lekin overcomplicated nahi

Aap hamesha ye rules follow karte hain:
- Sirf aaj ki tithi aur panchang data use karein — kuch bhi fabricate mat karein
- Remedy simple aur doable hona chahiye (ek mantra, ek chhota daan, ya ek easy ritual)
- CTA zaroor include karein — reader ko kuch karne ke liye motivate karein
- Hashtags zaroor include karein
- Output SIRF post content se shuru hona chahiye — koi preamble nahi ("Of course!", "Here is", "Sure!" etc.)
- Pehla character hona chahiye: 🌙
"""


# ── Post Format ────────────────────────────────────────────────────────────
# Rules:
#   - Section headings and sub-labels must be in *bold*
#   - Each point starts with "• " (bullet character) on a NEW LINE — never "-" or paragraphs
#   - Blank line between each section for visual breathing room
#   - Total post: 18-25 lines
POST_FORMAT = """
🌙 *Aaj ki Tithi: [Tithi name] | [Paksha] Paksha*
_[Nakshatra name] Nakshatra • [Yoga name] Yoga_

🔮 *Meaning:*
• [Tithi ki deity ya ruling energy — e.g. "Ekadashi → Bhagwan Vishnu ki tithi hai"]
• [Is tithi ka spiritual significance — kya vishesh cosmic energy hai aaj?]
• [Nakshatra ka influence — iska kya effect hai aaj ke din par?]

💡 *Daily Insight:*
• *Career/Work:* [Aaj kaam mein kya dhyan rakhein — ek sentence]
• *Relationships:* [Parivaar ya partner ke saath kaisa din rahega — ek sentence]
• *Health:* [Sehat ya energy level ke baare mein — ek sentence]
• *Finance:* [Paise ya decisions ke baare mein — ek sentence]

🪔 *Remedy:*
• *Kya karein:* [Remedy ka naam — mantra, daan, ya ritual]
• *Kyun karein:* [Is tithi ke liye yeh remedy kyun effective hai]
• *Kaise karein:* [Step-by-step — kya, kab, aur kaise — ghar mein 5 minute mein ho sake]

✨ *Tip of the Day:*
• [Aaj ke liye ek clear, actionable step — tithi energy se connected]
• [Encouraging closing line — reader ko motivate kare, jaise "Aaj ka din aapka hai! 🙏"]

#AstroChhayah #DailyPanchang #AajKiTithi #HinduCalendar #Astrology #VedicAstrology
"""


def build_prompt(title: str, summary: str, source_name: str, url: str) -> str:
    """
    Builds the complete prompt for generating today's panchang post.

    Takes today's panchang data (tithi, nakshatra, etc.) and builds
    a prompt that instructs Gemini to write an engaging Hinglish post
    in the exact format required.

    Args:
        title (str):       e.g. "Aaj ka Panchang — April 04, 2026"
        summary (str):     Panchang fields: "Tithi: Tritiya | Paksha: Shukla | Nakshatra: Rohini | ..."
        source_name (str): "Drik Panchang"
        url (str):         The source URL for today's panchang.

    Returns:
        str: The complete prompt string to send to Gemini.
    """
    prompt = f"""Aaj ka tithi-based daily astrology post likhein Telegram ke liye.

AAJKA PANCHANG DATA:
{summary}

Source: {source_name}

REQUIRED OUTPUT FORMAT (exactly follow karein):
{POST_FORMAT}

CONTENT RULES:
- Tithi aur Nakshatra dono header mein include karein
- Meaning mein tithi ki deity ya associated energy zaroor mention karein (e.g. Ekadashi → Vishnu, Ashtami → Durga)
- Daily Insight mein CHARON life areas cover karein — Career, Relationships, Health, Finance — har ek alag bullet mein
- Remedy mein teen alag bullets dein: "Kya karein", "Kyun karein", "Kaise karein"
- Tip of the Day mein 2 bullets: ek action, ek encouraging line
- Emojis exactly format ke according use karein: 🌙 🔮 💡 🪔 ✨
- Header mein _italic_ ke liye underscore (Telegram markdown)
- *bold* ke liye single asterisk (Telegram HTML markdown)
- Output SIRF 🌙 se shuru ho — koi preamble nahi

BULLET POINT FORMAT — STRICT RULE:
Har section mein EVERY point "• " (bullet character) se start hona chahiye aur APNI LINE pe hona chahiye.
Kabhi bhi "-" (hyphen) use mat karo — SIRF "•" bullet use karo.

❌ GALAT (bilkul mat karo):
🔮 *Meaning:*
Ekadashi Vishnu ji ki tithi hai. Yeh bahut powerful din hai. Rohini nakshatra ka aaj acha effect hai.

❌ YEH BHI GALAT (hyphen use mat karo):
- Ekadashi → Bhagwan Vishnu ki tithi hai

✅ SAHI (exactly aise likho):
🔮 *Meaning:*
• Ekadashi → Bhagwan Vishnu ki tithi hai
• Yeh din spiritual cleansing aur moksha ke liye bahut powerful hai
• Rohini Nakshatra aaj creativity aur stability ki energy deta hai

Do NOT write paragraph blocks. Do NOT use "-". Every single point = its own "• " bullet line."""
    return prompt


def build_image_prompt(title: str, summary: str) -> str:
    """
    Builds a spiritual cover image prompt for the daily panchang post.

    Creates a visually rich, temple-inspired image that evokes the
    energy of today's tithi — serene, sacred, and distinctly Indian.

    Args:
        title (str):   e.g. "Aaj ka Panchang — April 04, 2026"
        summary (str): Panchang data (used to pick visual theme).

    Returns:
        str: Image generation prompt string.
    """
    # Extract key panchang fields from summary for contextual image generation
    fields = {}
    if summary:
        for part in summary.split("|"):
            part = part.strip()
            if ":" in part:
                k, _, v = part.partition(":")
                fields[k.strip()] = v.strip()

    tithi     = fields.get("Tithi", "auspicious day")
    nakshatra = fields.get("Nakshatra", "")
    paksha    = fields.get("Paksha", "")
    festival  = fields.get("Festival", "")

    # Build contextual visual cues based on today's tithi and nakshatra
    # These guide the image model to produce a relevant, not generic, image
    tithi_lower = tithi.lower()
    if "ekadashi" in tithi_lower:
        focal_element = "a grand Vaishnava temple with Tulsi plant, conch shell, and Sudarshana Chakra"
        mood = "deeply devotional, serene, Vaishnava blue and gold"
    elif "amavasya" in tithi_lower or "chaturdashi" in tithi_lower:
        focal_element = "a dark sky with a thin crescent moon, oil lamps (diyas) floating on water, and marigold offerings"
        mood = "mystical, Shiva energy, deep indigo and silver"
    elif "purnima" in tithi_lower:
        focal_element = "a brilliant full moon reflected in still water, lotus flowers in full bloom, sacred Ganga ghats"
        mood = "radiant, auspicious, silver moonlight and white lotus"
    elif "tritiya" in tithi_lower or "trutiya" in tithi_lower:
        focal_element = "Devi Gauri standing on a lotus, golden jewelry, surrounded by flowers and soft morning light"
        mood = "feminine divine energy, saffron and pink, gentle and auspicious"
    elif "ashtami" in tithi_lower:
        focal_element = "Devi Durga in radiant warrior form, a lit havan kund, marigold garlands"
        mood = "powerful, fierce yet protective, deep red and gold"
    elif "navami" in tithi_lower:
        focal_element = "Lord Ram silhouette at sunrise over Ayodhya, with a golden bow and lotus throne"
        mood = "heroic, divine, golden dawn light"
    elif "chaturthi" in tithi_lower:
        focal_element = "Lord Ganesha seated on a lotus throne, modak in hand, surrounded by marigolds and a crescent moon"
        mood = "joyful, auspicious, golden and saffron"
    else:
        focal_element = "an oil lamp (diya) flame reflected in still water, lotus flowers, sacred mandala patterns"
        mood = "peaceful, divine, midnight blue and gold"

    nakshatra_hint = f"The nakshatra is {nakshatra} — incorporate subtle star constellation patterns." if nakshatra else ""
    festival_hint  = f"Today is {festival} — the image should subtly evoke this celebration." if festival else ""
    paksha_hint    = "The background sky should be very dark (Krishna Paksha — waning moon)." if "krishna" in paksha.lower() else "The background sky should be luminous (Shukla Paksha — waxing moon)."

    prompt = (
        f"Create a stunning, spiritual cover image for a Hindu panchang post.\n\n"
        f"TODAY'S CONTEXT:\n"
        f"- Tithi: {tithi}\n"
        f"- Paksha: {paksha}\n"
        f"- Nakshatra: {nakshatra}\n"
        f"{'- Festival: ' + festival if festival else ''}\n\n"
        f"VISUAL DIRECTION:\n"
        f"- Focal element: {focal_element}\n"
        f"- Mood: {mood}\n"
        f"- {paksha_hint}\n"
        f"- {nakshatra_hint}\n\n"
        "STYLE REQUIREMENTS:\n"
        "- Sacred Indian spiritual art — blend of Madhubani, Tanjore, and modern cinematic illustration\n"
        "- Color palette: Deep midnight blue/indigo sky, warm gold and saffron accents, lotus pink highlights\n"
        "- Composition: Strong central focal point with layered atmospheric depth — very cinematic\n"
        "- Lighting: Soft divine glow (golden from below, cool moonlight from above)\n"
        "- Include: Sacred geometry, subtle mandala patterns in background\n"
        "- Ultra-high detail, photorealistic spiritual art quality\n"
        "- NO text, watermarks, human faces, logos, or UI elements\n"
        "- 1024x1024 resolution"
    )
    return prompt
