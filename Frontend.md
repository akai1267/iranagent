# FRONTEND.md — Iran War Monitor UI Specification
## Complete Frontend Spec for Codex

*Companion to prompt.md, Plan.md, Implement.md, Documentation.md.*
*Codex must not consider the frontend complete until every section of this document is implemented.*

---

## DESIGN SYSTEM — THE LAW

This design system is non-negotiable. Every color, font, radius, and spacing value comes from it. Tailwind utility defaults that conflict with this system are overridden. Generic component library defaults are overridden. The system below is the single source of truth for all visual decisions.

### Fonts — three only, strict roles

```css
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&family=JetBrains+Mono:wght@300;400;500&display=swap');
```

| Font | Role | Never use for |
|---|---|---|
| **Playfair Display** | Post headlines, section titles, probability numbers, hero text | Tags, labels, body copy, UI chrome |
| **DM Sans** | Body copy, card text, nav labels, descriptions, chat messages | Headlines, timestamps, tags |
| **JetBrains Mono** | ALL timestamps, ALL tags/badges, overlines, observatory log, metadata | Body copy, headlines, long-form text |

Rule: when in doubt, Playfair for big editorial text, DM Sans for readable text, JetBrains Mono for everything that has a "machine" or "label" quality.

### Color tokens — copy this into index.css, override nothing

```css
:root {
  --accent:               #9b1c1c;   /* crimson — urgency, brand, primary CTA */
  --accent-deep:          #6b0f0f;   /* hover/pressed states */
  --accent-light:         #fbe9e9;   /* background behind red text */

  --accent-warm:          #b45309;   /* amber — watch alerts, caution */
  --accent-warm-light:    #fef3c7;
  --accent-blue:          #1c509b;   /* navy — intelligence, data */
  --accent-blue-light:    #eff6ff;
  --accent-green:         #166534;   /* forest — confirmed, pass */
  --accent-green-light:   #dcfce7;
  --accent-purple:        #6b21a8;   /* purple — geopolitics, longform */
  --accent-purple-light:  #f3e8ff;
  --accent-teal:          #0f766e;   /* teal — analysis */
  --accent-brown:         #7c2d12;   /* brown — military/ORBAT */

  --text:      #1a1a1a;
  --text-2:    #3a3a3a;
  --muted:     #666666;
  --faint:     #999999;

  --bg:            #f5f3f0;   /* page background */
  --bg-warm:       #f1ede7;   /* header, sidebars */
  --bg-panel:      #ece8e1;   /* observatory panel — slightly darker than bg */
  --bg-card:       #faf9f7;
  --bg-card-hover: #f3eeea;

  --border:        #e0dbd3;
  --border-light:  #ede9e3;

  --font-display: 'Playfair Display', Georgia, serif;
  --font-body:    'DM Sans', system-ui, sans-serif;
  --font-mono:    'JetBrains Mono', 'Courier New', monospace;

  --radius-sm:   2px;
  --radius-md:   4px;
  --radius-pill: 999px;
}
```

**Color semantics — enforced:**
- Crimson `#9b1c1c` = urgency, primary brand. Never decorative.
- Amber `#b45309` = watch, caution, secondary alert.
- Navy `#1c509b` = intelligence data, information.
- Forest `#166534` = confirmed, verified, pass.
- Purple `#6b21a8` = geopolitics, longform analysis.
- Every color use carries meaning. If you're using a color without a semantic reason, stop.

**What you must never do:**
- Never use pure white `#ffffff` as a background — always the parchment tones
- Never use cool grey backgrounds — always warm-tinted
- Never use `border-radius` greater than `4px` on any card, tag, or panel
- Never use Inter, Roboto, Arial, or system-ui as a primary font
- Never use purple gradients, neon accents, or glassmorphism
- Never use Tailwind's default `rounded-lg`, `rounded-xl`, `rounded-2xl` — override to `rounded-sm` (2px)

---

## LAYOUT — THE TWO-COLUMN SPLIT

