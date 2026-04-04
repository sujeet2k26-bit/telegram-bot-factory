# CLAUDE.md — AI & Bollywood News Bot

This file defines the architecture, flow, guardrails, and conventions for the AI & Bollywood News Aggregator + Telegram Publisher project. All development must follow these guidelines.

---

## Project Overview

An automated news aggregation and content generation system that:
- Collects AI/tech and Bollywood news from trusted free sources
- Scores content for virality and relevance
- Generates original posts using Claude AI
- Routes posts through a human review step before publishing
- Publishes via **two separate Telegram bots** (AI bot: 1 post/day, Bollywood bot: 2 posts/day)

---

## Bots & Target Audience

| Bot | Telegram Handle | Audience | Language | Posts/Day | Status |
|-----|----------------|----------|----------|-----------|--------|
| AI News Bot | `@AINewsDaily_Bot` | Tech enthusiasts | English | 1 | Phase 1 |
| Bollywood Buzz Bot | `@BollywoodBuzzBot` | Bollywood fans | Hindi / Hinglish | 2 | Phase 1 |
| Daily Astrology Bot | `@DailyAstrologyBot` | General public | Hindi | 1 | Planned |

- All bots are managed by the **same backend codebase**
- Each bot is a **config-driven plugin** — adding a new bot requires only a config entry + a prompt file, no core code changes
- Each bot has its own `BOT_TOKEN` and publishes to its own channel
- The reviewer receives pending posts from **all bots** in a single private review chat, labeled by bot/domain

---

## Content Rules

### Tone Guidelines
- AI News: Formal, informative, editorial — with a punchy headline and social media-friendly summary
- Bollywood: Conversational Hindi/Hinglish, credible gossip tone — not tabloid, not dry
- Every post must feel human-written, not AI-generated

### Post Format — AI News (English)
```
🔬 [Headline — max 12 words, punchy]

[Paragraph 1: What happened — the key fact]
[Paragraph 2: Why it matters — impact or significance]
[Paragraph 3: What's next — implication or trend]

📌 Source: [Source Name] | 🔗 [URL]
#AINews #TechUpdate #ArtificialIntelligence
```

### Post Format — Bollywood (Hindi/Hinglish)
```
🎬 [Headline — Hinglish, engaging, max 12 words]

[Paragraph 1: Kya hua — the news in Hindi/Hinglish]
[Paragraph 2: Kyun important hai — context or background]
[Paragraph 3: Aage kya — what to expect next]

📌 Source: [Source Name] | 🔗 Aur Padho
#Bollywood #BollywoodNews #Entertainment
```

---

## Content Pipeline Flow

```
Step 1: FETCH
  RSS feeds + NewsAPI polled every 6 hours
  Raw articles stored in DB with metadata

Step 2: DEDUPLICATE
  Hash-based dedup on title + URL
  Skip articles already seen in last 7 days

Step 3: FILTER (Guardrails — see below)
  Run guardrail checks before scoring
  Flagged content is logged and skipped

Step 4: SCORE
  Primary: Virality Score (recency + cross-source + Reddit signals)
  Fallback: View/engagement count if no story hits virality threshold

Step 5: SELECT
  AI Bot: Pick top 1 story per day (morning only)
  Bollywood Bot: Pick top 2 stories per day (1 morning + 1 evening)
  If virality threshold not met → use most-viewed story of the day

Step 6: GENERATE
  Claude API generates post in correct language and tone
  AI stories → English editorial
  Bollywood stories → Hindi/Hinglish editorial

Step 7: HUMAN REVIEW (mandatory)
  Generated post sent to reviewer via Telegram bot command
  Reviewer approves (/approve), edits (/edit), or rejects (/reject)
  No post is published without explicit approval

Step 8: PUBLISH
  Approved post published to correct Telegram channel
  DB updated with publish status, timestamp, channel
  Rejected posts logged with reason for future model improvement
```

---

## Virality Scoring

```python
virality_score = (
    recency_score        # 0-30: last 6hrs=30, 12hrs=20, 24hrs=10, 48hrs=0
  + source_overlap       # 0-30: same story in 3+ sources = 30, 2 sources = 15
  + reddit_signal        # 0-20: upvotes on r/artificial or r/bollywood
  + keyword_weight       # 0-20: matches trending keyword list
)
# Publish threshold: score >= 60
# Fallback if no story >= 60: use story with highest view/engagement count
```

