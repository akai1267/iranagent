# PLAN.md — Autonomous Political Intelligence System
## Milestones + Validations

*Voice, LLM abstraction, agent comms defined in prompt.md — not here.*

---

## STOP-AND-FIX RULE

Validation fails → stop → diagnose → fix → re-run → only then proceed.

| Severity | Definition | Action |
|---|---|---|
| CRITICAL | Agents down, DB corrupt, LLM calls failing, wrong model used | Stop. Fix before anything. |
| MAJOR | Posts not saving, questions lost on restart, rate limits crashing system | Stop. Fix before next milestone. |
| MINOR | Performance, incomplete but non-blocking | Log in Documentation.md, fix within milestone. |

---

## ARCHITECTURE

```
/
├── agents/
│   ├── orchestrator/
│   ├── monitor/
│   ├── researcher/
│   └── source_monitor/
├── memory/
│   ├── posts.db
│   ├── working_theories.md
│   └── stream.md
├── shared/
│   ├── base_agent.py       # BaseAgent, llm(), observe(), publish()
│   ├── schemas.py
│   └── rate_limiter.py     # Per-model rate limit tracker
├── frontend/
│   └── src/
├── api/
│   └── main.py
├── config/
│   ├── sources.yaml        # Complete — see below
│   ├── domain.yaml         # Complete — see below
│   └── resources.yaml      # Complete — see below
├── scripts/
│   └── validate.py         # Complete spec — see below
├── .env.example            # Complete — see below
├── fly.toml                # Fly.io deploy config
├── railway.json            # Railway deploy config
├── requirements.txt
└── docker-compose.yml
```

---

## COMPLETE CONFIG FILES

### config/sources.yaml
```yaml
rss_feeds:
  - url: "https://feeds.reuters.com/reuters/worldNews"
    outlet: "Reuters"
    type: "news_wire"
    reliability: 0.9

  - url: "https://www.iaea.org/feeds/topstories.xml"
    outlet: "IAEA"
    type: "official"
    reliability: 1.0

  - url: "https://iranintl.com/en/rss"
    outlet: "Iran International"
    type: "news_wire"
    reliability: 0.85

  - url: "https://www.rand.org/blog.xml"
    outlet: "RAND Corporation"
    type: "think_tank"
    reliability: 0.85

  - url: "https://www.crisisgroup.org/rss.xml"
    outlet: "International Crisis Group"
    type: "think_tank"
    reliability: 0.85

  - url: "https://www.brookings.edu/feed/"
    outlet: "Brookings Institution"
    type: "think_tank"
    reliability: 0.8

  - url: "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"
    outlet: "BBC Middle East"
    type: "news_wire"
    reliability: 0.85

  - url: "https://rss.nytimes.com/services/xml/rss/nyt/MiddleEast.xml"
    outlet: "New York Times"
    type: "news_wire"
    reliability: 0.85

x_accounts:
  # Verified OSINT/conflict reporters
  - handle: "sentdefender"
    priority: "high"
    reliability: 0.72
    notes: "Real-time OSINT, strong on military movements, occasional errors"
  - handle: "osint613"
    priority: "high"
    reliability: 0.70
    notes: "Israeli-focused OSINT, good on IDF/Iran axis"
  - handle: "faytuks"
    priority: "high"
    reliability: 0.75
    notes: "Conflict reporter, strong sourcing on Middle East events"
  - handle: "dailyirannews"
    priority: "high"
    reliability: 0.68
    notes: "Iran-specific aggregator, useful for domestic Iran news"

telegram_channels:
  # Iran/ME focused intel channels
  - channel: "ddgeopolitics"
    skepticism: "medium"
    reliability: 0.60
    priority: "high"
    notes: "Geopolitics aggregator, good reach, conservative reliability score"

  - channel: "geopolitics_prime"
    skepticism: "medium"
    reliability: 0.58
    priority: "medium"
    notes: "Aggregator, overlaps with ddgeopolitics"

  - channel: "warmonitors"
    skepticism: "medium"
    reliability: 0.62
    priority: "high"
    notes: "Active conflict monitoring, tends to be early on events"

  - channel: "Slavyangrad"
    skepticism: "high"
    reliability: 0.45
    priority: "medium"
    notes: "Russian milblog — valuable for proxy/Ukraine-Iran nexus, pro-Russian framing. Treat all claims with high skepticism. Useful for axis messaging signals."

  - channel: "colonelcassad"
    skepticism: "high"
    reliability: 0.45
    priority: "medium"
    notes: "Russian milblog — same caveats as Slavyangrad. Boris Rozhin. Cross-reference before treating as signal."

  - channel: "MiddleEastSpectator"
    skepticism: "medium"
    reliability: 0.63
    priority: "high"
    notes: "ME-focused, reasonable signal quality for regional developments"

  - channel: "Mediterranean_Man"
    skepticism: "medium"
    reliability: 0.60
    priority: "medium"
    notes: "Regional analysis, occasional good scoops"

  - channel: "intelslava"
    skepticism: "high"
    reliability: 0.45
    priority: "low"
    notes: "Russian-linked aggregator. Low reliability, use for Russian framing only"

  # Removed: paint_defender (general news, low Iran-specific value)
  # Removed: Rerum_Novarum (general US news aggregator, not Iran-focused)
  # Mediterranean_Man deduplicated (was listed twice)
```