```
┌─────────────────────────────────────────────────────────────┐
│  TICKER (only when CRITICAL signal — hidden otherwise)       │
├──────────────────────────────────┬──────────────────────────┤
│                                  │                          │
│  LEFT — The Mind (65%)           │  RIGHT — The Pulse (35%) │
│  bg: --bg (#f5f3f0)              │  bg: --bg-panel (#ece8e1)│
│                                  │                          │
│  ┌─────────────────────────────┐ │  OBSERVATORY             │
│  │ TAB NAV                     │ │  Always visible          │
│  │ FEED · THEORIES · CHAT      │ │  Monospace log           │
│  └─────────────────────────────┘ │  Real-time               │
│                                  │  Collapsible entries     │
│  Active tab content              │                          │
│  scrolls independently           │  scrolls independently   │
│                                  │                          │
└──────────────────────────────────┴──────────────────────────┘
```

**Column behavior:**
- Left column: 65% width, min-width 500px, scrolls independently
- Right column: 35% width, min-width 300px, fixed — never collapses, always visible
- Both columns: `height: 100vh`, `overflow-y: auto`, independent scroll
- Page border-top: `4px solid var(--accent)` — the brand identifier
- No mobile layout needed — this is a desktop tool

**The header:**
```
┌──────────────────────────────────────────────────────────────┐
│  IRAN WAR MONITOR          ● LIVE    Vol. I · 12 Mar 2026    │
│  [Playfair 900, --text]    [live dot] [JetBrains Mono, --faint] │
└──────────────────────────────────────────────────────────────┘
```
- Background: `--bg-warm`
- Border-bottom: `1px solid --border`
- Left: wordmark in Playfair Display 900, tight tracking
- Right: live dot (blinking) + date in JetBrains Mono
- Height: 52px

---

## THE TICKER

Only fires when Orchestrator broadcasts a CRITICAL signal. Hidden by default (`display: none`). When a critical signal arrives via WebSocket, the ticker appears with the signal headline scrolling.

```
┌──────────────────────────────────────────────────────────────┐
│ [BREAKING] IRAN ACTIVATES SECONDARY ENRICHMENT SITES — IAEA  │
└──────────────────────────────────────────────────────────────┘
```