---

## Guardrails (Hard Rules — Non-Negotiable)

All content — both fetched and generated — must pass these checks before proceeding.

### 1. Hate Speech / Communal / Religious Targeting
- Block any content that targets communities, religions, castes, or ethnicities
- Keywords: communal violence, religious slurs, caste-based attacks
- Action: Skip + log

### 2. Sexual / Adult Content
- Block explicit or suggestive sexual content
- Applies to both news articles and generated text
- Action: Skip + log

### 3. Violence / Graphic Content
- Block content describing graphic violence, gore, or brutality in detail
- Crime news may be included only if reported factually without graphic detail
- Action: Skip + log

### 4. Politically Sensitive Content
- Block content related to elections, political propaganda, riots, or political targeting
- General tech policy news (AI regulation, copyright) is allowed
- Bollywood-politics crossover: allowed only if factual, not opinionated
- Action: Skip + log

### 5. Unverified Celebrity Defamation
- Block Bollywood stories that make serious accusations (affairs, crimes, misconduct) without a credible named source
- Rumors tagged "sources say" from unverified blogs must be rejected
- Action: Skip + log

### 6. Fake News / Clickbait
- Block articles from non-whitelisted sources unless cross-verified by 2+ trusted sources
- Headlines with "SHOCKING", "You won't believe", "EXPOSED" patterns are flagged for review
- Action: Flag for human review (not auto-skip)

### Guardrail Implementation
- Pre-generation check: run on raw article before sending to Claude
- Post-generation check: run on Claude output before sending to reviewer
- Any guardrail violation → logged to `logs/guardrail_violations.log` with timestamp, source, reason
- Never silently discard — always log

---

## Trusted Sources

### AI / Technology News

Collect and summarize the latest daily AI news from the following open sources.
Extract the most important AI updates from the last 24 hours, remove duplicates and
low-quality content, and highlight trends, new tools, model releases, and breakthroughs.

#### Newsletters (monitored via RSS / web scraping)

| Source | URL | Notes |
|--------|-----|-------|
| The Rundown AI | therundown.ai | Daily AI digest, high signal |
| Superhuman AI | superhumanai.com | Practical AI tools and news |
| TLDR AI | tldr.tech/ai | Concise daily AI summaries |
| The Neuron | theneurondaily.com | Consumer AI news |
| Ben's Bites | bensbites.com | AI product and research news |

#### Websites / Blogs (Free RSS)

| Source | URL | RSS Feed | Notes |
|--------|-----|----------|-------|
| OpenAI Blog | openai.com/blog | /rss.xml | Official OpenAI updates |
| Anthropic Blog | anthropic.com/news | via RSS | Official Anthropic / Claude |
| Google DeepMind Blog | deepmind.google/discover/blog | via RSS | Official DeepMind research |
| Google AI Blog | blog.google/technology/ai/ | via RSS | Official Google AI |
| Meta AI Blog | ai.meta.com/blog | via RSS | Official Meta AI |
| Microsoft AI Blog | blogs.microsoft.com/ai | via RSS | Official Microsoft AI |
| MIT News (AI) | news.mit.edu | /rss/feed.xml | Academic AI research |
| Artificial Intelligence News | artificialintelligence-news.com | /feed/ | AI industry coverage |
| Crescendo AI News | crescendo.ai/news | via RSS | AI startup + product news |
| TechCrunch | techcrunch.com | /feed/ | Breaking AI/tech news |
| The Verge | theverge.com | /rss/index.xml | Tech culture + AI |
| Ars Technica | arstechnica.com | /feed/ | In-depth technical analysis |
| VentureBeat AI | venturebeat.com/category/ai/ | /feed/ | AI industry news |

#### Research Sources

| Source | URL | Notes |
|--------|-----|-------|
| ArXiv cs.AI | arxiv.org/rss/cs.AI | AI research papers |
| ArXiv cs.LG | arxiv.org/rss/cs.LG | Machine learning papers |
| Papers With Code | paperswithcode.com | ML papers + code |
| BAIR Blog | bair.berkeley.edu/blog | Berkeley AI Research |
| Alignment Forum | alignmentforum.org | AI safety research |

#### Community Sources (Phase 2 — requires API keys)

| Source | Notes |
|--------|-------|
| Hacker News | Community-verified tech via RSS |
| Reddit r/MachineLearning | Research and industry discussion |
| Reddit r/Artificial | General AI community |
| Reddit r/ChatGPT | Consumer AI trends |
| Twitter/X | AI influencers and company accounts |
| LinkedIn | AI posts and newsletters |

