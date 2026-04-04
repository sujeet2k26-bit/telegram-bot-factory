# AI & Bollywood News Bot

Automated news aggregator that collects AI/tech and Bollywood news, scores for virality, generates posts using Claude AI, routes through human review, and publishes to Telegram channels.

---

## What It Does

1. **Fetches** articles from 20+ RSS sources every 6 hours
2. **Filters** off-topic and unsafe content (guardrails)
3. **Scores** articles by recency, source credibility, and cross-source overlap
4. **Generates** a daily digest post (top 5 AI stories) using Claude AI + a cover image
5. **Sends** the post to a private reviewer chat on Telegram
6. **Publishes** to the channel after you tap Approve

---

## Bots

| Bot | Channel | Language | Posts/Day | Status |
|-----|---------|----------|-----------|--------|
| AI News Bot | `@AINewsDaily_Bot` | English | 1 digest (top 5) | Active |
| Bollywood Buzz Bot | `@BollywoodBuzzBot` | Hindi/Hinglish | 2 | Config ready |
| Daily Astrology Bot | `@DailyAstrologyBot` | Hindi | 1 | Inactive |

---

## Prerequisites

- Python 3.10+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- An Euri API key (free at [euron.one](https://euron.one) — 200K tokens/day free)

---

## Setup

### 1. Clone and install dependencies

```bash
cd "AI News"
pip install -r requirements.txt
```

### 2. Create your `.env` file

Copy the example and fill in your keys:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Euri AI (text + image generation)
EURI_API_KEY=your_euri_api_key_here

# Telegram — AI News Bot
TELEGRAM_AI_BOT_TOKEN=your_bot_token_here
TELEGRAM_AI_CHANNEL_ID=@YourChannelHandle

# Telegram — Reviewer (your private chat with the bot)
TELEGRAM_REVIEWER_CHAT_ID=543925804   # numeric ID, not @username

# Telegram — Bollywood Buzz Bot (when ready)
TELEGRAM_BOLLYWOOD_BOT_TOKEN=
TELEGRAM_BOLLYWOOD_CHANNEL_ID=

# Telegram — Astrology Bot (inactive)
TELEGRAM_ASTROLOGY_BOT_TOKEN=
TELEGRAM_ASTROLOGY_CHANNEL_ID=
```

> **How to get your reviewer chat ID:** Message your bot on Telegram, then run:
> ```bash
> curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
> ```
> Look for `"chat": {"id": 123456789}` — that number is your chat ID.

### 3. Verify your connection

```bash
python test_euri_connection.py
```

---

## Running the Bot

### Option A — Full automated scheduler (production)

Runs all pipeline jobs on a schedule (fetch at 6 AM, review at 7 AM, publish at 8 AM IST):

```bash
python main.py
```

Press `Ctrl+C` to stop.

### Option B — Manual test run (development)

Fetches articles, generates a digest, sends it to your reviewer chat, and waits for your Approve/Reject:

```bash
python publisher/test_review_interface.py
```

---

## Pipeline Scripts (run individually)

| Script | What it does |
|--------|-------------|
| `python aggregator/test_fetch.py` | Fetch articles from all RSS sources and save to DB |
| `python generator/test_generator.py` | Generate a post from the top scored article |
| `python publisher/test_review_interface.py` | Full flow: generate → send for review → listen for approval |
| `python publisher/test_publisher.py` | Test publishing an already-approved post |

---

## Review Commands

Once the review bot is running, send these commands in your Telegram reviewer chat:

| Command | Action |
|---------|--------|
| `/pending` | List all posts waiting for review |
| `/preview 5` | Show full post #5 |
| `/sources 5` | Show the source articles used for post #5 |
| `/approve 5` | Approve and publish post #5 immediately |
| `/reject 5` | Reject post #5 (bot asks for a reason) |
| `/skip 5` | Skip post #5 without publishing |

You can also tap the **✅ Approve** / **❌ Reject** inline buttons sent with each post.

---

## Project Structure

```
AI News/
├── aggregator/
│   ├── rss_fetcher.py        # Fetches articles from RSS feeds
│   └── dedup.py              # Deduplication (hash-based)
├── scoring/
│   ├── virality.py           # Scores articles (recency + overlap + keywords + source weight)
│   └── fallback.py           # Picks best articles when nothing hits virality threshold
├── guardrails/
│   ├── content_filter.py     # Safety + AI relevance filter
│   ├── keyword_blocklist.py  # Blocked keyword categories
│   └── source_whitelist.py   # Trusted source registry
├── generator/
│   ├── claude_client.py      # Claude API wrapper (text + image generation)
│   ├── prompts_ai_news.py    # Post format templates for AI News Bot
│   ├── prompts_bollywood.py  # Post format templates for Bollywood Bot
│   └── prompts_astrology.py  # Post format templates for Astrology Bot
├── publisher/
│   ├── telegram_bot.py       # Sends posts to Telegram channels
│   ├── review_interface.py   # Human review bot (approve/reject)
│   └── test_review_interface.py  # End-to-end test script
├── scheduler/
│   └── jobs.py               # APScheduler jobs for all active bots
├── db/
│   └── models.py             # SQLite database models
├── config/
│   ├── bots.json             # Master bot registry (add new bots here)
│   ├── sources_ai.json       # AI/tech RSS sources
│   ├── sources_bollywood.json # Bollywood RSS sources
│   ├── keywords.json         # Trending + blocked keywords
│   └── settings.py           # App config (thresholds, API keys)
├── logs/
│   ├── app.log               # General application logs
│   ├── guardrail_violations.log  # Blocked content log
│   └── publish_history.log   # Published posts log
├── main.py                   # Entry point
├── requirements.txt
├── .env.example              # API key template
└── CLAUDE.md                 # Architecture and coding guidelines
```

---

## Adding a New Bot

1. Add an entry to `config/bots.json` (copy an existing bot, change the `id`, `name`, etc.)
2. Create `config/sources_<id>.json` with trusted RSS sources
3. Create `generator/prompts_<id>.py` with post format instructions
4. Add `TELEGRAM_<ID_UPPERCASE>_BOT_TOKEN` and `TELEGRAM_<ID_UPPERCASE>_CHANNEL_ID` to `.env`
5. Set `"active": true` in `bots.json`
6. Restart `python main.py`

No changes to the core pipeline code needed.

---

## Schedule (IST)

| Time | Action |
|------|--------|
| 6:00 AM | Fetch + score articles (all bots) |
| 7:00 AM | Generate post + send to reviewer |
| 8:00 AM | Publish if approved |
| 12:00 PM | Midday fetch (Bollywood only) |
| 6:00 PM | Second Bollywood post sent for review |
| 7:00 PM | Publish if approved |

---

## Troubleshooting

**Bot not responding / 409 Conflict error**
Another bot instance is already running. Kill all Python processes and restart:
```bash
taskkill /F /IM python.exe   # Windows
# or
pkill python                  # Mac/Linux
python publisher/test_review_interface.py
```

**"Chat not found" when sending review**
Your `TELEGRAM_REVIEWER_CHAT_ID` must be a numeric ID, not `@username`. See setup step 2.

**No articles being selected / all from one source**
Run a manual fetch first:
```bash
python aggregator/test_fetch.py
```
Then retry the test script.

**Post generation fails**
Check your `EURI_API_KEY` is set in `.env` and run `python test_euri_connection.py`.