### config/domain.yaml
```yaml
central_question: "What is actually happening with the Iran conflict and why does it matter?"

tether_rule: >
  Follow any topic — Chinese foreign policy, Russian energy economics, Lebanese domestic
  politics, Gulf state positioning — but only the parts that sharpen understanding of the
  Iran conflict. At every step ask: does this make my understanding of the conflict
  more precise? Stop when the answer is no.

domain: "Iran conflict"

initial_priors_prompt: >
  You are beginning to analyze the Iran conflict from scratch.
  Write 4-6 sparse initial working theories — the priors and analytical lenses
  a seasoned Iran analyst would bring on day one before reading anything specific.
  Not facts. Not summaries. The instincts that come from understanding how the
  region works, how Iran's regime operates, how proxy conflicts function.
  First person, direct voice. Each prior should be one or two sentences.
  Example format: "Regime survival is Iran's north star. Everything else is downstream of that."

scope_notes: >
  Relevant adjacent topics: IRGC structure and decision-making, Hezbollah operational status,
  Houthi Red Sea campaign, Hamas and Palestinian factions, Iraqi PMF, Syrian corridor,
  US CENTCOM posture, Israeli red lines, Saudi-Iran relations, China's role as oil buyer
  and diplomatic actor, Russia's drone relationship with Iran, nuclear enrichment status,
  JCPOA and its aftermath, Iranian domestic politics and dissent, economic pressure from sanctions.
```

### config/resources.yaml
```yaml
groq:
  models:
    fast:
      name: "llama-3.1-8b-instant"
      rpm_limit: 30
      tpm_limit: 20000
      default_temperature: 0.1
    standard:
      name: "llama-3.3-70b-versatile"
      rpm_limit: 30
      tpm_limit: 6000
      default_temperature: 0.3
    deep:
      name: "deepseek-r1-distill-llama-70b"
      rpm_limit: 30
      tpm_limit: 6000
      default_temperature: 0.7

  # When a model hits this fraction of its per-minute limit, go to LIGHT mode
  rate_limit_threshold: 0.8

  # How long to wait when rate limited before retrying (seconds)
  rate_limit_backoff: 62

mode_thresholds:
  # Fraction of per-minute token budget used to trigger mode change
  light_mode: 0.8    # >80% of any deep/standard model's tpm used this minute
  minimal_mode: 0.95 # >95% used

poll_intervals:
  full: 300      # 5 minutes
  light: 900     # 15 minutes
  minimal: 3600  # 1 hour

dive_budget:
  # Max LLM calls per deep dive (controls cost/depth tradeoff)
  full: 15
  light: 0       # no deep dives in light mode
  minimal: 0

stream:
  max_age_hours: 48
  wipe_interval_hours: 6
```

### .env.example
```bash
# Groq API — https://console.groq.com
GROQ_API_KEY=your_groq_api_key_here

# X (Twitter) API v2 — https://developer.twitter.com
# Free tier: read-only, 500k tweets/month
TWITTER_BEARER_TOKEN=your_twitter_bearer_token_here

# Telegram API — https://my.telegram.org
# Free — create an app to get these
TELEGRAM_API_ID=your_telegram_api_id_here
TELEGRAM_API_HASH=your_telegram_api_hash_here
TELEGRAM_PHONE=your_phone_number_here  # for session auth

# Tavily search — https://tavily.com
# Free tier: 1000 searches/month
TAVILY_API_KEY=your_tavily_api_key_here

# Redis URL — set by Railway/Fly automatically, override for local dev
REDIS_URL=redis://localhost:6379

# Environment
ENV=development  # development | production
```