#### Content Collection Instructions

- Extract the most important AI updates from the **last 24 hours only**
- Remove duplicates — if the same story appears in 3+ sources, count that as high virality
- Filter out low-quality content (opinion pieces without news value, ads, job posts)
- Summarize into **5–10 key bullet points** per digest
- Highlight: trends, new tools, model releases, research breakthroughs, company moves
- Keep output concise, clear, and informative
- Add a **"Trend Insight"** section at the end summarizing emerging patterns across stories

### Bollywood / Entertainment News (Free RSS)

| Source | URL | Notes |
|--------|-----|-------|
| Bollywood Hungama | bollywoodhungama.com | Most specialized Bollywood source |
| India Today Entertainment | indiatoday.in/entertainment | Major Indian media group |
| NDTV Entertainment | entertainment.ndtv.com | Credible national news network |
| Hindustan Times Entertainment | hindustantimes.com/entertainment | Major national outlet |
| The Hindu Entertainment | thehindu.com/entertainment | Most editorially rigorous |
| Filmfare | filmfare.com | Industry-recognized Bollywood source |
| Pinkvilla | pinkvilla.com | Celebrity and entertainment focused |

### Free News APIs

| API | Free Tier | Use Case |
|-----|-----------|----------|
| NewsAPI.org | 100 req/day | Broad AI + Bollywood coverage |
| GNews | Limited free tier | Supplementary aggregation |
| Currents API | Free with limits | Backup source |

---

## Fallback Logic

```
If virality_score < 60 for ALL stories of the day:
  → Sort by engagement/view count (from NewsAPI metadata or Reddit)
  → Pick top story regardless of virality score
  → Tag post as [TRENDING] instead of [VIRAL] in internal DB
  → Still goes through human review before publishing
```

---

## Scheduling

```
06:00 AM  →  Fetch + Score run (morning batch) — both domains
07:00 AM  →  Send to reviewer:
               [AI Bot]        → 1 story (English)
               [Bollywood Bot] → 1st story (Hindi/Hinglish)
08:00 AM  →  Publish if approved (both bots)
             If no reviewer response by 8AM → hold, retry at 12 PM

12:00 PM  →  Fetch + Score run (midday batch) — Bollywood only
06:00 PM  →  Send to reviewer:
               [Bollywood Bot] → 2nd story of the day
07:00 PM  →  Publish if approved (Bollywood Bot only)
             If no reviewer response → hold, publish next morning

Note: AI Bot has no evening post. One high-quality post per day only.
```

---

## Human Review Interface (Telegram Bot Commands)

The reviewer interacts with the bot directly in a private Telegram chat:

```
/pending         → List all posts awaiting review
/preview [id]    → Show full generated post for review
/approve [id]    → Approve and queue for publishing
/reject [id]     → Reject and log reason
/edit [id]       → Open post for manual editing before approval
/sources [id]    → Show original source articles used
/skip            → Skip today's post (no publish)
```

---

## Extensible Bot Architecture

### Core Design Principle
**Every bot is defined entirely by its config entry + prompt file.**
The pipeline, scheduler, guardrails, reviewer interface, and publisher are all bot-agnostic.
To add a new bot: add one entry to `bots.json` + create one prompt file. Zero core code changes.

### Bot Config Schema (`config/bots.json`)
Each bot is one object in the `bots` array:

