# DOCUMENTATION.md — Autonomous Political Intelligence System
## Shared Memory & Audit Log

> Updated after every milestone. Canonical decision log — do not duplicate in other files.

---

## CURRENT STATUS

| Item | Value |
|---|---|
| **Active Milestone** | M7 — Deploy + Hardening |
| **Agents Running** | 0 / 4 (not started in this environment) |
| **Posts Published** | 0 |
| **Open Questions** | 0 |
| **Stream Entries** | 0 |
| **Working Theories** | File created (seeds on first live run) |
| **Blocking Issues** | Missing deploy keys (Groq/Twitter/Tavily) + Docker not installed locally |
| **Last Updated** | March 12, 2026 |

---

## MILESTONE STATUS

| Milestone | Status | Validated | Notes |
|---|---|---|---|
| M0 Infrastructure | ✅ Implemented | Partial | File/runtime checks done locally; full container run pending Docker + keys |
| M1 Monitor (RSS/news) | ✅ Implemented | Partial | Code + model routing in place; live source polling pending keys |
| M2 Monitor (X/Telegram) | ✅ Implemented | Partial | Social skepticism + reliability prompts implemented; live auth pending keys/session |
| M2b Source Health Monitor | ✅ Implemented | Partial | Agent + API approve/reject flow implemented; live loop pending runtime |
| M3 Orchestrator | ✅ Implemented | Partial | Interrupt/resource routing implemented; live interrupt test pending runtime |
| M4 Researcher (reactive + posting) | ✅ Implemented | Partial | Posting/theories/question priority loop implemented; live publishing pending runtime |
| M5 Researcher (deep dive + convo) | ✅ Implemented | Partial | Deep-dive/tether/conversation paths implemented; end-to-end pending keys |
| M5b API | ✅ Implemented | Partial | Endpoints + WebSocket implemented; live health/chat pending stack up |
| M6 Frontend | ✅ Implemented | ✅ Static | Build + design/model-routing/rate-limit static checks pass |
| M7 Deploy + Hardening | ⏳ Pending deploy | — | Waiting credentials + platform deploy |

---

## HOW TO RUN

### Local dev
```bash
git clone [repo] && cd iran-intel
cp .env.example .env
# Fill all vars — see .env.example for full list and where to get each key

docker-compose up -d
sleep 15
curl http://localhost:8000/health
```

Expected:
```json
{"status": "ok", "agents": {"orchestrator": "ok", "monitor": "ok", "researcher": "ok"}}
```

### Watch it work
```
open http://localhost:3000
```
- **Observatory** — real-time. Working events pulse during LLM calls. Expand any event for full I/O.
- **Feed** — published posts. Tag filter. Supersession chain.
- **Theories** — current working_theories.md.
- **Chat** — direct conversation with cited responses.

### Read things directly
```bash
# Last 10 posts
sqlite3 memory/posts.db "SELECT timestamp, title FROM posts ORDER BY timestamp DESC LIMIT 10;"

# Full latest post
sqlite3 memory/posts.db "SELECT content FROM posts ORDER BY timestamp DESC LIMIT 1;"

# Open questions by priority
sqlite3 memory/posts.db "SELECT question, priority_score FROM questions WHERE answered_at IS NULL ORDER BY priority_score DESC;"

# Working theories
cat memory/working_theories.md

# Stream (last 50 lines)
tail -50 memory/stream.md
```

### Validate
```bash
python scripts/validate.py --quick   # infrastructure + stream + posts + questions
python scripts/validate.py --full    # all 10 check groups
```

---

## DEMO FLOW

*Run after M6 complete.*

```
1. docker-compose up -d && open http://localhost:3000

2. Observatory — watch monitor ingest, see [fast] model calls for significance
   Expand a significance decision — confirm reliability score in prompt
   Confirm working events pulse (never frozen)

3. Wait for medium+ signal to reach researcher
   Observatory: Orchestrator routes → Researcher wakes → fast model judges → 
   deep model writes (if warranted)
   Confirm: model labels visible in observatory events

4. Feed tab — read first post
   Voice check: direct, has a take, not a summary, sources cited informally
   If it's bad: check VOICE_PROMPT in researcher, check temperature (should be 0.7)

5. Theories tab — seeded and readable
   Check: first person, analytical priors, not a fact list

6. Chat: "What's actually happening right now?"
   Should get a direct, opinionated, cited response within 30s
   Check observatory: deep model used for answer

7. Chat: "What's your read on the proxy escalation?"
   Should take a position, wrestle with complexity, cite own posts

8. python scripts/validate.py --full
```

