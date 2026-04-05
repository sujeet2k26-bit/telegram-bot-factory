# CLAUDE.md — Telegram Bot Factory

Project index. Detailed rules live in the `rules/` folder.

---

## Project Overview

Multi-bot publishing platform for Telegram. One shared backend drives any number of content bots across different domains and languages:
- Each bot is defined entirely by a config entry in `bots.json` + one prompt file
- Shared pipeline handles fetch → filter → score → generate → review → publish for every bot
- Human review is mandatory — no post is ever published without explicit approval
- Currently running: AI News (English), Bollywood (Hindi/Hinglish), Daily Astrology (Hindi/Hinglish)
- Adding a new bot requires zero changes to core pipeline code

---

## Bots

| Bot | Channel | Language | Posts/Day | Status |
|-----|---------|----------|-----------|--------|
| AI News Bot | `@ai26news` | English | 1 digest/day | Active |
| Bollywood Buzz Bot | `@bollywood_daily_gossip` | Hindi/Hinglish | 2 digests/day | Active |
| Daily Astrology Bot | `@astrochhayah` | Hindi/Hinglish | 1 panchang post/day | Built, inactive |

- All bots share one backend codebase — adding a bot = config entry + prompt file only
- Each bot uses its own Telegram token for publishing **and** for the review flow
- Each bot can route reviews to a **different reviewer Telegram account** via per-bot reviewer chat IDs

---

## Detailed Rules

| File | Contents |
|------|----------|
| [`.claude/rules/content.md`](.claude/rules/content.md) | Post formats, digest formats, Read more links, pipeline flow |
| [`.claude/rules/scoring.md`](.claude/rules/scoring.md) | Virality scoring, source weights, diversity caps, fallback, scheduling |
| [`.claude/rules/guardrails.md`](.claude/rules/guardrails.md) | All 6 guardrail categories, AI relevance filter, logging rules |
| [`.claude/rules/review_interface.md`](.claude/rules/review_interface.md) | Review commands, /generate, bot token routing, known behaviour |
| [`.claude/rules/architecture.md`](.claude/rules/architecture.md) | Bot config schema, folder structure, how to add a bot, env vars, HTML mode |
| [`.claude/rules/sources.md`](.claude/rules/sources.md) | All trusted sources for AI and Bollywood, with categories and weights |
| [`.claude/rules/coding_standards.md`](.claude/rules/coding_standards.md) | Docstrings, logging, error handling, what not to do |

---

## Development Phases

### Phase 1 — Local MVP ✅
- [x] RSS fetcher (AI + Bollywood)
- [x] Deduplication
- [x] Guardrail content filter (pre + post generation)
- [x] Virality scoring with source weight multipliers
- [x] Source + topic diversity caps (max 2 per source, max 2 per movie/topic)
- [x] Digest generation via Gemini 2.5 Pro (top 5 articles)
- [x] Cover image generation via Gemini image model
- [x] Read more links injected into each digest entry
- [x] Human review via Telegram (Approve/Reject buttons + commands)
- [x] On-demand generation via `/generate` command in reviewer chat
- [x] Publish scheduler (IST timezone, APScheduler)
- [x] SQLite database
- [x] Two separate bots + channels (AI News + Bollywood)
- [x] Daily Astrology Bot — panchang scraping, Hinglish post, spiritual cover image
- [x] Per-bot reviewer chat IDs (different Telegram accounts per bot)
- [x] All 3 review bots auto-start on `python main.py` (one thread each)
- [x] `/generate` cross-bot: works from any reviewer chat without 403 errors
- [x] `/killstale` command — kills stale Python processes via Telegram
- [x] Astrology social card: auto-height canvas, full text wrap (no truncation)

### Phase 2 — Enhanced
- [ ] Reddit + NewsAPI virality signals
- [ ] Subscriber management (subscribe/unsubscribe per bot)
- [ ] Web scraping for sources without RSS
- [ ] Keyword trending tracker
- [ ] Activate Daily Astrology Bot on schedule

### Phase 3 — Scale
- [ ] WhatsApp Business API integration
- [ ] Web dashboard for content review
- [ ] Engagement analytics per bot
- [ ] Cloud hosting migration
- [ ] New bot onboarding target: under 30 minutes

---

## Key Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Human review | Mandatory | Prevent guardrail bypass, maintain quality |
| Post format | Digest (5 stories) | More value per post than single-article posts |
| Read more links | Injected post-generation | AI doesn't track URLs reliably; we inject them after |
| Telegram formatting | HTML mode | MarkdownV1 breaks on AI-generated special characters |
| Topic diversity | Max 2 per movie | Prevents box office update flooding in Bollywood digest |
| Virality fallback | Best available | Ensures daily post even on slow news days |
| AI text | gemini-2.5-pro via Euri | Best quality, Hindi/Hinglish support, cost-efficient |
| AI images | gemini-2-pro-image-preview via Euri | News-quality cover images per post |
| API gateway | Euri (euron.one) | OpenAI-compatible, 200+ models, 200K free tokens/day |
| Database | SQLite → PostgreSQL | Simple for MVP, scalable later |
| Hosting | Local first | No infra cost during development |
| Astrology data | Drik Panchang scrape + date fallback | No free API; BeautifulSoup parses tithi/nakshatra |
| Astrology pipeline | Single article (not digest) | One panchang post per day, not a multi-story digest |
| Per-bot reviewer | `TELEGRAM_<BOT>_REVIEWER_CHAT_ID` | Different Telegram accounts can review different bots |
| Cross-bot `/generate` | Routes via `context.bot` + current `chat_id` | Avoids 403 Forbidden when generating AI/Bollywood posts from astrology reviewer chat |
| `/killstale` | Kills all Python PIDs except current | One-tap fix for 409 Conflict / frozen `/card` or `/generate` without restarting server |
| Social card height | Auto-calculated from dry run | Fixed content truncation — card grows to fit all bullet text |