---

## validate.py SPECIFICATION

`scripts/validate.py` must implement every check referenced in Plan.md milestones.

```python
"""
scripts/validate.py

Usage:
  python scripts/validate.py --mode infrastructure
  python scripts/validate.py --agent monitor --duration 300
  python scripts/validate.py --agent monitor --check-sources x,telegram
  python scripts/validate.py --agent orchestrator --test-interrupts
  python scripts/validate.py --agent orchestrator --test-resource-modes
  python scripts/validate.py --check-stream-format
  python scripts/validate.py --check-signal-reliability
  python scripts/validate.py --check-posts --voice --last 5
  python scripts/validate.py --check-post-immutability
  python scripts/validate.py --check-questions-table
  python scripts/validate.py --check-observatory-working-events
  python scripts/validate.py --test-interrupt-flow
  python scripts/validate.py --test-conversation --voice-check --check-citations
  python scripts/validate.py --quick
  python scripts/validate.py --full
"""

# Each check must:
# - Print what it's checking
# - Print PASS or FAIL with reason
# - Exit with code 0 (all pass) or 1 (any fail)
# - --full runs all checks in sequence, stops on CRITICAL failure

CHECKS = {
    "infrastructure": [
        "db_tables_exist",          # posts, posts_fts, questions tables in posts.db
        "fts5_working",             # INSERT a row, search it, confirm match
        "all_heartbeats_present",   # heartbeat:{agent} keys in Redis for all 3 agents
        "observatory_channel_live", # can publish and receive on channel:observatory
        "config_files_valid",       # sources.yaml, domain.yaml, resources.yaml parse without error
        "env_vars_present",         # all required .env vars present
    ],

    "stream_format": [
        # Each line in stream.md must match:
        # [YYYY-MM-DD HH:MM] [SIGNIFICANCE] [PLATFORM] [OUTLET] headline — why — url
        "stream_line_format",
        "stream_timestamps_valid",
        "stream_significance_valid",  # only low/medium/high/critical
    ],

    "signal_reliability": [
        # Every Signal published to orchestrator must have reliability field
        # reliability must be float 0.0-1.0
        "signal_has_reliability_field",
        "signal_reliability_in_range",
    ],

    "posts_voice": [
        # Automated banned phrase check on last N posts
        "no_banned_phrases",  # "remains to be seen", "multiple competing assessments",
                              # "it is unclear", "analysts argue", "some analysts suggest"
        "posts_not_empty",
        "posts_have_sources",  # every post should contain at least one "per " or "reported" or "confirmed"
    ],

    "post_immutability": [
        # posts table has no UPDATE statements in codebase (grep check)
        # posts_fts triggers are working (delete trigger fires on delete)
        "no_post_updates_in_code",
        "fts_triggers_working",
    ],

    "questions_table": [
        # questions table exists and has rows
        # answered_at NULL for open questions
        # priority_score populated
        "questions_table_has_rows",
        "open_questions_have_priority_scores",
    ],

    "observatory_working_events": [
        # In last 100 observatory events, every 'done' event has a preceding 'working' event
        # working events have non-empty summary
        "working_events_precede_done_events",
        "working_events_have_content",
    ],

    "interrupt_flow": [
        # Send mock CRITICAL signal, verify researcher receives interrupt within 5s
        # Send mock LOW signal, verify researcher does NOT receive interrupt
        "critical_signal_reaches_researcher",
        "low_signal_does_not_interrupt",
        "medium_signal_queued_correctly",
    ],

    "conversation": [
        # POST /chat with test question, verify response within 30s
        # voice check on response (banned phrases)
        # citation check: response contains at least one "as I wrote" or date reference
        "response_within_30s",
        "response_voice_check",
        "response_has_citation",
    ],

    "model_routing": [
        # Verify fast model used for significance assessments (check logs/observatory)
        # Verify deep model used for post writing
        "fast_model_for_triage",
        "deep_model_for_posts",
    ],

    "rate_limit_handling": [
        # Simulate rate limit response from Groq, verify system waits and retries
        # Verify system does not crash or switch models mid-thought
        "rate_limit_triggers_wait",
        "no_crash_on_rate_limit",
    ],

    "frontend_design": [
        # Grep frontend/src for banned CSS values
        "no_border_radius_over_4px",    # grep for rounded-lg, rounded-xl, rounded-2xl
        "no_pure_white_backgrounds",    # grep for #ffffff, bg-white
        "no_cool_grey_backgrounds",     # grep for Tailwind cool greys (gray-100, gray-50)
        "google_fonts_loaded",          # index.html contains Playfair Display + DM Sans + JetBrains Mono
        "playfair_on_post_titles",      # PostCard.jsx uses font-display / Playfair
        "jetbrains_on_timestamps",      # timestamp elements use font-mono
        "design_tokens_in_index_css",   # index.css contains --accent, --bg, --font-display
        "observatory_websocket_exists", # useObservatory.js exists and contains WebSocket
        "all_four_views_exist",         # Feed.jsx, Theories.jsx, Chat.jsx, Observatory.jsx all present
        "ticker_component_exists",      # Ticker.jsx exists with hidden-by-default state
    ],
}

QUICK_CHECKS = ["infrastructure", "stream_format", "posts_voice", "questions_table"]
FULL_CHECKS = list(CHECKS.keys())
# Note: frontend_design checks are grep-based and fast.
# The manual visual checklist in Frontend.md must also be verified by a human.
```