```json
{
  "bots": [
    {
      "id": "ai_news",
      "name": "AI News Bot",
      "handle": "@AINewsDaily_Bot",
      "domain": "ai_technology",
      "language": "english",
      "tone": "editorial_social",
      "posts_per_day": 1,
      "schedule_times": ["07:00"],
      "sources_file": "config/sources_ai.json",
      "prompt_file": "generator/prompts_ai.py",
      "bot_token_env": "TELEGRAM_AI_BOT_TOKEN",
      "channel_id_env": "TELEGRAM_AI_CHANNEL_ID",
      "active": true
    },
    {
      "id": "bollywood",
      "name": "Bollywood Buzz Bot",
      "handle": "@BollywoodBuzzBot",
      "domain": "bollywood_entertainment",
      "language": "hindi_hinglish",
      "tone": "conversational_editorial",
      "posts_per_day": 2,
      "schedule_times": ["07:00", "18:00"],
      "sources_file": "config/sources_bollywood.json",
      "prompt_file": "generator/prompts_bollywood.py",
      "bot_token_env": "TELEGRAM_BOLLYWOOD_BOT_TOKEN",
      "channel_id_env": "TELEGRAM_BOLLYWOOD_CHANNEL_ID",
      "active": true
    },
    {
      "id": "astrology",
      "name": "Daily Astrology Bot",
      "handle": "@DailyAstrologyBot",
      "domain": "astrology_hindi_calendar",
      "language": "hindi",
      "tone": "spiritual_informative",
      "posts_per_day": 1,
      "schedule_times": ["06:00"],
      "sources_file": "config/sources_astrology.json",
      "prompt_file": "generator/prompts_astrology.py",
      "bot_token_env": "TELEGRAM_ASTROLOGY_BOT_TOKEN",
      "channel_id_env": "TELEGRAM_ASTROLOGY_CHANNEL_ID",
      "active": false
    }
  ]
}
```

### How to Activate a New Bot
1. Set `"active": true` in its `bots.json` entry
2. Add its `BOT_TOKEN` and `CHANNEL_ID` to `.env`
3. Create its `sources_*.json` file with trusted sources
4. Create its `prompts_*.py` file with generation instructions
5. Restart the scheduler — it auto-registers all active bots

### How to Add a Brand New Bot
1. Append a new object to `bots.json` (follow the schema above)
2. Create `config/sources_<id>.json`
3. Create `generator/prompts_<id>.py`
4. Add env vars to `.env` and `.env.example`
5. Done — no changes to pipeline, scheduler, guardrails, or publisher code

---

## Project Folder Structure

```
ai-news-bot/
├── aggregator/
│   ├── rss_fetcher.py        # Bot-agnostic RSS poller (reads sources from bot config)
│   ├── news_api.py           # NewsAPI integration
│   └── dedup.py              # Hash-based deduplication
├── scoring/
│   ├── virality.py           # Virality scoring engine (bot-agnostic)
│   └── fallback.py           # View-count fallback logic
├── guardrails/
│   ├── content_filter.py     # Pre/post generation guardrail checks (bot-agnostic)
│   ├── keyword_blocklist.py  # Blocked keyword patterns
│   └── source_whitelist.py   # Trusted source registry
├── generator/
│   ├── claude_client.py      # Anthropic API wrapper (bot-agnostic)
│   ├── prompts_ai.py         # Prompt config for AI News Bot
│   ├── prompts_bollywood.py  # Prompt config for Bollywood Bot
│   └── prompts_astrology.py  # Prompt config for Astrology Bot (ready, inactive)
├── publisher/
│   ├── telegram_bot.py       # Bot-agnostic publisher (reads token from bot config)
│   └── review_interface.py   # Human-in-loop review handler (all bots, one chat)
├── scheduler/
│   └── jobs.py               # Auto-registers jobs for all active bots from bots.json
├── db/
│   ├── models.py             # SQLite models (bot_id field on all records)
│   └── migrations/
├── logs/
│   ├── guardrail_violations.log
│   ├── publish_history.log
│   └── errors.log
├── config/
│   ├── bots.json             # Master bot registry — add new bots here
│   ├── sources_ai.json       # AI/tech trusted sources
│   ├── sources_bollywood.json # Bollywood trusted sources
│   ├── sources_astrology.json # Astrology sources (ready, inactive)
│   ├── keywords.json         # Trending + blocked keywords
│   └── settings.py           # Global app config (thresholds, retry logic)
├── tests/
│   └── ...
├── .env.example              # API key template for all bots (never commit .env)
├── requirements.txt
├── CLAUDE.md                 # This file
└── main.py                   # Entry point — loads all active bots from bots.json
```

---

## Environment Variables (.env)

```
# Claude / Anthropic
ANTHROPIC_API_KEY=

# Telegram — AI News Bot
TELEGRAM_AI_BOT_TOKEN=
TELEGRAM_AI_CHANNEL_ID=

# Telegram — Bollywood Buzz Bot
TELEGRAM_BOLLYWOOD_BOT_TOKEN=
TELEGRAM_BOLLYWOOD_CHANNEL_ID=

# Telegram — Daily Astrology Bot (inactive — add when ready)
TELEGRAM_ASTROLOGY_BOT_TOKEN=
TELEGRAM_ASTROLOGY_CHANNEL_ID=

# Telegram — Reviewer (shared private chat for ALL bots)
TELEGRAM_REVIEWER_CHAT_ID=

# Pattern for future bots: TELEGRAM_<BOT_ID_UPPERCASE>_BOT_TOKEN and TELEGRAM_<BOT_ID_UPPERCASE>_CHANNEL_ID

# NewsAPI
NEWS_API_KEY=

# Reddit (Phase 2)
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=
```

