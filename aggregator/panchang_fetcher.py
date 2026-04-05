"""
aggregator/panchang_fetcher.py
───────────────────────────────
Fetches today's Hindu Panchang (tithi, nakshatra, yoga, etc.) and creates
an Article record in the DB for the Astrology bot to use.

How it works (two-layer approach):
  Layer 1 — Scrape: Authenticate to Drik Panchang using session cookies
             stored in .env (DRIK_SESSION_ID + DRIK_ACCESS_TOKEN) and
             extract structured panchang data via CSS class parsing.
  Layer 2 — Calculate: If scraping fails (cookies expired, network error),
             calculate tithi/nakshatra/yoga astronomically using the `ephem`
             library (Sun + Moon positions). More accurate than asking AI to
             guess, which caused inconsistent tithis across generations.

Cookie setup (one-time, lasts ~1 year):
  1. Open Chrome → drikpanchang.com → Log in with Google
  2. F12 → Application → Cookies → www.drikpanchang.com
  3. Copy _DRIK_SESSION_ID and drik_access_token values to .env

Why two layers?
  - Drik Panchang is the most authoritative panchang source (includes festival
    names, exact tithi end times, muhurtas).
  - ephem is the reliable fallback when cookies expire or the site is down.
  - Never ask the AI to guess — it hallucinates inconsistently.
"""

import logging
import math
import re
from datetime import datetime, timezone, timedelta

import ephem
import requests
from bs4 import BeautifulSoup

from config.settings import settings
from db.database import get_session
from db.models import Article

logger = logging.getLogger(__name__)

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Drik Panchang daily panchang URL
DRIK_URL = "https://www.drikpanchang.com/panchang/day-panchang.html"
SOURCE_NAME = "Drik Panchang"

# CSS class that wraps the main panchang table on Drik Panchang
PANCHANG_CARD_CLASS = "dpCorePanchangCardWrapper"

# 30 tithi names (index 0-14 = Shukla Pratipada→Purnima, 15-29 = Krishna Pratipada→Amavasya)
TITHI_NAMES = [
    "Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami",
    "Shashthi", "Saptami", "Ashtami", "Navami", "Dashami",
    "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Purnima",
    "Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami",
    "Shashthi", "Saptami", "Ashtami", "Navami", "Dashami",
    "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Amavasya",
]

# 27 nakshatra names (each spans 13°20' of sidereal ecliptic)
NAKSHATRA_NAMES = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni",
    "Uttara Phalguni", "Hasta", "Chitra", "Swati", "Vishakha",
    "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha",
    "Shravana", "Dhanishtha", "Shatabhisha", "Purva Bhadrapada",
    "Uttara Bhadrapada", "Revati",
]

# 27 yoga names
YOGA_NAMES = [
    "Vishkambha", "Preeti", "Ayushman", "Saubhagya", "Shobhana",
    "Atiganda", "Sukarma", "Dhriti", "Shoola", "Ganda", "Vriddhi",
    "Dhruva", "Vyaghata", "Harshana", "Vajra", "Siddhi", "Vyatipata",
    "Variyan", "Parigha", "Shiva", "Siddha", "Sadhya", "Shubha",
    "Shukla", "Brahma", "Indra", "Vaidhriti",
]


def get_today_panchang_article() -> "Article | None":
    """
    Fetches today's panchang and returns it as an Article DB object.

    Tries authenticated Drik Panchang scraping first. Falls back to
    astronomical calculation (ephem) if cookies are missing or expired.

    Returns:
        Article: A saved Article object with panchang data in summary field.
        None:    If the DB save failed.
    """
    now_ist      = datetime.now(IST)
    date_str     = now_ist.strftime("%d/%m/%Y")   # URL format: DD/MM/YYYY e.g. 05/04/2026
    display_date = now_ist.strftime("%B %d, %Y")  # Display: April 05, 2026

    # Layer 1: Authenticated scrape from Drik Panchang
    panchang_summary = None
    if settings.DRIK_SESSION_ID and settings.DRIK_ACCESS_TOKEN:
        panchang_summary = _scrape_drik_panchang(date_str)
        if panchang_summary:
            logger.info("Panchang scraped from Drik Panchang for %s", display_date)
    else:
        logger.warning(
            "DRIK_SESSION_ID / DRIK_ACCESS_TOKEN not set in .env — skipping scrape."
        )

    # Layer 2: Astronomical calculation fallback
    if not panchang_summary:
        logger.warning(
            "Drik Panchang scraping failed for %s — using ephem calculation.", display_date
        )
        panchang_summary = _calculate_panchang(now_ist)
        logger.info("Calculated panchang: %s", panchang_summary)

    title = f"Aaj ka Panchang — {display_date}"
    url   = f"{DRIK_URL}?date={date_str}"
    return _save_panchang_article(title, panchang_summary, SOURCE_NAME, url)