---

## MILESTONE 0 — Infrastructure
**Goal:** Everything starts. DB initialized. Config valid. LLM abstraction working with Groq.

### Tasks
- [ ] Repo structure per architecture above
- [ ] All config files written exactly as specified above
- [ ] `.env.example` written exactly as specified above
- [ ] `requirements.txt` — exact versions as specified in Frontend.md
- [ ] `docker-compose.yml` with Redis + three agent containers + API + frontend
- [ ] Dockerfiles for all four services (orchestrator, monitor, researcher, api) + frontend — exact contents in Frontend.md
- [ ] `frontend/nginx.conf` — contents in Frontend.md
- [ ] `shared/schemas.py` — AgentMessage, Signal, Post, ObservabilityEvent
- [ ] `shared/rate_limiter.py` — per-model RPM/TPM tracker with window reset logic
- [ ] `shared/base_agent.py` — BaseAgent with `llm()`, `observe()`, `publish()`, `heartbeat_loop()`
- [ ] `llm()` implements: model alias resolution, Groq API call, think-block stripping, JSON fence stripping, working/done events, token reporting, rate limit wait-and-retry
- [ ] `scripts/init_db.py` — creates posts.db with all tables, FTS5, triggers, questions table
- [ ] `scripts/validate.py` — skeleton with all checks stubbed (implement checks as milestones complete)
- [ ] `working_theories.md` and `stream.md` created empty
- [ ] `/health` endpoint
- [ ] Railway deploy config (`railway.json`) and Fly.io config (`fly.toml`)

### Rate limiter
```python
# shared/rate_limiter.py
import time
from collections import defaultdict

class RateLimiter:
    """Per-model sliding window rate tracker"""
    def __init__(self, model_configs: dict):
        self.configs = model_configs
        self.request_times = defaultdict(list)   # model -> [timestamps]
        self.token_counts = defaultdict(list)    # model -> [(timestamp, tokens)]

    def can_call(self, model_alias: str) -> bool:
        cfg = self.configs[model_alias]
        now = time.time()
        window = 60  # 1 minute window

        # clean old entries
        self.request_times[model_alias] = [
            t for t in self.request_times[model_alias] if now - t < window
        ]
        self.token_counts[model_alias] = [
            (t, tok) for t, tok in self.token_counts[model_alias] if now - t < window
        ]

        req_count = len(self.request_times[model_alias])
        tok_count = sum(tok for _, tok in self.token_counts[model_alias])

        req_ok = req_count < cfg["rpm_limit"] * self.configs.get("rate_limit_threshold", 0.8)
        tok_ok = tok_count < cfg["tpm_limit"] * self.configs.get("rate_limit_threshold", 0.8)

        return req_ok and tok_ok

    def record_call(self, model_alias: str, tokens: int):
        now = time.time()
        self.request_times[model_alias].append(now)
        self.token_counts[model_alias].append((now, tokens))

    def seconds_until_reset(self, model_alias: str) -> float:
        times = self.request_times[model_alias]
        if not times:
            return 0
        oldest = min(times)
        return max(0, 60 - (time.time() - oldest))
```

