# PROMPT.md — Autonomous Political Intelligence System
## Authoritative Project Specification for Codex

---

## WHAT THIS IS

An autonomous intelligence system that monitors the Iran conflict continuously, builds a compounding understanding over time, and publishes analysis in the voice of a brilliant friend who knows this subject deeply — direct, opinionated, willing to say what's actually happening and why.

It does not wait to be asked. It runs on its own, thinks on its own, publishes when it has something worth saying, and gets sharper over time.

---

## THE CORE EXPERIENCE

**The post feed**
The Researcher publishes timestamped analytical posts whenever it has a genuine take. Not source summaries — its own analysis. Posts are permanent and immutable. New understanding produces a new post that supersedes the old one, with explicit acknowledgment of what changed and why.

**Working theories**
A single living document the Researcher maintains itself. Its priors, hunches, lenses — the distilled intuitions that make analysis sharp. Visible to the user. Updated only when something changes how the Researcher thinks, not just what it knows.

**The observability window**
Full visibility into what the system is doing. Every LLM call — inputs and outputs. Every search, every decision, every write. Collapsible entries. The Researcher publishes a `working` event before every LLM call so the window never looks frozen.

**The conversation**
Talk to it anytime. Direct, opinionated, cites its own prior posts inline.

---

## THE THREE AGENTS

### Orchestrator
Manages resources and interrupt routing. Never does domain reasoning.

**Resource management:**
```
FULL     (default): deep dives allowed, normal poll frequency
LIGHT    (rate limit approaching): reactive only, no deep dives
MINIMAL  (rate limit hit): monitor only, reduced polling
```
Tracks Groq API rate limit status per model (requests/minute, tokens/minute). Transitions modes when approaching limits. Broadcasts mode changes to all agents. Resets to FULL when rate limit window resets (per-minute windows).

**Interrupt routing:**
```
CRITICAL → interrupt Researcher immediately
HIGH     → finish current thought, then handle
MEDIUM   → queue for next available cycle
LOW      → noted in stream only
```

---

### Monitor
Reads stream sources continuously. Tags significance. Writes to stream.md. Signals Orchestrator on medium+ items.

**Sources:** X (Twitter API v2), Telegram (Telethon), RSS/news feeds, think tank publications.

**Epistemic tagging:** Source type and reliability flow through to everything downstream. "Telegram channel, unconfirmed" vs "IAEA official statement." Source reliability score from sources.yaml passed into every significance assessment.

**Stream.md:** Raw, timestamped, ephemeral. Wipe policy: on startup and every 6 hours, delete entries older than 48 hours.

**Never crashes** on rate limits, auth failures, or inaccessible sources.

---

### Researcher
The intelligence. Thinks, publishes posts, maintains working theories, answers questions.

**Primary loop:**
```
1. Load open questions from DB
2. Read recent stream — anything new? New questions?
3. Re-score open questions by priority
4. If FULL mode and questions exist: deep dive on highest-priority question
5. Consider posting from anything significant
6. After substantive work: check if working theories need updating
7. Repeat
```

**Open question prioritization:** LLM-scored by centrality to conflict, recency signal from stream, and age. Re-scored each cycle. Highest score worked on next.

**When to publish:** Genuine take worth publishing = connection sources aren't making, implication others aren't drawing, revision of prior thinking, or meaningful uncertainty. Not source summaries.

**When to update working theories:** After substantive post or dive — did this change HOW I THINK, not just what I know? High threshold. New facts don't update theories. Confirmed patterns, overturned priors, new useful lenses do.

**Working theories initialization:** If working_theories.md is empty on startup, seed with sparse initial priors from domain config. Minimal starting lens. Researcher builds from there.

**Central tether:** Every research thread evaluated at each step — does this sharpen understanding of the conflict? Stop if no. This is an evaluated condition in the loop, not a comment.

---

## THE VOICE

*Canonical. All agents reference this. Do not redefine elsewhere.*

The Researcher writes like a brilliant friend who has been thinking hard about this for a long time.

**What that means:**
- Lead with the assessment. Then reasoning.
- Have a point of view. State it. Don't hide behind "analysts say."
- Plain language. No jargon.
- Confidence matches reality: "This is clear..." / "My best read is..." / "Genuinely uncertain here..."
- No false balance. If evidence points one way, say so.
- Sources cited informally: "per the IAEA February report..." / "Telegram reporting, unconfirmed..."
- When something contradicts current thinking, wrestle with it visibly.
- If updating a prior post: "I said X before. Here's why I'm updating that..."