def _alert_cookie_expiry() -> None:
    """
    Sends a Telegram alert to the astrology reviewer when Drik Panchang
    cookies have expired. The bot will still work (falls back to ephem),
    but the reviewer should refresh the cookies for accurate festival data.
    """
    try:
        import requests as _requests
        chat_id = settings.TELEGRAM_ASTROLOGY_REVIEWER_CHAT_ID or settings.TELEGRAM_REVIEWER_CHAT_ID
        token   = settings.TELEGRAM_ASTROLOGY_BOT_TOKEN
        if not chat_id or not token:
            return
        message = (
            "⚠️ *Drik Panchang Cookie Expired*\n\n"
            "Aaj ka panchang scraping fail hua — session cookies expire ho gayi hain.\n\n"
            "*Kya karein:*\n"
            "1. Chrome mein drikpanchang.com kholo\n"
            "2. Google se login karo\n"
            "3. F12 → Application → Cookies → www.drikpanchang.com\n"
            "4. `_DRIK_SESSION_ID` aur `drik_access_token` copy karo\n"
            "5. `.env` file mein update karo aur bot restart karo\n\n"
            "_Tab tak bot ephem calculation use karega (tithi accurate rahega)._"
        )
        _requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
        logger.info("Cookie expiry alert sent to reviewer chat.")
    except Exception as e:
        logger.warning("Could not send cookie expiry alert: %s", e)


def _scrape_drik_panchang(date_str: str) -> "str | None":
    """
    Scrapes panchang data from Drik Panchang using stored session cookies.

    Uses the dpCorePanchangCardWrapper CSS class to locate the main
    panchang table, then extracts each field from dpTableRow elements.

    Args:
        date_str (str): Date in MM/DD/YYYY format for the URL parameter.

    Returns:
        str:  Panchang fields as a pipe-separated string, e.g.
              "Tithi: Tritiya | Paksha: Krishna | Nakshatra: Anuradha | ..."
        None: If scraping fails (cookies expired, network error, HTML changed).
    """
    url = f"{DRIK_URL}?date={date_str}"
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-IN,en;q=0.9",
                "Referer": "https://www.drikpanchang.com/",
            },
            cookies={
                "_DRIK_SESSION_ID": settings.DRIK_SESSION_ID,
                "drik_access_token": settings.DRIK_ACCESS_TOKEN,
                "drik-geoname-id":   settings.DRIK_GEONAME_ID,
                "drik-arithmetic":   "modern",
                "drik-ayanamsha-type": "chitra-paksha",
            },
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning("HTTP request to Drik Panchang failed: %s", e)
        return None

    try:
        soup = BeautifulSoup(response.text, "lxml")

        # Detect login redirect — cookies may have expired
        if "sign in" in soup.get_text().lower():
            logger.warning(
                "Drik Panchang returned login page — session cookies may have expired. "
                "Re-copy DRIK_SESSION_ID and DRIK_ACCESS_TOKEN from your browser."
            )
            _alert_cookie_expiry()
            return None

        # Find the main panchang card
        card = soup.find(class_=PANCHANG_CARD_CLASS)
        if not card:
            logger.warning("Could not find panchang card (class=%s) on page.", PANCHANG_CARD_CLASS)
            return None

        fields = {}

        # Each dpTableRow has 4 cells: [label1][value1][label2][value2]
        # Some rows have empty labels (continuation of previous field — we skip those)
        for row in card.find_all(class_="dpTableRow"):
            cells = row.find_all(class_=re.compile(r"dpTableCell"))
            if len(cells) < 2:
                continue

            def clean(text: str) -> str:
                """Strip tooltip icons (ⓘ and similar), whitespace, and 'upto HH:MM' suffixes."""
                text = text.split(" upto ")[0]
                # Remove any non-ASCII characters (tooltip icons like ⓘ render as junk)
                text = text.encode("ascii", "ignore").decode("ascii")
                return text.replace("?", "").strip()

            # Process first label/value pair (cells 0 + 1)
            label1 = clean(cells[0].get_text(separator=" ", strip=True))
            value1 = clean(cells[1].get_text(separator=" ", strip=True))
            if label1 and value1 and label1 not in fields:
                fields[label1] = value1

            # Process second label/value pair (cells 2 + 3) if present
            if len(cells) >= 4:
                label2 = clean(cells[2].get_text(separator=" ", strip=True))
                value2 = clean(cells[3].get_text(separator=" ", strip=True))
                if label2 and value2 and label2 not in fields:
                    fields[label2] = value2

        # Extract Sunrise and Sunset using regex from the page text
        page_text = soup.get_text(separator=" ", strip=True)
        sunrise_match = re.search(r"Sunrise\s+(\d{1,2}:\d{2}\s*[AP]M)", page_text)
        sunset_match  = re.search(r"Sunset\s+(\d{1,2}:\d{2}\s*[AP]M)", page_text)
        if sunrise_match:
            fields["Sunrise"] = sunrise_match.group(1)
        if sunset_match:
            fields["Sunset"] = sunset_match.group(1)

        # Grab festival/vrat from day events section
        for elem in soup.find_all(class_="dpTableCell"):
            txt = elem.get_text(strip=True).encode("ascii", "ignore").decode("ascii").replace("?", "").strip()
            if txt and any(kw in txt for kw in ["Nakshatram", "Navratri", "Ekadashi", "Purnima", "Amavasya"]):
                if "Festival" not in fields:
                    fields["Festival"] = txt
                    break

        if not fields:
            logger.warning("No panchang fields extracted from Drik Panchang page.")
            return None

        parts = [f"{k}: {v}" for k, v in fields.items()]
        return " | ".join(parts)

    except Exception as e:
        logger.warning("Failed to parse Drik Panchang HTML: %s", e)
        return None