### Acceptance Criteria
- [ ] `docker-compose up` starts all services cleanly
- [ ] `/health` returns all agents ok
- [ ] posts.db has all tables and FTS5 triggers verified
- [ ] Test `llm()` call: uses correct model, strips think blocks, reports tokens, publishes working/done events
- [ ] Rate limiter correctly tracks and blocks when threshold hit
- [ ] `validate.py --mode infrastructure` PASS

### Validation
```bash
docker-compose up -d && sleep 15
curl http://localhost:8000/health
python scripts/validate.py --mode infrastructure
```

---

## MILESTONE 1 — Monitor (RSS + news)
*(Tasks, acceptance criteria, validation identical to previous version — now uses `self.llm(prompt, model="fast")` for significance assessment)*

Key change from previous: all Monitor LLM calls use `model="fast"` (llama-3.1-8b-instant). Signal includes `reliability` field from sources.yaml.

### Validation
```bash
python scripts/validate.py --agent monitor --duration 300
python scripts/validate.py --check-stream-format
python scripts/validate.py --check-signal-reliability
```

---

## MILESTONE 2 — Monitor (X + Telegram)
**Goal:** X (Twitter) and Telegram ingestion running. Social skepticism applied. All configured sources polling.

### Tasks
- [ ] Add `poll_x_loop()`, `_poll_x_account()`, `_process_x_queue()`, `_x_queue_processor()` to MonitorAgent (code in Implement.md M2)
- [ ] Add `poll_telegram_loop()`, `_poll_telegram_channel()` to MonitorAgent (code in Implement.md M2)
- [ ] Update `__init__` and `start()` gather (code in Implement.md M2)
- [ ] Add `import os` to monitor imports
- [ ] Add `TWITTER_BEARER_TOKEN` env check — disable X polling gracefully if missing
- [ ] Add `TELEGRAM_API_ID/HASH` env check — disable Telegram polling gracefully if missing
- [ ] **Telegram first-run auth:** run container interactively once to save session file:
  ```bash
  docker-compose run -it monitor python -c "
  from telethon.sync import TelegramClient
  import os
  c = TelegramClient('/memory/telegram_session',
      int(os.environ['TELEGRAM_API_ID']),
      os.environ['TELEGRAM_API_HASH'])
  c.start(phone=os.environ['TELEGRAM_PHONE'])
  print('Session saved at /memory/telegram_session')
  "
  ```
- [ ] Confirm session file exists at `/memory/telegram_session` before running normally
- [ ] SOCIAL_SKEPTICISM prefix applied in X and Telegram assessment prompts
- [ ] Reliability scores from sources.yaml passed into significance prompts (not hardcoded)
- [ ] All 4 X accounts polling: sentdefender, osint613, faytuks, dailyirannews
- [ ] All 8 Telegram channels polling (see sources.yaml)
- [ ] `handle()` responds to `reload_sources` from SourceMonitor by re-reading sources.yaml

### Key design notes
- X calls are synchronous (tweepy) — wrapped in `asyncio.to_thread()`
- Telegram calls are async (telethon) — run natively in event loop
- Social sources get skepticism prefix in the prompt AND stored in stream, so downstream LLMs always see the provenance caveat
- CRITICAL signals from Telegram require corroboration note — LLM told to require corroboration before rating CRITICAL for Telegram

### Validation
```bash
python scripts/validate.py --agent monitor --check-sources x,telegram
python scripts/validate.py --check-stream-format
# Manual: tail -f memory/stream.md — confirm X and Telegram entries appearing
# Manual: confirm skepticism prefix in stream entries for social sources
```

---

## MILESTONE 2b — Source Health Monitor
**Goal:** Fourth agent running. Source health checked every 6 hours. Proposals surfaced to UI. Human approves/rejects.