**What it never writes:**
- "Multiple competing assessments suggest..."
- "It remains to be seen..."
- "Some analysts argue X while others contend Y" without a view on who's right
- Passive voice on its own conclusions

**Few-shot examples for voice prompt** (include these in every substantive LLM call):

*Good example:*
"Iran is not striking directly right now and the reason is straightforward if you look at the economics. Another round of sanctions would be devastating — the rial is already in freefall and the IRGC knows domestic pressure is at a threshold. The proxy route gives them deniability and keeps the pressure on without triggering the response they can't afford. That's not restraint, that's calculation."

*Bad example (never write like this):*
"Multiple analysts have suggested that Iran may be considering various options in response to recent developments. It remains to be seen how the situation will evolve, as different stakeholders have competing interests that could influence outcomes in unpredictable ways."

**This voice applies to:** posts, working theories, conversation responses. There is no formal mode.

---

## LLM ARCHITECTURE — GROQ HYBRID

*Canonical. All agents reference this. Do not redefine elsewhere.*

Three Groq models, each used for the right job. Rate limits are per-model per-minute, so spreading calls across models multiplies effective throughput. All Groq, all free tier.

### Model assignments

**`llama-3.1-8b-instant`** — Fast triage calls
- Significance assessment (Monitor)
- Deduplication checks
- Post-worthy judgment (quick yes/no)
- Rate limit: ~30 req/min, 20k tokens/min free tier
- Use when: need fast structured JSON, low reasoning required

**`llama-3.3-70b-versatile`** — Standard reasoning calls  
- Question prioritization
- Stream assessment
- Tether checks during deep dive
- Working theories update check
- Rate limit: ~30 req/min, 6k tokens/min free tier
- Use when: moderate reasoning, structured output

**`deepseek-r1-distill-llama-70b`** — Deep reasoning calls
- Writing posts (voice-critical)
- Updating working theories
- Answering conversation questions
- Deep dive synthesis
- Rate limit: ~30 req/min, 6k tokens/min free tier
- Use when: quality matters, voice matters, extended reasoning needed
- Note: returns `<think>...</think>` block before answer — strip this from output, but it genuinely improves reasoning quality

### Prompting rules for open-weight models

**Always use chain-of-thought for substantive calls:**
Prefix every deep reasoning prompt with: "Think through this carefully before responding."
With DeepSeek-R1 this is automatic (the think block). With other models, add it explicitly.

**Temperature settings:**
- Fast triage calls: `temperature=0.1` (deterministic JSON)
- Standard reasoning: `temperature=0.3`
- Post writing / voice calls: `temperature=0.7` (more creative, less robotic)

**Few-shot examples in voice prompts:**
Include the good/bad voice examples above in every post-writing and conversation prompt. Open-weight models respond better to "write like this example" than described style alone.

**Explicit negative examples:**
Tell the model exactly what NOT to write alongside what to write. Both the good and bad examples from the voice section above belong in the post-writing prompt.

### Rate limit management

The Orchestrator tracks per-model usage:
- Requests made this minute (per model)
- Tokens used this minute (per model)
- Time until window resets

When a model approaches its limit (>80% of window used):
- For fast-model calls: brief sleep until window resets (usually seconds)
- For deep-model calls: queue the call, notify Orchestrator to consider LIGHT mode

The Researcher checks with Orchestrator before any deep call in a dive loop. If rate-limited, it pauses the dive and resumes when the window resets rather than switching to a weaker model mid-thought.

### LLM abstraction

Defined in `shared/base_agent.py`. All agents call `self.llm()`. No agent makes direct Groq API calls outside this method.

```python
async def llm(self,
    prompt: str,
    model: str = "fast",        # "fast" | "standard" | "deep"
    max_tokens: int = 500,
    temperature: float = None,  # None = use model default
    expect_json: bool = True
) -> dict | str:
    """
    - Resolves model alias to actual Groq model name
    - Applies default temperature per model if not specified
    - Publishes 'working' observatory event before call
    - Publishes 'done' event with token count after
    - Reports token usage to Orchestrator for rate limit tracking
    - Strips <think>...</think> blocks from DeepSeek-R1 output
    - Strips JSON markdown fences if expect_json=True
    - On rate limit: waits for window reset, retries once
    """
```

Model alias resolution:
```python
MODELS = {
    "fast":     "llama-3.1-8b-instant",
    "standard": "llama-3.3-70b-versatile",
    "deep":     "deepseek-r1-distill-llama-70b"
}
DEFAULT_TEMPS = {
    "fast": 0.1,
    "standard": 0.3,
    "deep": 0.7
}
```

---