Never commit `.env` to version control. Use `.env.example` as the template.

---

## Development Phases

### Phase 1 — Local MVP
- [ ] RSS fetcher (AI + Bollywood sources)
- [ ] Deduplication logic
- [ ] Guardrail content filter
- [ ] Virality scoring (recency + source overlap)
- [ ] Claude API content generation (English + Hindi/Hinglish)
- [ ] Human review via Telegram bot commands (shared reviewer chat)
- [ ] Daily publish scheduler — AI bot (1/day), Bollywood bot (2/day)
- [ ] SQLite database
- [ ] Two separate Telegram bots + channels

### Phase 2 — Enhanced
- [ ] Reddit + NewsAPI virality signals
- [ ] Subscriber management (subscribe/unsubscribe commands per bot)
- [ ] Web scraping for sources without RSS
- [ ] Keyword trending tracker
- [ ] Activate Daily Astrology Bot (set active: true in bots.json, add sources + prompt)

### Phase 3 — Scale
- [ ] WhatsApp Business API integration
- [ ] Web dashboard for content review
- [ ] Analytics (engagement tracking per bot)
- [ ] Cloud hosting migration
- [ ] Multi-language expansion
- [ ] New bot onboarding in under 30 minutes (target)

---

## Key Decisions & Rationale

| Decision | Choice | Reason |
|----------|--------|--------|
| Human review | Mandatory | Prevent guardrail bypass, maintain quality |
| Virality fallback | Most-viewed | Ensure daily post even on slow news days |
| WhatsApp | Phase 3 | High complexity and cost vs Telegram |
| Hosting | Local first | No infra cost during development |
| Database | SQLite → PostgreSQL | Simple for MVP, scalable later |
| Language | Python | Best ecosystem for RSS, NLP, Telegram bots |
| AI Text Generation | gemini-2.5-pro via Euri | Best quality, Hindi/Hinglish support, cost-efficient |
| AI Image Generation | gemini-3-pro-image-preview via Euri | News-quality cover images per post |
| AI API Gateway | Euri (euron.one) | OpenAI-compatible, 200+ models, 200K free tokens/day |

---

## Coding Standards

### Documentation
- Every file must have a **module-level docstring** explaining what it does
- Every function must have a **docstring** explaining: what it does, parameters, and return value
- Add **inline comments** for any logic that isn't immediately obvious
- Use simple, plain English — this codebase is maintained by a Python beginner

Example function format:
```python
def fetch_rss_feed(url: str) -> list:
    """
    Fetches articles from a single RSS feed URL.

    Args:
        url (str): The RSS feed URL to fetch from.

    Returns:
        list: A list of article dictionaries with keys:
              title, link, published, summary, source.
              Returns empty list if fetch fails.
    """
    # Your code here
```

### Logging
- Every module must use Python's built-in `logging` library — never use `print()` for status messages
- Log levels to use:
  - `logging.DEBUG` — detailed step-by-step info (for development)
  - `logging.INFO` — normal operations (fetch started, post published)
  - `logging.WARNING` — something unexpected but not breaking (no articles found)
  - `logging.ERROR` — something failed (API call failed, DB write failed)
- All logs must include: timestamp, module name, log level, message
- Guardrail violations log to `logs/guardrail_violations.log`
- Publish history logs to `logs/publish_history.log`
- All other logs to `logs/app.log`

Example logging setup (in every module):
```python
import logging

# Get a logger named after this module (e.g. "aggregator.rss_fetcher")
logger = logging.getLogger(__name__)

# Usage
logger.info("Starting RSS fetch for bot: %s", bot_id)
logger.error("Failed to fetch feed %s: %s", url, str(error))
```

---

## What NOT to Do

- Never auto-publish without human approval
- Never fetch from non-whitelisted sources without cross-verification
- Never commit `.env` or API keys
- Never generate content that takes a political stance
- Never republish full article text (generate original summaries only — copyright)
- Never skip guardrail checks to meet a publishing deadline