- Background: `--accent` (#9b1c1c)
- Text: white
- Label: `BREAKING` in `--accent-deep` background, separated by border
- Font: JetBrains Mono, 0.62em, uppercase, letter-spacing 0.14em
- Animation: `ticker-scroll 60s linear infinite` (duplicate content for seamless loop)
- Appears with a 200ms slide-down animation
- Dismissible with ✕ button on right

```css
@keyframes ticker-scroll {
  0%   { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}
```

---

## LEFT PANEL — TAB NAVIGATION

Three tabs across the top of the left panel. JetBrains Mono, uppercase, letter-spacing 0.1em. Active tab: `--accent` color + 2px bottom border in `--accent`. Background: `--bg-warm`. Border-bottom: `1px solid --border`.

```
  FEED      THEORIES      CHAT
  ────
```

---

## VIEW 1 — FEED

The post feed. Chronological, newest first. This is the heart of the product.

### Feed header
```
ANALYSIS FEED                           [tag filter: all · nuclear · proxy · diplomatic]
─── 14 posts ────────────────────────────────────────────────────────────────
```
- "ANALYSIS FEED" in JetBrains Mono overline style, `--accent`, uppercase
- Tag filters: small tag pills, clicking filters the list
- Section rule below with post count

### Open questions sidebar (within feed view)
A compact panel at the top of the feed, above posts, collapsible. Shows the Researcher's current open questions list from GET /questions, ranked by priority_score.

```
┌─ OPEN QUESTIONS ──────────────────────────── [collapse ▲] ─┐
│  ● What is driving the current IRGC posture shift?   0.91  │
│  ● Has the Omani back-channel resumed?               0.74  │
│  ● What does China's positioning signal?             0.61  │
└────────────────────────────────────────────────────────────┘
```
- Background: `--bg-card`, border: `1px solid --border`, border-left: `3px solid --accent-warm`
- Bullet: small circle in `--accent-warm`
- Priority score: right-aligned, JetBrains Mono, `--faint`
- Updates in real time via polling or WebSocket

### Post card

Each post renders as a card with generous vertical spacing. Not a compact list — this is reading material.

```
┌────────────────────────────────────────────────────────────┐
│ [ANALYSIS]  [NUCLEAR]                     12 Mar 2026 14:48 │  ← tags + timestamp, JetBrains Mono
│                                                            │
│  Iran is not restraining itself. It's waiting.            │  ← Playfair Display 700, ~1.3em
│                                                            │
│  The enrichment acceleration isn't a negotiating chip —   │  ← DM Sans 400, 0.88em, --text-2
│  it's a hedge against a deal that never comes. Per the    │    leading 1.65
│  IAEA February report, 60% enrichment has resumed at      │
│  Fordow. That's not leverage. That's positioning.         │
│                                                            │
│  [Read more ▾]    ● supersedes post from 08 Mar 2026      │  ← expand + supersedes link
└────────────────────────────────────────────────────────────┘
```

**Post card anatomy:**
- Background: `--bg-card`
- Border: `1px solid --border`
- Border-top: `3px solid` — color determined by primary tag (red=urgent, amber=watch, blue=intel, purple=geo, green=confirmed)
- Border-radius: `2px`
- Padding: 20px 24px
- Margin-bottom: 12px

**Title:** Playfair Display 700, 1.25em, `--text`, letter-spacing -0.01em, line-height 1.2

**Body preview:** First 3-4 sentences visible. DM Sans 400, 0.88em, `--text-2`, line-height 1.65. Fades out at bottom with a gradient mask when collapsed.

**Expanded state:** Click "Read more" → full post expands inline with smooth height animation. No navigation away from the feed.

**Superseded state:**
- If this post has been superseded by a newer one: title gets `opacity: 0.6`, a strikethrough tag appears: `[UPDATED]` in amber, with a link "→ see updated analysis"
- If this post supersedes an older one: a small note below the title: "Updates analysis from [date]" in JetBrains Mono, `--faint`

**Metadata row (top of card):**
- Tags on left: each tag styled per design system (`.tag` class, color-coded)
- Timestamp on right: JetBrains Mono, 0.6em, `--faint`

### Empty state
When no posts yet: a single centered message in DM Sans italic, `--muted`, with a small live-dot blinking beside it: "● Researcher is working..."

---

## VIEW 2 — THEORIES

The working_theories.md document. Read-only. Rendered markdown.

```
┌────────────────────────────────────────────────────────────┐
│  WORKING THEORIES                   Last updated 2h ago    │
│  ─────────────────────────────────────────────────────     │
│                                                            │
│  Regime survival is Iran's north star. Everything else     │
│  is downstream of that. When something seems irrational    │
│  from outside, ask what it looks like through that lens    │
│  first.                                                    │
│                                                            │
│  The IRGC and the foreign ministry want different          │
│  things...                                                 │
└────────────────────────────────────────────────────────────┘
```

**Styling:**
- Background: `--bg-card`, padding: 32px, max-width: 680px, margin: 0 auto
- Header: "WORKING THEORIES" in JetBrains Mono overline, `--accent`, uppercase, tracking 0.18em
- Last updated: right-aligned, JetBrains Mono, `--faint`, 0.6em
- Body: DM Sans 400, 0.94em, `--text-2`, line-height 1.75 — generous, this is reading material
- Paragraph breaks: 1.2em margin between paragraphs
- Any italics in the markdown: Playfair Display 400 italic (swap font on `em` tags)
- Border-left: `3px solid --accent` on the outer container, like a pullquote
- No code blocks, no tables — this is prose only

**Lede quote treatment:**
The first paragraph gets special treatment — larger text, Playfair italic, the `.lede-quote` treatment:
- Font: Georgia (or Playfair), italic, 1.1em, line-height 1.75
- Border-left: `3px solid --accent`, padding-left: 18px

**Update animation:**
When the content changes (on fetch refresh), new text highlights briefly with a `--accent-light` background that fades out over 1.5s. Signals the document was just updated.

---

## VIEW 3 — CHAT

Clean conversation. No chat bubbles. No avatars. Feels like a document, not iMessage.

### Layout
```
┌────────────────────────────────────────────────────────────┐
│  [conversation history scrolls here]                       │
│                                                            │
│  ─── 12 Mar 2026, 14:48 ────────────────────────────────  │
│                                                            │
│  You: What's your read on the proxy escalation?           │
│                                                            │
│  Iran is using the Houthis and PMF as a release valve...  │
│  As I wrote on 10 Mar ("The Houthi pause explained"),     │
│  this is coercive deterrence not war appetite...          │
│                                                            │
├────────────────────────────────────────────────────────────┤
│  [urgent □]  Ask anything...              [Send ↵]        │
└────────────────────────────────────────────────────────────┘
```

**Message styling:**

User messages:
- JetBrains Mono, 0.75em, `--faint`, preceded by "You:" label
- No background, no bubble
- Indent: 0

System responses:
- DM Sans 400, 0.92em, `--text-2`, line-height 1.7
- No background, no bubble
- Post citations render as inline links in `--accent`, underlined: "As I wrote on [10 Mar](/posts/id)..."
- Clicking a citation opens that post in the Feed tab

**Timestamps:**
- Section rules between conversation sessions (new session = page reload)
- JetBrains Mono, `--faint`, the `.section-rule` treatment with horizontal lines

**Input row:**
- Background: `--bg-warm`, border-top: `1px solid --border`, padding: 12px 16px
- Textarea: DM Sans 400, 0.88em, `--text`, no border, no background, resize: none, auto-grows
- Placeholder: "Ask anything..." in `--faint`
- Urgent checkbox: small, labeled "urgent" in JetBrains Mono 0.6em `--muted` — when checked, sends with urgent=true flag (bypasses queue)
- Send button: minimal — "↵" or "SEND" in JetBrains Mono, `--accent` on hover

**Streaming response:**
When response is coming in, a blinking cursor `▌` appears at the end of the current text. The response streams word by word, not character by character (chunk on word boundaries).

**Thinking state:**
Before any text appears, show: `● thinking...` in JetBrains Mono, `--faint`, with the live-dot animation. Replaced by actual response when first tokens arrive.

**Empty state:**
Single centered block:
```
Ask me anything about the conflict.
I'll answer from what I've written and what I know.
```
DM Sans italic, `--muted`, centered.

---

## RIGHT PANEL — OBSERVATORY

Always visible. Always updating. The pulse of the system.

### Panel header
```
┌─ OBSERVATORY ──────────────── ● LIVE ─┐
```
- Background: `--bg-warm`, border-bottom: `1px solid --border`
- "OBSERVATORY" in JetBrains Mono, 0.65em, uppercase, `--text`, tracking 0.14em
- Live dot: blinking, `--accent`

### Agent color coding
| Agent | Color | Token |
|---|---|---|
| orchestrator | Amber `#b45309` | `--accent-warm` |
| monitor | Navy `#1c509b` | `--accent-blue` |
| researcher | Forest `#166534` | `--accent-green` |

### Event row — collapsed (default)
```
14:48  ⏳ [researcher]  Writing post: Iran is not restraining...  ▾
14:47  🔍 [researcher]  Search: IRGC posture signals March 2026
14:46  📄 [monitor]     [HIGH] Reuters: Iran activates Fordow
14:45  💭 [orchestrator] Signal HIGH routed — researcher idle
```

**Anatomy:**
- Timestamp: JetBrains Mono, 0.58em, `--faint`, fixed width 36px
- Icon: emoji or simple glyph, 12px, fixed width 20px
- Agent tag: JetBrains Mono, 0.6em, colored per agent table above, `[brackets]`, fixed width
- Summary: DM Sans 400, 0.78em, `--text-2`, truncated to one line
- Expand indicator: `▾` when detail available, right-aligned, `--faint`
- Row padding: 6px 12px
- Border-bottom: `1px solid --border-light`
- Hover: background `--bg-card-hover`

**Event type icons:**
```
working  →  ⏳  (pulses with opacity animation while active)
done     →  ✓   (green, --accent-green)
search   →  ⟳  or magnifier
read     →  ▤  or document glyph
decide   →  ◈  or diamond
write    →  ✎  or pen
interrupt → ⚡
```

**Working event special treatment:**
When event_type is `working`, the entire row has a subtle left-border in the agent's color, and the summary text pulses with `opacity: 0.5 → 1.0 → 0.5` at 1.5s intervals. This tells you the system is alive and thinking. The pulse stops and the icon changes to ✓ when the corresponding `done` event arrives.

### Event row — expanded (on click)
```
14:48  ⏳ [researcher]  Writing post: Iran is not restraining...  ▴
┌──────────────────────────────────────────────────────────┐
│  model=deep  max_tokens=1000  temperature=0.7            │  ← metadata, JetBrains Mono 9px --faint
│                                                          │
│  [FULL PROMPT TEXT]                                      │  ← DM Sans 0.75em --muted, scrollable
│  ...                                                     │    max-height: 200px, overflow-y: auto
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │  ← dashed separator
│  [RESPONSE TEXT]                                         │  ← DM Sans 0.75em --text-2
└──────────────────────────────────────────────────────────┘
```
- Expanded area: background `--bg-card`, border: `1px solid --border`, border-radius: `2px`
- Metadata row: JetBrains Mono, 9px, `--faint`, flex row
- Prompt/response: scrollable, max-height 200px per section
- Smooth height animation on expand/collapse (CSS transition on max-height)

### Observatory scroll behavior
- Auto-scrolls to newest entry
- Pauses auto-scroll on hover (user is reading)
- Resumes auto-scroll when mouse leaves
- Maximum 500 events in DOM — remove oldest when exceeded

### Observatory empty state
Single centered line: `● Waiting for agents...` JetBrains Mono, `--faint`, live-dot animation.

---

## REAL-TIME BEHAVIOR

All real-time updates via WebSocket at `ws://localhost:8000/ws/observatory`.

**Observatory:** Each event appended to top of list (newest first). Working events pulse until done event arrives with matching trace. Done event updates the working event row in-place (replace ⏳ with ✓, stop pulse animation).

**Feed:** Polls GET /posts every 30 seconds. New posts slide in at top with a 300ms fade-in. No full re-render — append new posts to top of list.

**Working theories:** Polls GET /working-theories every 60 seconds. On change, new content highlights briefly with `--accent-light` background fading out over 1.5s.

**Open questions:** Polls GET /questions every 30 seconds. Updates in place.

**Ticker:** Triggered by observatory WebSocket events with `event_type: interrupt` and significance `critical`. Appears with 200ms slide-down, scrolls until dismissed.

---

## COMPONENT REFERENCE

Implement these exactly as specified in the design system. Do not use component library defaults.

### Tag `.tag`
```css
.tag {
  font-family: var(--font-mono);
  font-size: 0.58em;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  padding: 2px 6px;
  border-radius: 2px;
  border: 1px solid currentColor;
  line-height: 1.4;
  white-space: nowrap;
}
.tag-urgent  { color: #9b1c1c; background: #fbe9e9; }
.tag-watch   { color: #b45309; background: #fef3c7; }
.tag-intel   { color: #1c509b; background: #eff6ff; }
.tag-pass    { color: #166534; background: #dcfce7; }
.tag-geo     { color: #6b21a8; background: #f3e8ff; }
.tag-neutral { color: #999;    border-color: #e0dbd3; background: #f1ede7; }
```

### Live dot `.live-dot`
```css
.live-dot {
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #9b1c1c;
  animation: blink 2s ease-in-out infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.15; }
}
```

### Section rule `.section-rule`
```css
.section-rule {
  display: flex; align-items: center; gap: 10px;
  font-family: var(--font-mono);
  font-size: 0.58em; text-transform: uppercase;
  letter-spacing: 0.14em; color: #999;
}
.section-rule::before, .section-rule::after {
  content: ''; flex: 1; height: 1px; background: #ede9e3;
}
```

### Overline `.overline`
```css
.overline {
  font-family: var(--font-mono);
  font-size: 0.62em;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--accent);
}
```

### Card `.card`
```css
.card {
  background: #faf9f7;
  border: 1px solid #e0dbd3;
  border-radius: 2px;
  padding: 16px;
  transition: background 120ms ease;
}
.card:hover { background: #f3eeea; }
.card-accent-top-red    { border-top: 3px solid #9b1c1c; }
.card-accent-top-amber  { border-top: 3px solid #b45309; }
.card-accent-top-blue   { border-top: 3px solid #1c509b; }
.card-accent-top-green  { border-top: 3px solid #166534; }
.card-accent-top-purple { border-top: 3px solid #6b21a8; }
.card-accent-left       { border-left: 3px solid #9b1c1c; }
```

### Probability bar
```css
.prob-bar  { height: 3px; background: #e0dbd3; border-radius: 1px; overflow: hidden; }
.prob-fill { height: 100%; border-radius: 1px; transition: width 0.8s ease; }
/* Numbers paired with bars: Playfair Display 900, colored to match bar */
```

---

## TAG → BORDER COLOR MAPPING

When the Researcher publishes a post with tags, the card's top accent border color is determined by the primary (first) tag:

| Tag | Border color | Token |
|---|---|---|
| `nuclear`, `urgent` | Crimson | `--accent` |
| `watch`, `military`, `escalation` | Amber | `--accent-warm` |
| `intelligence`, `data` | Navy | `--accent-blue` |
| `confirmed`, `verified` | Forest | `--accent-green` |
| `geopolitics`, `diplomacy` | Purple | `--accent-purple` |
| `analysis` | Teal | `--accent-teal` |
| `orbat`, `weapons` | Brown | `--accent-brown` |
| anything else | Neutral border | `--border` with no accent top |

---

## TYPOGRAPHY RULES IN CODE

```css
/* Post titles — Playfair Display 700 */
.post-title {
  font-family: var(--font-display);
  font-size: 1.25em;
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.2;
  color: var(--text);
}

/* Post body — DM Sans 400 */
.post-body {
  font-family: var(--font-body);
  font-size: 0.88em;
  font-weight: 400;
  line-height: 1.65;
  color: var(--text-2);
}

/* All timestamps — JetBrains Mono */
.timestamp {
  font-family: var(--font-mono);
  font-size: 0.6em;
  color: var(--faint);
  letter-spacing: 0.05em;
}

/* Section overlines — JetBrains Mono, accent */
.overline {
  font-family: var(--font-mono);
  font-size: 0.62em;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  color: var(--accent);
}

/* Probability numbers — Playfair Display 900 */
.prob-number {
  font-family: var(--font-display);
  font-size: 1.3em;
  font-weight: 900;
  line-height: 1;
}
```

---

## ANIMATIONS

```css
/* Blink — live dots, NOW timeline item */
@keyframes blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.15; }
}

/* Pulse ring — critical alert indicator */
@keyframes pulse-ring {
  0%   { box-shadow: 0 0 0 0 rgba(155,28,28,0.4); }
  70%  { box-shadow: 0 0 0 6px rgba(155,28,28,0); }
  100% { box-shadow: 0 0 0 0 rgba(155,28,28,0); }
}

/* Ticker scroll */
@keyframes ticker-scroll {
  0%   { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}

/* Working event text pulse */
@keyframes working-pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
}
.working-row .summary { animation: working-pulse 1.5s ease-in-out infinite; }

/* New post slide-in */
@keyframes slide-in-top {
  from { opacity: 0; transform: translateY(-8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.post-card.new { animation: slide-in-top 300ms ease forwards; }

/* Theories update highlight */
@keyframes highlight-fade {
  0%   { background: var(--accent-light); }
  100% { background: transparent; }
}
.theories-updated { animation: highlight-fade 1.5s ease forwards; }
```

---

## SCROLLBAR

```css
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 10px; }
::-webkit-scrollbar-thumb:hover { background: var(--muted); }
```

---

## DONE WHEN — VISUAL CHECKLIST

Codex must verify every item before considering the frontend complete.

**Fonts:**
- [ ] Playfair Display loading and used for all post titles
- [ ] JetBrains Mono used for ALL timestamps, ALL tags, ALL overlines, observatory log
- [ ] DM Sans used for body copy, card text, chat messages
- [ ] No Inter, Roboto, Arial, or system font visible anywhere

**Colors:**
- [ ] No pure white background anywhere — all parchment tones
- [ ] No cool grey backgrounds
- [ ] Observatory panel visibly darker than left panel (`--bg-panel` vs `--bg`)
- [ ] Post card top border color matches primary tag
- [ ] Agent colors in observatory: orchestrator=amber, monitor=navy, researcher=forest

**Layout:**
- [ ] Two-column layout: 65/35 split
- [ ] Both columns scroll independently, full viewport height
- [ ] Header has brand border-top in crimson, 4px
- [ ] Observatory always visible — never hidden or collapsed

**Components:**
- [ ] All border-radius ≤ 4px — no rounded-lg, rounded-xl anywhere
- [ ] Tags styled exactly per spec — monospace, uppercase, border, color-coded
- [ ] Live dot blinking on header
- [ ] Working events pulse in observatory
- [ ] Done events stop pulse, show ✓

**Behavior:**
- [ ] Observatory auto-scrolls to newest, pauses on hover
- [ ] Expand/collapse works on every observatory event with detail
- [ ] Post expand/collapse works inline (no navigation)
- [ ] Ticker hidden by default, fires on CRITICAL signal
- [ ] New posts animate in from top
- [ ] Working theories highlight on update
- [ ] Chat shows "● thinking..." before response arrives
- [ ] Urgent toggle on chat input
- [ ] Post citations in chat are clickable links to Feed tab

---

## REACT COMPONENT ARCHITECTURE

See Plan.md M6 for the full component tree. Summary of key state management decisions:

**WebSocket state (useObservatory):**
```javascript
// hooks/useObservatory.js
import { useState, useEffect, useRef } from 'react'

export function useObservatory() {
  const [events, setEvents] = useState([])
  const [connected, setConnected] = useState(false)
  const ws = useRef(null)

  useEffect(() => {
    function connect() {
      ws.current = new WebSocket('ws://localhost:8000/ws/observatory')

      ws.current.onopen = () => setConnected(true)
      ws.current.onclose = () => {
        setConnected(false)
        setTimeout(connect, 3000)  // reconnect after 3s
      }
      ws.current.onmessage = (e) => {
        const event = JSON.parse(e.data)
        setEvents(prev => {
          // if this is a 'done' event, find matching 'working' event and update it
          if (event.event_type === 'done') {
            const updated = prev.map(ev =>
              ev.event_type === 'working' && ev.agent === event.agent
              && !ev.resolved
                ? { ...ev, resolved: true, done_summary: event.summary }
                : ev
            )
            return [event, ...updated].slice(0, 500)
          }
          return [event, ...prev].slice(0, 500)
        })
      }
    }
    connect()
    return () => ws.current?.close()
  }, [])

  return { events, connected }
}
```

**Working event resolution:**
Each `working` event has `resolved: false` until the matching `done` event arrives from the same agent. The EventRow component checks `event.resolved` to decide whether to show the pulse animation or the ✓ icon. Match on agent name (not trace_id) since the base_agent publishes working/done without explicit pairing — same agent, working then done, in sequence.

**Polling hooks pattern:**
```javascript
// hooks/usePosts.js
import { useState, useEffect } from 'react'

export function usePosts() {
  const [posts, setPosts] = useState([])
  const [newIds, setNewIds] = useState(new Set())

  useEffect(() => {
    async function fetch() {
      const res = await window.fetch('http://localhost:8000/posts')
      const data = await res.json()
      setPosts(prev => {
        const prevIds = new Set(prev.map(p => p.id))
        const incoming = data.filter(p => !prevIds.has(p.id))
        if (incoming.length) {
          setNewIds(new Set(incoming.map(p => p.id)))
          setTimeout(() => setNewIds(new Set()), 1000)  // clear new flag after animation
        }
        return data  // full replace, already sorted by timestamp DESC from API
      })
    }
    fetch()
    const interval = setInterval(fetch, 30000)
    return () => clearInterval(interval)
  }, [])

  return { posts, newIds }
}
```

**Tab state and citation navigation:**
App.jsx holds `activeTab` state and a `highlightPostId` state. When a post citation in Chat is clicked, App sets `activeTab = 'feed'` and `highlightPostId = postId`. Feed component watches highlightPostId and briefly highlights the matching card with the `--accent-light` background animation.

**tagColors.js:**
```javascript
// lib/tagColors.js
export const TAG_BORDER_COLORS = {
  nuclear:     'var(--accent)',          // crimson
  urgent:      'var(--accent)',
  escalation:  'var(--accent-warm)',     // amber
  watch:       'var(--accent-warm)',
  military:    'var(--accent-warm)',
  intelligence:'var(--accent-blue)',     // navy
  data:        'var(--accent-blue)',
  confirmed:   'var(--accent-green)',    // forest
  verified:    'var(--accent-green)',
  geopolitics: 'var(--accent-purple)',   // purple
  diplomacy:   'var(--accent-purple)',
  analysis:    'var(--accent-teal)',     // teal
  orbat:       'var(--accent-brown)',    // brown
  weapons:     'var(--accent-brown)',
}

export function getCardBorderColor(tags) {
  if (!tags) return null
  const tagList = tags.split(',').map(t => t.trim().toLowerCase())
  for (const tag of tagList) {
    if (TAG_BORDER_COLORS[tag]) return TAG_BORDER_COLORS[tag]
  }
  return null  // no accent border for unrecognized tags
}
```

---

## DOCKERFILES

One Dockerfile per service. All Python services share the same base pattern. Frontend has its own.

### agents/orchestrator/Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/orchestrator/ ./agents/orchestrator/
COPY shared/ ./shared/
COPY config/ ./config/

CMD ["python", "-m", "agents.orchestrator.main"]
```

### agents/monitor/Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/monitor/ ./agents/monitor/
COPY shared/ ./shared/
COPY config/ ./config/

CMD ["python", "-m", "agents.monitor.main"]
```

### agents/researcher/Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/researcher/ ./agents/researcher/
COPY shared/ ./shared/
COPY config/ ./config/
COPY scripts/init_db.py ./scripts/init_db.py

# Init DB on startup if not already initialized
CMD ["sh", "-c", "python scripts/init_db.py && python -m agents.researcher.main"]
```

### api/Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/
COPY scripts/init_db.py ./scripts/init_db.py

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### frontend/Dockerfile
```dockerfile
FROM node:20-alpine AS build

WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
```

### frontend/nginx.conf
```nginx
server {
    listen 3000;

    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;  # SPA routing
    }

    # Proxy API calls to api service
    location /api/ {
        proxy_pass http://api:8000/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    # WebSocket proxy
    location /ws/ {
        proxy_pass http://api:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Each agent needs a main.py entrypoint:
```python
# agents/orchestrator/main.py
import asyncio, os
from agents.orchestrator.agent import OrchestratorAgent

async def main():
    agent = OrchestratorAgent(
        redis_url=os.environ["REDIS_URL"],
        groq_key=os.environ["GROQ_API_KEY"]
    )
    await agent.start()

if __name__ == "__main__":
    asyncio.run(main())

# agents/monitor/main.py — same pattern, passes TWITTER_BEARER_TOKEN, TELEGRAM_* vars
# agents/researcher/main.py — same pattern, passes TAVILY_API_KEY
```

---

## REQUIREMENTS.TXT

Single requirements.txt at project root, shared across all Python services.

```txt
# Groq LLM
groq==0.9.0

# Web framework + WebSocket
fastapi==0.111.0
uvicorn[standard]==0.30.1
websockets==12.0

# Redis
redis[asyncio]==5.0.6

# Data validation
pydantic==2.7.1

# Config
PyYAML==6.0.1

# RSS feeds
feedparser==6.0.11

# X (Twitter)
tweepy==4.14.0

# Telegram
telethon==1.36.0

# Web search + content fetch
httpx==0.27.0
beautifulsoup4==4.12.3
lxml==5.2.2

# Tavily search client
tavily-python==0.3.3

# Utilities
python-dotenv==1.0.1
```

**Version notes:**
- `groq` — install from PyPI: `pip install groq`. The async client (`groq.AsyncGroq`) is included.
- `telethon` — requires a Telegram session file. On first run, will prompt for phone number + code interactively. Run the monitor container with `-it` flag on first boot to complete auth, then the session file persists on the volume.
- `tweepy` — Twitter API v2 free tier gives 500k tweet reads/month. Bearer token only needed (no OAuth for read).
- `tavily-python` — alternatively use `httpx` to call the API directly (shown in Implement.md). Either works.

---

*Frontend spec — companion to prompt.md, Plan.md, Implement.md, Documentation.md.*
*The design system tokens and component CSS in this file are the law. Override nothing from the design system without explicit discussion.*
*Component architecture and Dockerfiles in this file are authoritative for frontend and container setup.*
