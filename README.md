# Telegram Bot Factory

A multi-bot publishing platform that automates content aggregation, AI generation, human review, and Telegram channel publishing — all from a single shared backend.

Add any new domain in under 30 minutes: one config entry + one prompt file. The pipeline, scheduler, guardrails, and review interface work for every bot automatically.

---

## How It Works

1. **Fetch** — RSS feeds or custom scrapers pull fresh content every few hours
2. **Filter** — guardrails block unsafe, off-topic, or low-quality content
3. **Score** — virality engine ranks articles by recency, source credibility, and cross-source overlap
4. **Select** — diversity caps prevent any single source or topic from dominating
5. **Generate** — Gemini 2.5 Pro writes a digest post + cover image via Euri API
6. **Review** — post lands in your private Telegram chat with ✅ Approve / ❌ Reject buttons
7. **Publish** — approved posts go live on the correct channel instantly

No post is ever published without explicit human approval.

---

## Active Bots

| Bot | Channel | Domain | Language | Posts/Day |
|-----|---------|--------|----------|-----------|
| AI News Bot | `@ai26news` | AI & Technology | English | 1 digest (top 5) |
| Bollywood Buzz Bot | `@bollywood_daily_gossip` | Entertainment | Hindi/Hinglish | 2 digests (top 5 each) |
| Daily Astrology Bot | `@astrochhayah` | Astrology/Panchang | Hindi/Hinglish | 1 panchang post |

Each bot uses its own Telegram token and can route review messages to a different Telegram account via per-bot reviewer chat IDs.

---

## Prerequisites