### Tasks
- [ ] `agents/source_monitor/agent.py` — full code in Implement.md Source Health Monitor section
- [ ] `agents/source_monitor/main.py` — same pattern as other agents
- [ ] `agents/source_monitor/Dockerfile` — same pattern, code in Implement.md
- [ ] Add `source_monitor` service to docker-compose.yml (already in Implement.md)
- [ ] `GET /source-proposals` API endpoint (code in Implement.md)
- [ ] `POST /source-proposals/{id}/approve` and `/reject` API endpoints
- [ ] `/memory/source_proposals.json` initialized as `[]` in M0
- [ ] Monitor agent handles `reload_sources` message — reloads sources.yaml without restart
- [ ] Source proposals visible in UI (optional M6 enhancement — a simple collapsible panel)
- [ ] Add `source_monitor` heartbeat to `/health` endpoint

### Notes
- Agent does NOT auto-add sources to sources.yaml. Proposes only.
- Reliability scores in sources.yaml are the reliability passed to significance assessment
- slavyangrad and colonelcassad: reliability 0.45, skepticism "high" — still included because
  Russian milblogs are often first on proxy-related developments. The LLM sees the skepticism
  note and adjusts threshold accordingly.
- CANDIDATE_POOL in agent code is the only place new sources can come from — not open web search

### Validation
```bash
python scripts/validate.py --agent source_monitor
# Manual: check /memory/source_proposals.json exists
# Manual: GET http://localhost:8000/source-proposals returns []
```

---

## MILESTONE 3 — Orchestrator
*(Tasks identical to previous version)*

Key changes:
- Resource tracking now tracks per-model RPM/TPM via RateLimiter, not total tokens
- Mode transitions based on rate limit thresholds per resources.yaml
- Mode resets to FULL when rate limit window resets (auto, within ~60s)

### Validation
```bash
python scripts/validate.py --agent orchestrator --test-interrupts
python scripts/validate.py --agent orchestrator --test-resource-modes
```

---

## MILESTONE 4 — Researcher (reactive + posting)
*(Tasks identical to previous version)*

Key changes:
- All post-writing uses `model="deep"` (deepseek-r1-distill-llama-70b)
- Post judgment uses `model="fast"`
- Stream assessment uses `model="standard"`
- Question prioritization uses `model="standard"`
- Working theories update check uses `model="standard"`
- Working theories rewrite uses `model="deep"`
- Voice prompt includes good/bad examples from prompt.md

### Model routing in Researcher
```python
# Explicit model assignments — do not change without updating prompt.md
CALL_MODELS = {
    "post_judgment":        "fast",      # yes/no, cheap
    "stream_assessment":    "standard",  # moderate reasoning
    "question_priority":    "standard",  # moderate reasoning
    "tether_check":         "standard",  # moderate reasoning
    "theories_update_check":"standard",  # moderate reasoning
    "write_post":           "deep",      # voice-critical
    "update_theories":      "deep",      # voice-critical
    "answer_question":      "deep",      # voice-critical
    "seed_theories":        "deep",      # voice-critical
}
```

### Validation
```bash
python scripts/validate.py --check-posts --voice --last 5
python scripts/validate.py --check-post-immutability
python scripts/validate.py --check-questions-table
python scripts/validate.py --check-observatory-working-events
python scripts/validate.py --model-routing  # verifies right model used per call type
```

---

## MILESTONE 5 — Researcher (deep dive + conversation)
*(Tasks identical to previous version)*

Key changes:
- Tether checks in dive loop use `model="standard"`
- Deep dive synthesis and post writing use `model="deep"`
- Before starting dive: check RateLimiter for deep model availability
- If rate limited: wait for window reset, log to observatory, then proceed
- Conversation responses use `model="deep"`

### Rate limit handling in dive loop
```python
async def deep_dive(self, question, question_id):
    budget = self.resources["dive_budget"].get(self.mode, 0)
    if budget == 0:
        return

    calls = 0
    while calls < budget:
        # check rate limit before expensive call
        if not self.rate_limiter.can_call("deep"):
            wait = self.rate_limiter.seconds_until_reset("deep")
            await self.observe("decide", f"Rate limit — waiting {wait:.0f}s for window reset")
            await asyncio.sleep(wait + 1)

        # ... rest of loop
```

### Validation
```bash
python scripts/validate.py --test-conversation --voice-check --check-citations
python scripts/validate.py --rate-limit-handling
```