## MEMORY ARCHITECTURE

```
memory/
├── posts.db              SQLite FTS5 — posts + questions tables
├── working_theories.md   Living priors document
└── stream.md             Ephemeral stream log — last 48hrs only
```

**posts.db schema:**
```sql
CREATE TABLE posts (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT,
    supersedes TEXT
);

CREATE VIRTUAL TABLE posts_fts USING fts5(
    title, content,
    content='posts', content_rowid='rowid'
);

CREATE TRIGGER posts_ai AFTER INSERT ON posts BEGIN
    INSERT INTO posts_fts(rowid, title, content)
    VALUES (new.rowid, new.title, new.content);
END;

CREATE TRIGGER posts_ad AFTER DELETE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, title, content)
    VALUES ('delete', old.rowid, old.title, old.content);
END;

CREATE TABLE questions (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    added_at TEXT NOT NULL,
    priority_score REAL DEFAULT 0.5,
    last_scored TEXT,
    answered_at TEXT
);
```

**Retrieval:**
- Prior thinking → FTS5 search on posts, ORDER BY timestamp DESC
- Current facts → live web search (Tavily free tier)
- Current pulse → recent stream.md entries
- Own priors → working_theories.md in full context

**No vector store. No knowledge graph. No extraction pipeline.**

---

## AGENT COMMUNICATION

Redis pub/sub. Each agent subscribes to `channel:{name}`. All messages go to `channel:orchestrator` first — Orchestrator routes onward. Agents never message each other directly.

Conversation responses: Researcher publishes to `channel:response:{trace_id}`. API subscribes with 30-second timeout.

---

## PLATFORM

```
LLM:         Groq API (free tier) — three models, hybrid routing
Hosting:     Railway free tier (dev) → Fly.io free tier (prod)
DB:          SQLite with FTS5 (local, persisted volume)
Message bus: Redis 7 (Railway/Fly managed or container)
X:           Twitter API v2 free tier (Tweepy)
Telegram:    Telethon (free)
Web search:  Tavily API free tier (1000 searches/month)
Frontend:    React + Tailwind
Container:   Docker Compose → Railway/Fly deploy
```

**Cost: $0/month** with careful rate management.

---

## HARD CONSTRAINTS

- **Voice is the product.** Never softened. Few-shot examples in every substantive prompt.
- **Tether rule in code.** Evaluated condition in dive loop. Not a comment.
- **Posts immutable.** INSERT only. Never UPDATE.
- **Open questions persisted.** questions table in posts.db. Survives restarts.
- **Stream wiped.** Entries >48hrs deleted on startup and every 6hrs.
- **Source reliability used.** In significance assessment prompt.
- **Observatory never silent.** `working` event before every LLM call.
- **Model routing enforced.** Fast calls use fast model. Deep calls use deep model. Never the reverse.
- **Rate limits respected.** Orchestrator tracks per-model usage. System waits for window reset rather than degrading quality mid-thought.
- **Single source of truth.** Voice defined here. Decision log in Documentation.md. Comms defined here. Nothing redefined in other files.

---

## DELIVERABLES

1. Three agent services — containerized, independently restartable
2. posts.db — FTS5, questions table, initialized on startup
3. working_theories.md — seeded on first startup
4. stream.md — Monitor writes, auto-wiped
5. Observability window — full I/O, collapsible, never silent
6. Post feed UI — chronological, tag filter, supersession chain
7. Working theories UI — rendered markdown
8. Conversation interface — cited responses
9. Complete config files — sources.yaml, domain.yaml, resources.yaml
10. `.env.example` — all required variables
11. `scripts/validate.py` — all checks referenced in Plan.md
12. `docker-compose.yml` — full system in one command
13. Railway/Fly deploy config

---

## DONE WHEN

- [ ] All three agents running on Railway/Fly free tier
- [ ] Monitor ingesting from X + RSS continuously
- [ ] Groq hybrid routing working — right model for right call
- [ ] Rate limit management working — system waits, never degrades mid-thought
- [ ] Posts published in correct voice with few-shot examples enforcing it
- [ ] DeepSeek-R1 think blocks stripped from output
- [ ] Open questions persisted — survive restart
- [ ] Questions prioritized by score each cycle
- [ ] working_theories.md seeded and updating
- [ ] Stream wipe running correctly
- [ ] Observatory never silent during LLM calls
- [ ] Conversation returns cited direct response within 30s
- [ ] All validate.py checks pass
- [ ] Zero monthly cost

---

*Authoritative spec. Plan.md, Implement.md, Documentation.md derive from this. In conflict, this governs.*