- Python 3.10+
- A Telegram bot token for each active bot (from [@BotFather](https://t.me/BotFather))
- An Euri API key — free at [euron.one](https://euron.one), 200K tokens/day

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/sujeet2k26-bit/telegram-bot-factory.git
cd telegram-bot-factory
pip install -r requirements.txt
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Fill in `.env`:

```env
# Euri AI (text + image generation via Gemini)
EURI_API_KEY=your_euri_api_key_here

# Telegram — AI News Bot
TELEGRAM_AI_BOT_TOKEN=your_ai_bot_token_here
TELEGRAM_AI_CHANNEL_ID=@your_ai_channel

# Telegram — Bollywood Buzz Bot
TELEGRAM_BOLLYWOOD_BOT_TOKEN=your_bollywood_bot_token_here
TELEGRAM_BOLLYWOOD_CHANNEL_ID=@your_bollywood_channel

# Telegram — Daily Astrology Bot
TELEGRAM_ASTROLOGY_BOT_TOKEN=your_astrology_bot_token_here
TELEGRAM_ASTROLOGY_CHANNEL_ID=@your_astrology_channel

# Reviewer — default account (used by AI News + Bollywood)
TELEGRAM_REVIEWER_CHAT_ID=123456789   # numeric ID, not @username

# Reviewer — per-bot override (optional — routes to a different account)
TELEGRAM_ASTROLOGY_REVIEWER_CHAT_ID=987654321
```

> **Get your reviewer chat ID:** Search `@userinfobot` on Telegram and send it any message — it replies with your numeric ID.

> **Per-bot reviewer:** Set `TELEGRAM_<BOT>_REVIEWER_CHAT_ID` to send that bot's review messages to a different Telegram account.

### 3. Add each bot as a channel admin

1. Open the channel → Settings → Administrators
2. Add the bot by username
3. Grant **Post Messages** permission

### 4. Verify connection

```bash
python test_euri_connection.py
```

---

## Running

### Production — full scheduler

```bash
python main.py
```

Starts all bots. Fetches, scores, generates, and sends posts to your reviewer on the schedule below. All three review bots start automatically as background threads.

### Development — manual test run

Generate a fresh post for a specific bot, send it to your reviewer chat, and wait for Approve/Reject:

```bash
python publisher/test_review_interface.py ai_news
python publisher/test_review_interface.py bollywood
python publisher/test_review_interface.py astrology
```

---

## Reviewer Commands

Send these from any reviewer Telegram chat while the bot is running:

| Command | Action |
|---------|--------|
| `/generate` | Generate a new post for the current bot |
| `/generate bollywood` | Generate for a specific bot (works from any reviewer chat) |
| `/card` | Generate + publish an Instagram/Facebook image card (astrology) |
| `/card full` | Full auto-height card for WhatsApp |
| `/edit [id]` | Edit a post with a natural language instruction before approving |
| `/pending` | List all posts waiting for review |
| `/preview <id>` | Show full content of a post |
| `/sources <id>` | Show the source article used for a post |
| `/skip <id>` | Skip a post without publishing |
| `/killstale` | Kill stale Python processes (fixes 409 Conflict / frozen commands) |
| `/help` | Show all commands |

**On Approve** → published to the bot's channel immediately.
**On Reject** → bot asks for a reason, marks post rejected.

> `/generate bollywood` works from **any** reviewer chat — you don't need separate accounts open for each bot.

---

## Adding a New Bot

The entire pipeline is bot-agnostic. To add a new bot:

1. **Add a config entry** to `config/bots.json`:

```json
{
  "id": "crypto",
  "name": "Crypto News Bot",
  "domain": "crypto_finance",
  "language": "english",
  "posts_per_day": 1,
  "schedule_times": ["08:00"],
  "digest_count": 5,
  "sources_file": "config/sources_crypto.json",
  "prompt_file": "generator/prompts_crypto.py",
  "bot_token_env": "TELEGRAM_CRYPTO_BOT_TOKEN",
  "channel_id_env": "TELEGRAM_CRYPTO_CHANNEL_ID",
  "active": true
}
```

2. **Create a sources file** — `config/sources_crypto.json` with trusted RSS feeds
3. **Create a prompt file** — `generator/prompts_crypto.py` with `SYSTEM_PROMPT`, `build_digest_prompt()`, `build_digest_image_prompt()`
4. **Add env vars** to `.env`:
   ```env
   TELEGRAM_CRYPTO_BOT_TOKEN=...
   TELEGRAM_CRYPTO_CHANNEL_ID=@your_crypto_channel
   TELEGRAM_CRYPTO_REVIEWER_CHAT_ID=...   # optional
   ```
5. **Register the token** in `_get_bot_token()` in `publisher/review_interface.py` and `BOT_CONFIG_MAP` in `publisher/telegram_bot.py`
6. Set `"active": true` and restart `main.py`

No changes to the core pipeline, scheduler, guardrails, or review interface.

---

## Post Formats

### Digest — AI News (English)
```
📰 AI News Daily — April 04, 2026

1️⃣  Headline for story one
    What happened + why it matters (2-3 sentences)
    📌 TechCrunch  |  🔗 Read more

2️⃣ ... (5 stories total)

🔍 Trend Insight
   What today's stories have in common

#AINews #TechUpdate #ArtificialIntelligence
```

### Digest — Bollywood (Hindi/Hinglish)
```
🎬 Bollywood Buzz Daily — April 04, 2026
Aaj ki sabse hot Bollywood khabrein 🌟

1️⃣  Catchy Hinglish headline 🎬
    Kya hua + kyun interesting (2-3 sentences)
    📌 Pinkvilla  |  🔗 Read more

2️⃣ ... (5 stories total)

🔥 Top Trending Gossip

#Bollywood #BollywoodNews #Entertainment
```

### Panchang — Daily Astrology (Hindi/Hinglish)
```
🌙 Aaj ki Tithi: Dwitiya | Shukla Paksha
  Rohini Nakshatra • Saubhagya Yoga

🔮 Meaning:      [spiritual significance + nakshatra energy]
💡 Daily Insight: [career / relationships / health / finance]
🪔 Remedy:        [what, why, how — in 5 minutes at home]
✨ Tip of the Day: [one action + encouraging closing line]

#DailyPanchang #AajKiTithi #Astrology
```

---

## Project Structure

```
telegram-bot-factory/
├── aggregator/
│   ├── rss_fetcher.py          # Bot-agnostic RSS poller
│   ├── panchang_fetcher.py     # Scrapes Drik Panchang (astrology bot)
│   └── dedup.py                # Hash-based deduplication
├── scoring/
│   ├── virality.py             # Scoring engine + source weights + diversity caps
│   └── fallback.py             # Best-available selection when threshold not met
├── guardrails/
│   ├── content_filter.py       # Pre/post generation safety checks
│   ├── keyword_blocklist.py    # Blocked keyword patterns
│   └── source_whitelist.py     # Trusted source registry
├── generator/
│   ├── claude_client.py        # Euri/Gemini API wrapper + Read more URL injection
│   ├── image_card.py           # Astrology image card generator (social + full)
│   ├── prompts_ai_news.py      # Prompt templates — AI News Bot
│   ├── prompts_bollywood.py    # Prompt templates — Bollywood Bot
│   └── prompts_astrology.py    # Prompt templates — Astrology Bot
├── publisher/
│   ├── telegram_bot.py         # Bot-agnostic publisher + Markdown→HTML converter
│   ├── review_interface.py     # Review bot — Approve/Reject, /generate, /killstale
│   └── test_review_interface.py
├── scheduler/
│   └── jobs.py                 # APScheduler jobs, IST timezone, all active bots
├── db/
│   ├── database.py             # SQLite session management
│   └── models.py               # Article, Post, PublishLog models
├── config/
│   ├── bots.json               # Master bot registry — one entry per bot
│   ├── sources_ai.json         # AI/tech trusted sources
│   ├── sources_bollywood.json  # Bollywood trusted sources
│   ├── sources_astrology.json  # Astrology reference sources
│   ├── keywords.json           # Trending + blocked keywords
│   └── settings.py             # Global config (thresholds, model names, API URLs)
├── .env.example
├── requirements.txt
├── CLAUDE.md
└── main.py
```

---

## Schedule (IST)

| Time | Action |
|------|--------|
| 6:00 AM | Fetch + score (AI News + Bollywood) · Panchang fetch + generate (Astrology) |
| 7:00 AM | Generate digest + send to reviewer (AI News + Bollywood) |
| 8:00 AM | Publish if approved; hold until 12 PM if no response |
| 12:00 PM | Midday fetch (Bollywood only) |
| 6:00 PM | Second Bollywood digest sent for review |
| 7:00 PM | Publish if approved |

---

## Troubleshooting

**409 Conflict — another instance already running**
Use `/killstale` in your Telegram reviewer chat — it kills all stale Python processes except the current one and reports what was stopped. Or manually:
```bash
taskkill /F /IM python.exe        # Windows
pkill -f python                   # Linux/Mac
```

**Bot can't send review message (403 Forbidden)**
The reviewer hasn't started a conversation with that bot. Open Telegram, find the bot, and send `/start`. Then retry.
Alternatively, use `/generate <bot_id>` from a chat where you've already started the bot — the review message will be delivered through whichever bot you're currently talking to.

**"Chat not found" for reviewer**
`TELEGRAM_REVIEWER_CHAT_ID` must be a numeric ID (e.g. `543925804`), not `@username`. Get it from `@userinfobot`.

**Review message shows no image**
Normal — Euri image URLs expire in ~5 minutes. The bot falls back to text-only automatically. The post can still be approved and published.

**No articles selected / empty digest**
Run a manual fetch first:
```bash
python aggregator/test_fetch.py ai_news
python aggregator/test_fetch.py bollywood
```

**Post blocked by guardrails**
Check `logs/guardrail_violations.log` to see which category triggered.

**Generation fails / empty response**
Check `EURI_API_KEY` is set and quota isn't exhausted (200K tokens/day free tier):
```bash
python test_euri_connection.py
```

**Gemini 429 — rate limit hit**
Quota resets daily at UTC midnight. Wait and retry the next day.