---

## MILESTONE 6 — Frontend
**Goal:** All four views working. Design system enforced. Real-time behavior correct. Visual checklist in Frontend.md passes completely.

*Full design spec in Frontend.md — read it before writing a single component. Every color, font, radius, and spacing value comes from that file. Tailwind defaults that conflict are overridden.*

### Component tree

```
frontend/src/
├── index.css              # Design system tokens (:root variables), base reset, animations
├── main.jsx               # React entry, mounts <App />
├── App.jsx                # Root layout: header, ticker, two-column split, WebSocket provider
├── hooks/
│   ├── useObservatory.js  # WebSocket connection to ws://.../ws/observatory, returns events[]
│   ├── usePosts.js        # Polls GET /posts every 30s, returns posts[], addPost()
│   ├── useQuestions.js    # Polls GET /questions every 30s, returns questions[]
│   └── useTheories.js     # Polls GET /working-theories every 60s, returns {content, updatedAt}
├── components/
│   ├── layout/
│   │   ├── Header.jsx         # Wordmark + live dot + date
│   │   ├── Ticker.jsx         # Breaking news ticker — hidden until CRITICAL signal
│   │   └── TabNav.jsx         # FEED · THEORIES · CHAT tab switcher
│   ├── observatory/
│   │   ├── Observatory.jsx    # Right panel container, auto-scroll, pause-on-hover
│   │   └── EventRow.jsx       # Single collapsible event row, working pulse, expand/collapse
│   ├── feed/
│   │   ├── Feed.jsx           # Feed view container, tag filter, open questions panel
│   │   ├── OpenQuestions.jsx  # Collapsible questions panel above posts
│   │   ├── PostCard.jsx       # Single post: title, body, tags, timestamp, expand/collapse
│   │   └── PostBody.jsx       # Expanded post content, supersession links
│   ├── theories/
│   │   └── Theories.jsx       # Rendered markdown, lede treatment, update highlight
│   └── chat/
│       ├── Chat.jsx           # Conversation container, message history, input row
│       ├── Message.jsx        # Single message — user style vs system style
│       └── ChatInput.jsx      # Textarea, urgent toggle, send button
└── lib/
    └── tagColors.js           # Tag → border color mapping from Frontend.md
```

### Tasks

**Setup:**
- [ ] `npm create vite@latest frontend -- --template react`
- [ ] Install dependencies: `tailwindcss`, `@tailwindcss/typography`, `react-markdown`
- [ ] `index.css`: copy full `:root` token block from Frontend.md, base reset, all animations
- [ ] Override Tailwind config: `borderRadius: { sm: '2px', md: '4px', DEFAULT: '2px' }` — never rounded-lg or larger
- [ ] Import Google Fonts in index.html: Playfair Display, DM Sans, JetBrains Mono (exact weights from Frontend.md)

**Hooks:**
- [ ] `useObservatory`: WebSocket, reconnects on disconnect, returns events array (max 500), exposes isConnected
- [ ] `usePosts`: polls every 30s, deduplicates by id, newest first
- [ ] `useQuestions`: polls every 30s, sorted by priority_score DESC
- [ ] `useTheories`: polls every 60s, tracks previous content to detect changes for highlight animation

