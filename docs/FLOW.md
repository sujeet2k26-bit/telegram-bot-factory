# AI News Bot — Complete Architecture & Flow

> How the entire system works, from fetching news to publishing on Telegram.

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AI NEWS BOT SYSTEM                               │
│                                                                         │
│   INTERNET                   YOUR MACHINE                  TELEGRAM     │
│                                                                         │
│  ┌──────────┐   fetch    ┌──────────────┐   publish   ┌─────────────┐  │
│  │ RSS Feeds│──────────▶│              │────────────▶│ @ai26news   │  │
│  │ (30+     │            │   PIPELINE   │             │  channel    │  │
│  │ sources) │            │              │             └─────────────┘  │
│  └──────────┘            │  SQLite DB   │                              │
│                          │  + Gemini AI │   review    ┌─────────────┐  │
│  ┌──────────┐   fetch    │              │────────────▶│  Reviewer   │  │
│  │Drik      │──────────▶│              │◀────────────│  Chat       │  │
│  │Panchang  │            └──────────────┘  approve/  └─────────────┘  │
│  │(Astrology│                               reject                     │
│  └──────────┘                                                          │
│                                                                         │
│  ┌──────────┐            ┌──────────────┐             ┌─────────────┐  │
│  │Euri API  │◀──────────│  Gemini 2.5  │             │@bollywood   │  │
│  │(euron.one│           │  Pro (text)  │             │  channel    │  │
│  │)         │──────────▶│  + Image     │             └─────────────┘  │
│  └──────────┘  response │  model       │                              │
│                          └──────────────┘             ┌─────────────┐  │
│                                                        │@astrochhayah│  │
│                                                        │  channel    │  │
│                                                        └─────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Main Pipeline — Step by Step

This is the journey of a single news story from the internet to Telegram.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         MAIN PIPELINE FLOW                              │
└─────────────────────────────────────────────────────────────────────────┘

  STEP 1 — FETCH (every 6 hours, 6:00 AM IST)
  ┌──────────────────────────────────────────────────────────────────────┐
  │  aggregator/rss_fetcher.py                                           │
  │                                                                      │
  │  For each source in sources_ai.json / sources_bollywood.json:        │
  │    → feedparser.parse(rss_url)          # read the RSS XML           │
  │    → extract: title, url, summary, published_at, source_name        │
  │    → check: is article < 48 hours old?  # skip old news             │
  │    → check: is URL already in DB?       # skip duplicates           │
  │    → save Article to SQLite DB          # status = 'new'            │
  └──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  STEP 2 — GUARDRAIL CHECK (pre-generation)
  ┌──────────────────────────────────────────────────────────────────────┐
  │  guardrails/content_filter.py                                        │
  │                                                                      │
  │  Run check_article() on each new article:                            │
  │    → scan title + summary for blocked keywords                       │
  │    → categories checked:                                             │
  │        ✗ Hate speech / communal targeting                            │
  │        ✗ Sexual / adult content                                      │
  │        ✗ Graphic violence                                            │
  │        ✗ Political propaganda / elections                            │
  │        ✗ Unverified celebrity defamation                            │
  │        ✗ Clickbait from non-trusted sources                         │
  │    → AI relevance filter (AI News only):                             │
  │        Hacker News / Reddit articles must contain AI keywords        │
  │                                                                      │
  │  PASS → article.status = 'scored'                                   │
  │  FAIL → article.status = 'blocked', log to guardrail_violations.log │
  └──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  STEP 3 — VIRALITY SCORING
  ┌──────────────────────────────────────────────────────────────────────┐
  │  scoring/virality.py                                                 │
  │                                                                      │
  │  For each article that passed guardrails:                            │
  │                                                                      │
  │  RAW SCORE (max 80):                                                 │
  │    recency_score     = last 6h→30,  12h→20, 24h→10, 48h→0          │
  │    source_overlap    = same story in 3+ sources→30, 2 sources→15    │
  │    keyword_weight    = 3+ trending keywords→20, 1-2 keywords→5-10   │
  │                                                                      │
  │  × SOURCE WEIGHT MULTIPLIER:                                         │
  │    ai_official  (OpenAI, Anthropic, Google AI)  → ×1.5             │
  │    ai_research  (ArXiv, MIT, Papers with Code)  → ×1.3             │
  │    ai_newsletter (TLDR AI, The Rundown)         → ×1.2             │
  │    ai_technology (TechCrunch, The Verge)        → ×1.0  (baseline) │
  │    ai_community  (Hacker News, Reddit)          → ×0.7             │
  │                                                                      │
  │  FINAL SCORE = raw_score × multiplier                               │
  └──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  STEP 4 — ARTICLE SELECTION (3 diversity caps applied in order)
  ┌──────────────────────────────────────────────────────────────────────┐
  │  scoring/virality.py  +  scoring/fallback.py                         │
  │                                                                      │
  │  PRIMARY PATH (score ≥ 60):                                          │
  │    Sort articles by score, then apply caps:                          │
  │    Cap 1: No exact duplicate titles (same title from 2 sources)     │
  │    Cap 2: Max 2 articles per source (no single source dominates)    │
  │    Cap 3: Max 2 articles per topic/movie (Bollywood flood guard)    │
  │            → uses keyword overlap: "Dhurandhar" shared = same topic │
  │    Pick top 5 → article.status = 'selected'                         │
  │                                                                      │
  │  FALLBACK PATH (no article scores ≥ 60):                            │
  │    Same 3 caps applied but ignores the threshold                    │
  │    Pick best available → article.status = 'selected_fallback'       │
  │    Post still goes through human review                              │
  └──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  STEP 5 — AI GENERATION (7:00 AM IST)
  ┌──────────────────────────────────────────────────────────────────────┐
  │  generator/claude_client.py  +  generator/prompts_ai_news.py        │
  │                                                                      │
  │  DIGEST TEXT GENERATION:                                             │
  │    1. Load prompts_ai_news.py → SYSTEM_PROMPT + build_digest_prompt()│
  │    2. Pass top 5 articles (title, summary, source, url)             │
  │    3. POST to Euri API → gemini-2.5-pro                             │
  │       model: "gemini-2.5-pro"                                        │
  │       max_tokens: 4096  (thinking model needs room)                 │
  │    4. Response: formatted digest (📰 header, 1️⃣-5️⃣ stories, trend) │
  │    5. Inject Read more links:                                        │
  │       Find each 📌 line → append [🔗 Read more](article_url)        │
  │    6. Run post-generation guardrail check                            │
  │                                                                      │
  │  A/B HEADLINE GENERATION (new):                                      │
  │    7. Send first 400 chars to Gemini                                 │
  │       Ask: "Write ONE alternative headline for story 1️⃣"            │
  │       max_tokens: 80  (just a headline)                              │
  │    8. Store as headline_b in DB                                      │
  │                                                                      │
  │  COVER IMAGE GENERATION:                                             │
  │    9. Load build_digest_image_prompt() → visual description          │
  │   10. POST to Euri API → gemini-3-pro-image-preview                 │
  │       size: 1024×1024                                                │
  │   11. Response: image URL (expires in ~minutes)                     │
  │                                                                      │
  │  SAVE TO DB:                                                         │
  │   12. Post saved → status = 'pending_review'                        │
  │       fields: content, image_url, headline_b, bot_id, article_id    │
  └──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  STEP 6 — HUMAN REVIEW (reviewer's Telegram chat)
  ┌──────────────────────────────────────────────────────────────────────┐
  │  publisher/review_interface.py                                       │
  │                                                                      │
  │  send_for_review(post):                                              │
  │    1. Use bot's own token (AI News → TELEGRAM_AI_BOT_TOKEN)         │
  │    2. Send to reviewer's chat (TELEGRAM_REVIEWER_CHAT_ID)           │
  │    3. Message layout:                                                │
  │       ┌──────────────────────────────────────────┐                  │
  │       │ [Cover Image]                            │                  │
  │       │ 📬 NEW POST FOR REVIEW                   │                  │
  │       │ Bot: 🤖 AI News Bot | Post ID: 42        │                  │
  │       ├──────────────────────────────────────────┤                  │
  │       │ [Full digest content]                    │                  │
  │       │                                          │                  │
  │       │ ─────────────────────────────────────── │                  │
  │       │ 💡 Alt Headline (B): [alternative]       │                  │
  │       ├──────────────────────────────────────────┤                  │
  │       │ [✅ Approve]  [❌ Reject]                 │                  │
  │       │ [📰 View Source Article]                 │                  │
  │       │ [📝 Use Alt Headline (B)]                │                  │
  │       └──────────────────────────────────────────┘                  │
  └──────────────────────────────────────────────────────────────────────┘
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
          APPROVE          REJECT       USE ALT B
               │              │              │
               ▼              ▼              ▼
  STEP 7 — PUBLISH / REJECT / SWAP
  ┌──────────────────────────────────────────────────────────────────────┐
  │                                                                      │
  │  APPROVE:                                                            │
  │    post.status = 'approved'                                          │
  │    _publish_post_async(post)                                         │
  │      → convert Markdown to HTML (_to_html())                        │
  │      → bot.send_photo(channel_id, image_url, caption=content)       │
  │      → if image expired: bot.send_message(channel_id, content)      │
  │    post.status = 'published'                                         │
  │    PublishLog entry saved                                            │
  │    logs/publish_history.log updated                                  │
  │                                                                      │
  │  REJECT:                                                             │
  │    Bot asks: "Please type the reason"                                │
  │    Reviewer types reason                                             │
  │    post.status = 'rejected', reject_reason saved                    │
  │    PublishLog entry saved                                            │
  │                                                                      │
  │  USE ALT HEADLINE (B):                                               │
  │    Find line starting with 1️⃣ in content                            │
  │    Replace *Old Headline* with *Alternative Headline*               │
  │    post.headline_b = None (used, cleared)                            │
  │    Re-send updated post for review (back to Step 6)                 │
  │                                                                      │
  └──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Astrology Bot — Different Pipeline

The Astrology bot skips RSS entirely and uses a different data source.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      ASTROLOGY BOT PIPELINE                             │
└─────────────────────────────────────────────────────────────────────────┘

  6:00 AM IST daily
        │
        ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │  aggregator/panchang_fetcher.py                                    │
  │                                                                    │
  │  1. Get today's date in IST (UTC+5:30)                            │
  │  2. HTTP GET → drikpanchang.com/panchang/day-panchang.html        │
  │     headers: Chrome User-Agent (to avoid bot blocks)              │
  │                                                                    │
  │  SCRAPING STRATEGY 1 — Table row scan:                            │
  │    BeautifulSoup parses HTML                                       │
  │    Scan all <tr> tags                                              │
  │    Match cell[0] against: Tithi, Nakshatra, Yoga, Karana, etc.    │
  │    Extract: "Tithi: Dwitiya | Paksha: Shukla | Nakshatra: Rohini" │
  │                                                                    │
  │  SCRAPING STRATEGY 2 — CSS class scan (fallback):                 │
  │    Look for elements with "panchang", "tithi", "nakshatra" class  │
  │    Extract first block of text > 30 chars                         │
  │                                                                    │
  │  FALLBACK (if both strategies fail):                               │
  │    Use: "Date: April 04, 2026 (IST). Please identify today's      │
  │    Hindu Panchang including Tithi, Paksha, Nakshatra..."          │
  │    → Gemini calculates panchang from the date                     │
  │                                                                    │
  │  Save as Article in DB (bot_id='astrology', virality_score=80)   │
  └───────────────────────────────────────────────────────────────────┘
        │
        ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │  generator/claude_client.py + generator/prompts_astrology.py      │
  │                                                                    │
  │  build_prompt(title, summary, source_name, url):                  │
  │    summary = "Tithi: Dwitiya | Paksha: Shukla | Nakshatra: ..."   │
  │                                                                    │
  │  SYSTEM_PROMPT tells Gemini:                                       │
  │    → Write in Hinglish (Hindi + English WhatsApp style)           │
  │    → Start with 🌙, no preamble                                   │
  │    → Warm, spiritual tone                                          │
  │                                                                    │
  │  POST_FORMAT output:                                               │
  │    🌙 *Aaj ka Tithi: Dwitiya | Shukla Paksha*                     │
  │    _Rohini Nakshatra • Saubhagya Yoga_                            │
  │    🔮 *Meaning:*  [3-4 lines — deity, significance]               │
  │    💡 *Daily Insight:* [3-4 lines — career/health/relationships]  │
  │    🪔 *Remedy:*  [3-4 lines — what to do, why, how]              │
  │    ✨ *Tip of the Day:* [2-3 lines — actionable CTA]              │
  │    #DailyPanchang #AajKaTithi ...                                 │
  │                                                                    │
  │  NO headline_b generated (tithi is factual, not creative)         │
  │                                                                    │
  │  Cover image: spiritual Indian art — moon, diya, lotus, mandala   │
  └───────────────────────────────────────────────────────────────────┘
        │
        ▼
  Review → Approve → Publish to @astrochhayah
  (Same review flow as AI News — separate reviewer chat ID)
```

---

## 4. Review Interface — Command Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    REVIEWER TELEGRAM CHAT                                │
│                    publisher/review_interface.py                         │
└─────────────────────────────────────────────────────────────────────────┘

  COMMANDS AVAILABLE:

  /generate [bot_id]
  ┌──────────────────────────────────────────────────────────────────────┐
  │ 1. Send "⏳ Generating..." message immediately                        │
  │ 2. Run _run_generation(bot_id) in a thread executor                  │
  │    (so Telegram doesn't freeze while waiting 30-60s for Gemini)     │
  │    → astrology: calls panchang_fetcher → generate_and_save_post()  │
  │    → others:    calls get_best_articles_for_bot() → generate_digest │
  │ 3. Edit status message to "✅ Done" or "❌ Failed"                   │
  │ 4. Send generated post for review (with buttons)                    │
  └──────────────────────────────────────────────────────────────────────┘

  /edit [post_id]
  ┌──────────────────────────────────────────────────────────────────────┐
  │ 1. Find post (by ID or most recent pending)                          │
  │ 2. Show content preview + "What would you like to change?"          │
  │ 3. Set state: _awaiting_edit_instruction[chat_id] = post_id         │
  │ 4. Wait for reviewer's next text message                            │
  │ 5. Run _apply_edit_sync(post_id, instruction) in thread executor:   │
  │    → Send to Gemini: [current post] + [edit instruction]            │
  │    → Gemini applies ONLY the requested change                       │
  │    → Update post.content in DB                                      │
  │    → Clear post.headline_b (content changed, old alt invalid)       │
  │ 6. Re-send updated post for review                                  │
  └──────────────────────────────────────────────────────────────────────┘

  /pending
  ┌──────────────────────────────────────────────────────────────────────┐
  │ Query DB for all posts WHERE status = 'pending_review'               │
  │ Show: ID, bot name, first 80 chars of content                        │
  └──────────────────────────────────────────────────────────────────────┘

  BUTTON TAP FLOWS:

  ✅ Approve
  ──────────────────────────────────────────────────────────────────────
  query.answer() → acknowledge tap (try/except — expires after ~30s)
  post.status = 'approved'
  _publish_post_async(post)
    → _to_html(content) — convert *bold* → <b>, _italic_ → <i>, links
    → bot.send_photo(channel_id, image_url, caption=html_content)
    → if image expired → bot.send_message(channel_id, html_content)
  post.status = 'published'
  PublishLog(action='published') saved
  publish_history.log entry written

  ❌ Reject
  ──────────────────────────────────────────────────────────────────────
  Set _awaiting_reject_reason[chat_id] = post_id  ← FIRST (crash-safe)
  try: remove buttons from message  ← SECOND (non-critical)
  Send: "Please type the reason for rejection"
  Wait for next text → _reject_post(post_id, reason=text)
    post.status = 'rejected', reject_reason = text
    PublishLog(action='rejected', notes=reason) saved

  📝 Use Alt Headline (B)
  ──────────────────────────────────────────────────────────────────────
  Load post.headline_b from DB
  _swap_first_headline(content, headline_b):
    Find line starting with 1️⃣
    Replace *Old Headline* with *New Headline* (regex)
  post.content = swapped content
  post.headline_b = None
  Re-send for review (back to full review message with buttons)
```

---

## 5. Markdown → Telegram HTML Conversion

Telegram requires HTML mode. AI generates Markdown. `_to_html()` converts between them.

```
  AI GENERATES THIS:          TELEGRAM NEEDS THIS:
  ─────────────────           ────────────────────
  **bold text**          →    <b>bold text</b>
  ***bold text***        →    <b>bold text</b>
  *bold text*            →    <b>bold text</b>
  _italic text_          →    <i>italic text</i>
  `code text`            →    <code>code text</code>
  [🔗 Read more](url)    →    <a href="url">🔗 Read more</a>

  Why HTML instead of Telegram Markdown?
  A single unmatched * or _ in AI text causes Telegram's MarkdownV1
  parser to throw an error and drop the entire message.
  HTML is more forgiving — unmatched tags are shown literally.
```

---

## 6. Database Schema

Three tables in SQLite (`db/ainews.db`):

```
┌──────────────────────────────────────────────────────────────────────────┐
│  TABLE: articles                                                          │
├──────────────┬────────────┬──────────────────────────────────────────────┤
│ id           │ INTEGER PK │ Auto-increment                                │
│ bot_id       │ VARCHAR    │ "ai_news" / "bollywood" / "astrology"         │
│ title        │ VARCHAR    │ Article headline                              │
│ url          │ VARCHAR    │ UNIQUE — deduplication key                    │
│ source_name  │ VARCHAR    │ "TechCrunch", "Drik Panchang", etc.           │
│ summary      │ TEXT       │ RSS description / panchang fields             │
│ published_at │ DATETIME   │ When article was published on source          │
│ fetched_at   │ DATETIME   │ When our app fetched it                       │
│ virality_score│ FLOAT     │ 0–100 score (panchang always = 80)            │
│ status       │ VARCHAR    │ new → scored → selected → skipped/blocked     │
│ blocked_reason│ VARCHAR   │ Guardrail category if blocked                 │
└──────────────┴────────────┴──────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│  TABLE: posts                                                             │
├──────────────┬────────────┬──────────────────────────────────────────────┤
│ id           │ INTEGER PK │ Auto-increment                                │
│ article_id   │ FK         │ → articles.id (CASCADE delete)                │
│ bot_id       │ VARCHAR    │ "ai_news" / "bollywood" / "astrology"         │
│ content      │ TEXT       │ Full generated post text (Markdown)           │
│ image_url    │ VARCHAR    │ Euri-generated cover image URL (expires fast) │
│ headline_b   │ TEXT       │ Alternative headline for A/B testing          │
│ status       │ VARCHAR    │ pending_review → approved → published/rejected│
│ created_at   │ DATETIME   │ When post was generated                       │
│ reviewed_at  │ DATETIME   │ When reviewer acted on it                     │
│ published_at │ DATETIME   │ When post went live on Telegram               │
│ reject_reason│ VARCHAR    │ Reviewer's rejection reason                   │
└──────────────┴────────────┴──────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│  TABLE: publish_log                                                       │
├──────────────┬────────────┬──────────────────────────────────────────────┤
│ id           │ INTEGER PK │ Auto-increment                                │
│ post_id      │ FK         │ → posts.id                                    │
│ bot_id       │ VARCHAR    │ Which bot published                           │
│ channel_id   │ VARCHAR    │ "@ai26news" etc.                              │
│ action       │ VARCHAR    │ "published" / "rejected" / "skipped"          │
│ notes        │ VARCHAR    │ Rejection reason or skip notes                │
│ timestamp    │ DATETIME   │ When the action happened                      │
└──────────────┴────────────┴──────────────────────────────────────────────┘

  RELATIONSHIPS:
  Article ──(1:many)──▶ Post ──(1:many)──▶ PublishLog
```

---

## 7. Scheduler — Daily Timeline (IST)

```
  TIME     ACTION                          FILES INVOLVED
  ──────── ─────────────────────────────── ─────────────────────────────────
  06:00    Fetch + score (all bots)        aggregator/rss_fetcher.py
           + fetch panchang (astrology)    aggregator/panchang_fetcher.py
           + generate astrology post       generator/claude_client.py
           + send astrology for review     publisher/review_interface.py

  07:00    Generate AI News digest         generator/claude_client.py
           Generate Bollywood digest       generator/claude_client.py
           Send both for review            publisher/review_interface.py

  08:00    Check if approved → publish     publisher/telegram_bot.py
           If no response → hold           publisher/review_interface.py

  12:00    Midday fetch (Bollywood only)   aggregator/rss_fetcher.py

  18:00    Generate 2nd Bollywood digest   generator/claude_client.py
           Send for review                 publisher/review_interface.py

  19:00    Check if approved → publish     publisher/telegram_bot.py

  ─────────────────────────────────────────────────────────────────────────
  All times are IST (UTC+5:30). APScheduler handles the job queue.
  Scheduler file: scheduler/jobs.py
```

---

## 8. Technology Stack

```
  LAYER               TECHNOLOGY              WHY
  ──────────────────  ──────────────────────  ────────────────────────────────
  Language            Python 3.10+            Async support, rich ecosystem
  Database            SQLite                  Zero setup, single file, local
  ORM                 SQLAlchemy 2.x          Python objects instead of raw SQL
  RSS Parsing         feedparser              Industry standard for RSS/Atom
  HTML Parsing        BeautifulSoup4 + lxml   Scraping Drik Panchang panchang
  AI Text             Gemini 2.5 Pro          Best quality, Hindi/Hinglish support
  AI Images           Gemini Image model      News-quality cover images
  AI Gateway          Euri API (euron.one)    OpenAI-compatible, 200K tokens/day free
  AI SDK              openai Python SDK       Works with Euri via base_url override
  Telegram Bot        python-telegram-bot 21  Modern async Telegram library
  HTTP Client         httpx (via PTB)         Async HTTP for Telegram API
  Scheduling          APScheduler 3.x         IST timezone, cron-style jobs
  Env Management      python-dotenv           Loads .env file into os.environ
  Logging             Python logging module   Named loggers, file + console output
```

---

## 9. File-by-File Reference

```
  FILE                               WHAT IT DOES
  ─────────────────────────────────  ──────────────────────────────────────────
  main.py                            Entry point — init DB, start scheduler

  config/settings.py                 All env vars + app constants in one place
  config/bots.json                   Master bot registry (3 bots defined)
  config/sources_ai.json             30+ AI/tech RSS sources with weights
  config/sources_bollywood.json      17 Bollywood sources in 4 groups
  config/sources_astrology.json      6 astrology reference sources
  config/keywords.json               Trending keywords + blocked keyword list

  aggregator/rss_fetcher.py          Polls RSS feeds, saves Article records
  aggregator/panchang_fetcher.py     Scrapes Drik Panchang, saves panchang Article
  aggregator/dedup.py                URL + title hash deduplication

  scoring/virality.py                Scoring formula + source multipliers + 3 caps
  scoring/fallback.py                Best-available selection when threshold not met

  guardrails/content_filter.py       Checks articles AND generated posts
  guardrails/keyword_blocklist.py    Lists of blocked keyword patterns
  guardrails/source_whitelist.py     Trusted source names registry

  generator/claude_client.py         Euri API calls: text, image, A/B, edit
  generator/prompts_ai_news.py       English digest templates + image prompts
  generator/prompts_bollywood.py     Hinglish digest templates + image prompts
  generator/prompts_astrology.py     Hinglish panchang post template + image prompt

  publisher/telegram_bot.py          Sends to channels, Markdown→HTML converter
  publisher/review_interface.py      Review bot: buttons, commands, A/B, /edit
  publisher/test_review_interface.py Manual test runner (any bot)

  scheduler/jobs.py                  APScheduler job definitions (IST timezone)

  db/models.py                       Article, Post, PublishLog table definitions
  db/database.py                     SQLite engine, sessions, auto-migration

  logs/app.log                       All application logs
  logs/guardrail_violations.log      Every blocked article or post with reason
  logs/publish_history.log           Every publish and rejection event

  .env                               API keys — NEVER committed to git
  .env.example                       Template for new developers
  requirements.txt                   All pip dependencies
```

---

## 10. Bot Token Routing — Why Each Bot Has Its Own Token

```
  PROBLEM: The reviewer has ONE chat. Three bots send posts to it.
           When reviewer taps "Approve", which bot publishes?

  SOLUTION: Each bot uses its OWN token to send review messages AND
            to poll for button taps. Telegram routes the callback back
            to whichever bot sent the original message.

  ┌──────────────┐  sends review msg  ┌──────────────────┐
  │ AI News Bot  │──────────────────▶│                  │
  │ (token A)    │◀──────────────────│  Reviewer Chat   │
  └──────────────┘  receives callback│  (one chat, 3    │
                                     │  bots writing to │
  ┌──────────────┐  sends review msg │  it)             │
  │ Bollywood Bot│──────────────────▶│                  │
  │ (token B)    │◀──────────────────│                  │
  └──────────────┘  receives callback└──────────────────┘

  Code: _get_bot_token(bot_id) in review_interface.py
        _get_reviewer_chat_id(bot_id) for per-bot reviewer accounts

  ASTROLOGY EXTRA: Can send to a DIFFERENT reviewer Telegram account
  via TELEGRAM_ASTROLOGY_REVIEWER_CHAT_ID in .env
```

---

## 11. Key Design Decisions Explained

```
  DECISION                  WHAT WE DO              WHY
  ────────────────────────  ──────────────────────  ───────────────────────────
  Human review mandatory    No auto-publish         Guardrails aren't perfect;
                                                    reviewer is the last line

  Post format               Digest (5 stories)      More value per notification
                                                    than 5 separate posts

  Read more links           Injected after AI gen   AI hallucinates URLs;
                                                    we inject real ones after

  Telegram format           HTML mode               MarkdownV1 crashes on
                                                    unmatched * or _ from AI

  Topic diversity cap       Max 2/movie             Prevents "Dhurandhar Day 15,
                                                    16, 17" flooding one digest

  Source weight             Official AI 1.5×        OpenAI/Anthropic posts are
                                                    more authoritative signal

  Panchang scraping         BeautifulSoup           Drik Panchang has no free API;
                            + date fallback         AI calculates from date if
                                                    scraping fails

  Alt headline (A/B)        Generated separately    Cheap 80-token call; gives
                            at 80 max_tokens        reviewer a creative option

  Thread executor           asyncio.run_in_executor Gemini takes 30-60s;
  for generation            (None, fn, arg)         we can't block the event loop

  State before API calls    _awaiting_reject BEFORE Order matters: if Telegram API
                            edit_message call       fails mid-flow, state is still
                                                    set so flow continues
```