---

## DECISIONS LOG

*Canonical. Do not duplicate in Plan.md or Implement.md.*

| # | Decision | Context | Choice | Rationale |
|---|---|---|---|---|
| D001 | Three agents | Considered more | Orchestrator + Monitor + Researcher | Writing and reasoning are the same act. Meta-cognition continuous in Orchestrator. |
| D002 | No vector store | Considered Chroma | SQLite FTS5 + live web search | Posts searchable by FTS5 recency-weighted. Working theories in context. Web handles external. |
| D003 | No knowledge graph | Considered Neo4j | None | LLMs reason better over text than structured nodes. Extraction is lossy. |
| D004 | Posts immutable | Considered live updates | New post supersedes old | Honest record of thinking evolution. |
| D005 | Stream ephemeral | Considered full history | Last 48hrs, wipe every 6hrs | Breaking intel becomes public picture quickly. Long-term memory lives in posts. |
| D006 | Working theories high-threshold | Considered updating often | Updates only on how-I-think shifts | New facts → post feed. Priors → working theories. Different things. |
| D007 | Self-managed tempo | Considered hardcoded schedules | Orchestrator tracks rate limits dynamically | System operates according to actual constraints. Resets with rate limit windows. |
| D008 | Full observability + working events | Considered narration | Full I/O, collapsible, working event pre-call | Working event prevents frozen appearance during 10-30s LLM calls. |
| D009 | Posts feed mental model | Considered living docs | Timestamped posts, analyst-on-Twitter | Supersedes chain shows how thinking changed. |
| D010 | Questions persisted in DB | Initial: in-memory | questions table in posts.db | Container restarts lose memory. Questions = analytical agenda. Must survive. |
| D011 | Question priority by LLM | Considered FIFO | Scored by centrality + recency + age | Real analysts don't work FIFO. Most important question worked on next. |
| D012 | Source reliability in prompt | Config had scores, unused | Pass into significance assessment | 0.6 reliability source needs stronger signal than 0.9 source. LLM reasons explicitly. |
| D013 | Conversation via trace_id | Considered DB polling | channel:response:{trace_id}, 30s timeout | Clean request-response without polling. Trace ties query to response. |
| D014 | Working theories seeded | Initial: empty on start | LLM seeds from domain config | Empty theories = no analytical grounding for early posts. |
| D015 | Single source of truth | Earlier: duplicated content | Voice in prompt.md, decisions here, comms in prompt.md | Drift risk when same content in multiple files. |
| D016 | FTS5 from start | Considered LIKE first | FTS5 initialized at M0 | Full table scan vs. one-line schema change. No reason to defer. |
| D017 | **Groq hybrid LLM stack** | Considered Claude API (cost) | Three Groq models, free tier, hybrid routing | Zero cost. Fast model for triage, deep model for quality. DeepSeek-R1's chain-of-thought improves post reasoning. |
| D018 | **Model routing by call type** | Considered single model | fast/standard/deep per call type | Monitor significance: fast (cheap, structured). Post writing: deep (voice-critical). Tether checks: standard. Multiplies effective rate budget. |
| D019 | **Rate limit = wait, not degrade** | Considered switching models on limit | Wait for window reset | System never degrades mid-thought. 60s wait vs. weaker output on voice-critical calls is the right tradeoff. |
| D020 | **Few-shot examples in voice prompt** | Considered description-only | Good + bad examples in every substantive prompt | Open-weight models respond better to examples than described style. Non-negotiable for voice quality. |
| D021 | **DeepSeek-R1 think blocks** | R1 outputs `<think>` blocks | Strip think block, use cleaned output | Think block improves reasoning quality but should not appear in posts or conversation responses. |
| D022 | **Railway → Fly.io** | Considered Cloudflare Workers | Railway (dev), Fly.io (prod) | Workers are serverless — can't run long-lived background loops. Railway/Fly support persistent Docker containers. |
| D023 | **Telegram session on volume** | Default: container root | Mount session at /memory/telegram_session | Session file lost on container restart without volume mount. Re-auth required each time otherwise. |
| D024 | **Validate.py specified in Plan.md** | Earlier: undocumented checks | Full spec in Plan.md, skeleton at M0, checks added per milestone | Codex was guessing at validation logic. Explicit spec prevents wrong implementations. |
| D025 | **SQLite WAL mode** | Default journal mode | `PRAGMA journal_mode=WAL` in init_db.py | Researcher writes while API reads concurrently. WAL prevents `database is locked` errors. One-line fix, no reason not to. |
| D026 | **FTS search from context dict** | `str(context)[:100]` as FTS query | Extract headline/question field from context dict | FTS on a serialized dict returns nothing. Must extract the meaningful text field for the query to work. |
| D027 | **/chat as request body** | Query param `question: str` | `ChatRequest` Pydantic model in POST body | Query params break on long questions and special characters. Standard REST for a chat endpoint. |
| D028 | **WebSocket cleanup on disconnect** | No error handling | try/finally with `pubsub.unsubscribe()` | Browser refresh causes WebSocket disconnect. Without cleanup, pubsub subscriptions leak indefinitely. |
| D029 | **working-theories updated_at** | Not returned by API | Return file mtime as `updated_at` ISO string | Frontend shows "Last updated X ago" — needs timestamp. File mtime is the correct source. |
| D030 | **Question dedup by text** | INSERT OR IGNORE on UUID | Check for exact text match before insert | UUID-keyed dedup does nothing. Same question asked twice generates two rows, both get priority-scored and potentially dived. |
| D031 | **Source Health Monitor (4th agent)** | Manual source management | Autonomous health scoring, human-approved proposals | Sources degrade. New sources emerge. Agent tracks signal/noise ratio per source, proposes from curated seed pool. Human approves — agent never auto-adds. |
| D032 | **Source proposals from curated pool only** | Considered open web discovery | CANDIDATE_POOL in agent code, manually maintained | Open discovery would add low-quality or adversarially-positioned sources. Iran Telegram is full of propaganda accounts. Curated seed pool is the only safe approach. |
| D033 | **Russian milblogs kept at low reliability** | Considered excluding | Included at reliability 0.45, skepticism "high" | Slavyangrad/colonelcassad are often first on proxy-theater developments. The skepticism prefix and low reliability score mean the LLM discounts them appropriately. Excluding them loses genuine signal. |
| D034 | **Docker build context = project root** | `build: ./agents/orchestrator` | `context: .` + `dockerfile: agents/orchestrator/Dockerfile` | Dockerfiles COPY from project root paths. Build context must be project root or COPY paths break. |
| D035 | **feedparser wrapped in asyncio.to_thread** | Direct sync call in async loop | `await asyncio.to_thread(feedparser.parse, url)` | feedparser is synchronous. Calling it directly blocks the event loop during HTTP fetch. to_thread runs it in a thread pool. |