def _calculate_panchang(dt: datetime) -> str:
    """
    Calculates tithi, paksha, nakshatra, and yoga astronomically using ephem.

    Uses geocentric ecliptic longitudes with Lahiri ayanamsa correction so
    nakshatra and yoga match the Hindu sidereal (Nirayana) system used by
    Drik Panchang. Tithi is ayanamsa-independent (cancels in subtraction).

    Args:
        dt (datetime): The IST datetime to calculate for.

    Returns:
        str: Panchang fields as a pipe-separated string.
    """
    utc_dt    = dt.astimezone(timezone.utc)
    ephem_date = ephem.Date(utc_dt.strftime("%Y/%m/%d %H:%M:%S"))

    sun  = ephem.Sun(ephem_date)
    moon = ephem.Moon(ephem_date)

    ecl_sun  = ephem.Ecliptic(sun,  epoch=ephem_date)
    ecl_moon = ephem.Ecliptic(moon, epoch=ephem_date)
    sun_lon  = math.degrees(ecl_sun.lon)
    moon_lon = math.degrees(ecl_moon.lon)

    # Lahiri ayanamsa for sidereal (Nirayana) conversion
    year     = dt.year + dt.timetuple().tm_yday / 365.0
    ayanamsa = 23.15 + (year - 1900) * 0.013611

    # Sidereal longitudes (for nakshatra and yoga)
    sun_sid  = (sun_lon  - ayanamsa) % 360
    moon_sid = (moon_lon - ayanamsa) % 360

    # Tithi — ayanamsa cancels out, use tropical elongation directly
    elongation  = (moon_lon - sun_lon) % 360
    tithi_index = int(elongation / 12)
    tithi_name  = TITHI_NAMES[tithi_index]
    paksha      = "Shukla" if tithi_index < 15 else "Krishna"
    tithi_num   = (tithi_index % 15) + 1

    # Nakshatra — use sidereal Moon longitude
    nakshatra = NAKSHATRA_NAMES[int(moon_sid / (360 / 27)) % 27]

    # Yoga — use sidereal Sun + Moon sum
    yoga_index = int(((sun_sid + moon_sid) % 360) / (360 / 27)) % 27
    yoga       = YOGA_NAMES[yoga_index]

    # Weekday
    vara_names = ["Somavara", "Mangalavara", "Budhavara", "Guruvara",
                  "Shukravara", "Shanivara", "Ravivara"]
    vara = vara_names[dt.weekday() % 7]

    parts = [
        f"Tithi: {tithi_name} ({tithi_num})",
        f"Paksha: {paksha}",
        f"Nakshatra: {nakshatra}",
        f"Yoga: {yoga}",
        f"Vara: {vara}",
        f"Note: Calculated astronomically for {dt.strftime('%B %d, %Y')} IST",
    ]
    return " | ".join(parts)


def _save_panchang_article(
    title: str, summary: str, source_name: str, url: str
) -> "Article | None":
    """
    Saves the panchang data as an Article record in the database.

    Checks if today's panchang article already exists. If it does and the
    new summary contains richer data (scraped vs calculated), updates it.

    Args:
        title (str):       e.g. "Aaj ka Panchang — April 05, 2026"
        summary (str):     Panchang fields string.
        source_name (str): "Drik Panchang"
        url (str):         The source URL.

    Returns:
        Article: The saved (or updated) Article object.
        None:    If the DB operation failed.
    """
    try:
        with get_session() as session:
            existing = (
                session.query(Article)
                .filter_by(bot_id="astrology", title=title)
                .first()
            )
            if existing:
                # Update summary if we now have better (scraped) data
                if existing.summary != summary:
                    existing.summary = summary
                    session.flush()   # Write to transaction BEFORE expunge so commit includes it
                    logger.info(
                        "Updated panchang article (id=%d) with fresh data.", existing.id
                    )
                session.expunge(existing)
                return existing

            article = Article(
                bot_id="astrology",
                title=title,
                summary=summary,
                source_name=source_name,
                url=url,
                status="new",
                published_at=datetime.utcnow(),
                virality_score=80.0,
            )
            session.add(article)
            session.flush()
            session.expunge(article)

        logger.info("Panchang article saved to DB: '%s'", title)
        return article

    except Exception as e:
        logger.error("Failed to save panchang article to DB: %s", e)
        return None