**Layout (App.jsx):**
- [ ] `border-top: 4px solid var(--accent)` on body
- [ ] Header: 52px, `--bg-warm`, wordmark in Playfair 900, live dot blinking, date in JetBrains Mono
- [ ] Ticker: hidden by default, fires when observatory receives event with significance=critical
- [ ] Two-column split: left 65%, right 35%, both `height: 100vh`, `overflow-y: auto`
- [ ] Right panel background: `--bg-panel` (#ece8e1), visibly distinct from left

**Observatory (right panel):**
- [ ] EventRow: timestamp + icon + agent tag (color-coded) + summary, one line collapsed
- [ ] Expand/collapse on click when detail present, smooth height transition
- [ ] Working events: left-border in agent color, summary text pulses via `working-pulse` animation
- [ ] Done events: working row updated in-place — icon ⏳ → ✓, pulse stops
- [ ] Auto-scroll to top (newest), pause on hover, resume on mouse-leave
- [ ] Agent colors: orchestrator=amber (#b45309), monitor=navy (#1c509b), researcher=forest (#166534)

**Feed view:**
- [ ] OpenQuestions panel: collapsible, card-accent-left amber border, priority scores right-aligned
- [ ] PostCard: border-top color from primary tag via tagColors.js
- [ ] Post title: Playfair Display 700, 1.25em
- [ ] Post body preview: first 3-4 sentences, fades at bottom with gradient mask
- [ ] Expand inline on "Read more" click — no navigation, smooth height animation
- [ ] Superseded post: opacity 0.6, [UPDATED] amber tag, link to newer post
- [ ] New posts: `slide-in-top` animation on arrival
- [ ] Tag filter row: clicking a tag filters list to matching posts
- [ ] Empty state: "● Researcher is working..." with live dot

**Theories view:**
- [ ] Renders working_theories.md as markdown via react-markdown
- [ ] First paragraph: lede-quote treatment (Georgia italic, border-left crimson)
- [ ] Body: DM Sans 0.94em, line-height 1.75, generous paragraph spacing
- [ ] On content change: `highlight-fade` animation on updated sections
- [ ] Last updated timestamp: JetBrains Mono, --faint, right-aligned

**Chat view:**
- [ ] Message history: user messages in JetBrains Mono 0.75em --faint, system in DM Sans 0.92em
- [ ] No bubbles, no avatars — flat document style
- [ ] Post citations rendered as clickable links that switch to Feed tab and highlight the referenced post
- [ ] Before response: "● thinking..." with live-dot animation
- [ ] Input: auto-growing textarea, urgent checkbox, send on Enter (Shift+Enter for newline)
- [ ] POST /chat → poll `channel:response:{trace_id}` via WebSocket or timeout fallback

**Design system enforcement:**
- [ ] Zero instances of border-radius > 4px anywhere in the codebase
- [ ] Zero pure white (#ffffff) backgrounds
- [ ] Zero cool grey backgrounds
- [ ] All timestamps in JetBrains Mono
- [ ] All tags in JetBrains Mono uppercase
- [ ] All post headlines in Playfair Display

### Acceptance Criteria
- [ ] All items in Frontend.md done-when visual checklist pass
- [ ] Observatory updates in real time, working events pulse, done events stop pulse
- [ ] Post feed renders correctly, expand/collapse works, tag filter works
- [ ] Theories renders markdown with correct lede treatment
- [ ] Chat returns responses, citations are clickable, urgent toggle works
- [ ] Ticker hidden at rest, fires on CRITICAL signal
- [ ] No Tailwind default overriding design system tokens visible anywhere

### Validation
```bash
python scripts/validate.py --frontend-design
# Checks: no banned CSS values (border-radius > 4px, #ffffff backgrounds, cool greys)
# Checks: Google Fonts loaded in HTML
# Manual: open http://localhost:3000, verify against Frontend.md done-when checklist
# Manual: confirm Playfair on post titles, JetBrains Mono on all timestamps and tags
```

---

## MILESTONE 7 — Deploy + Hardening
**Goal:** Running on Railway or Fly.io free tier. All validations pass. Zero cost.

### Railway deploy
```json
// railway.json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE"
  },
  "deploy": {
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

### Fly.io deploy
```toml
# fly.toml
app = "iran-intel"
primary_region = "iad"

[build]
  dockerfile = "Dockerfile"

[env]
  ENV = "production"

[[services]]
  internal_port = 8000
  protocol = "tcp"

  [[services.ports]]
    port = 80
    handlers = ["http"]

  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]

[mounts]
  source = "memory_vol"
  destination = "/memory"
```

### Tasks
- [ ] Deploy to Railway or Fly.io free tier
- [ ] Persistent volume mounted at /memory (posts.db, working_theories.md, stream.md survive redeploys)
- [ ] Telegram session file persisted on volume (not lost on container restart)
- [ ] Redis provisioned (Railway Redis plugin or Fly Redis)
- [ ] All env vars set in deploy platform
- [ ] 24-hour stability run
- [ ] Verify rate limit management under real load
- [ ] Verify stream wipe cycle
- [ ] All validate.py checks pass

### Final validation
```bash
python scripts/validate.py --full
# Expected: all checks PASS
```

---

*Plan.md derives from prompt.md. Voice, LLM abstraction, agent comms defined in prompt.md only. Decision log canonical in Documentation.md.*