---

## ARCHITECTURE NOTES

### Why Groq hybrid works

The insight is that not all LLM calls need the same quality. The Monitor's significance assessment is asking "is this Iran-related and how significant?" — an 8B model with structured output and temperature 0.1 does this fine and uses almost no rate budget. The Researcher writing a post in a specific voice with extended reasoning is where quality matters — that's where DeepSeek-R1's built-in chain-of-thought earns its place.

Spreading calls across three models means three separate rate limit buckets. The Monitor can burn through fast-model budget at full speed without touching the deep-model budget the Researcher needs for posts.

### Why we wait on rate limits

The alternative — downgrading the model when rate-limited — means a post might get written by llama-3.1-8b when DeepSeek-R1 is rate-limited. The voice quality difference is real and the post would be weaker. Since rate limit windows reset every 60 seconds, waiting is almost always the right call. The dive loop checks before each call and pauses if needed, which means deep dives just take a bit longer rather than producing worse analysis.

### Why DeepSeek-R1's think block matters

R1's chain-of-thought isn't just a gimmick — it genuinely improves reasoning quality on complex multi-step problems. For analytical post writing ("what's actually happening and why"), having the model reason through its thinking before producing output produces better conclusions. We strip the think block from the final response so the user sees clean analysis, but the reasoning improves what the analysis says.

### The cost picture

In practice: Monitor makes ~100-200 fast-model calls/day (significance assessments). Researcher makes ~10-20 deep-model calls/day (posts + dives + conversation). Standard model: ~30-50 calls/day. All within free tier limits with careful rate management. Total monthly LLM cost: $0.

---

## KNOWN ISSUES

| # | Issue | Severity | Found | Status |
|---|---|---|---|---|
| — | — | — | — | — |

---

## FUTURE WORK

*Out of scope. Log here.*

- Failure recovery: retry logic, partial write recovery, agent crash handling
- Multi-domain: same team on different conflict
- Voice interface
- Push notifications on critical signals
- Source reliability learning: track which sources have historically been right
- Farsi/Arabic sources: major current coverage gap
- Post sharing / export

---

*Spec: prompt.md | Plan: Plan.md | Runbook: Implement.md | Memory: this file*
*Decision log is canonical here.*
