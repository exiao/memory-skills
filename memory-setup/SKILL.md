---
name: memory-setup
description: Set up a persistent memory system for any AI coding agent (Cursor, Claude Code, OpenCode, OpenClaw, etc.). This file is the shared spec (entry format, categories, episodes, recall, GC); per-platform install steps live in references/<platform>.md. Use when someone wants their agent to remember things across sessions, set up memory, or configure persistent context.
---

# Memory Setup

Set up persistent memory for an AI coding agent so it remembers context, preferences, decisions, and lessons across sessions. Agent-agnostic — works with any agent that can read/write files.

## Core Principle

AI agents have no memory between sessions unless you write things to disk. Memory = files. This skill defines the file structure, entry format, and maintenance routines; the per-platform guides wire them into a specific agent.

## Choose your platform

Read **only** the guide for your agent — each is self-contained for install steps and refers back to this file for the shared spec.

| Platform | Setup guide |
|----------|-------------|
| **Cursor** | [`references/cursor.md`](references/cursor.md) — alwaysApply rule + optional `sessionEnd` hook |
| **Claude Code** | [`references/claude-code.md`](references/claude-code.md) — `CLAUDE.md` + native `SessionEnd` hook |
| **OpenCode / Hermes / OpenClaw / any file-based agent** | [`references/generic.md`](references/generic.md) — `~/.hermes` workspace + operating-instructions rule |

---

## Architecture Overview

```
                    SESSION START
                    ─────────────
                    Load MEMORY.md + USER.md → system prompt
                    Load SOUL.md / AGENTS.md / CLAUDE.md → operating instructions
                            │
                            ▼
                    DURING SESSION
                    ──────────────
                    Agent appends durable facts to MEMORY.md the moment they appear
                            │
                            ▼
                    SESSION END (optional backstop)
                    ───────────
                    Extract any missed facts from transcript → MEMORY.md
                    Write episode summary → episodes/YYYY-MM-DD.md
                            │
                            ▼
                    DAILY MAINTENANCE (memory-gc)
                    ────────────────────────────
                    Decay stale entries │ Drain pending overflow │ Prune old files
```

---

## Shared spec

### Memory files

**MEMORY.md** — long-term curated memory, loaded every session:

```markdown
# MEMORY.md

> Durable facts and context. Loaded every session.
> Entry format: [YYYY-MM-DD][category] content
> Categories: fact, pref, env, proj:<path>, rel:<name>, task, tmp, rule, meta

§
```

**USER.md** — stable user profile, loaded alongside MEMORY.md:

```markdown
# USER.md

- **Name:** (your name)
- **Timezone:** (e.g. America/New_York)
- **Communication style:** (how you like to be talked to)
- **Key preferences:** (tools, languages, frameworks you prefer)
```

**SOUL.md** (optional) — agent persona/tone/boundaries. Loaded automatically by some agents, otherwise referenced from AGENTS.md / CLAUDE.md.

### Entry format & categories

`[YYYY-MM-DD][cat] content`, one entry per `§`-separated block.

| Category | Purpose | Decay |
|----------|---------|-------|
| `fact` | Durable facts | 60 days |
| `pref` | User preferences | 60 days |
| `env` | Environment/infra | 30 days |
| `proj:<path>` | Project-specific context | 30 days |
| `rel:<name>` | Info about a person | Never |
| `task` | Active tasks/goals | 14 days |
| `tmp` | Ephemeral notes | 7 days |
| `rule` | Hard behavioral constraints | Never |
| `meta` | System configuration | Never |

Rules: date = creation date only (never updated); `[rule]` entries are hard constraints; **capture incrementally** (write the moment a fact appears, not at session end); never fabricate dates; keep under ~100 entries (use `memory-gc` to prune).

### Episodes

Daily session summaries — the middle recall tier. One file per day, sessions appended:

```markdown
## Episode — 2:30 PM

**Summary:** Set up CI pipeline. Chose GitHub Actions over CircleCI. Fixed a flaky auth test.

tags: devops, ci, testing, auth

---
```

### Multi-tier recall

Search in order, stop when confident:

| Tier | Source | Method |
|------|--------|--------|
| 1. Hot | MEMORY.md + USER.md | Already in context |
| 2. Topic files | `memories/*.md` (via `memories/INDEX.md`) | Read matching files |
| 3. Episodes | `episodes/*.md` | Grep by tag/date |
| 4. Sessions | Raw transcripts | Full-text search (ripgrep/FTS5) |

Use both semantic (vector) and exact (grep) search — one alone misses things.

### Daily garbage collection

Run `memory-gc` daily (cron/launchd) to keep files clean:

1. **Decay** stale entries by category TTL (tmp=7d, task=14d, env/proj=30d, fact/pref=60d, rule/meta/rel=never).
2. **Drain** `episodes/.pending.md` overflow into MEMORY.md.
3. **Promote** 0-3 durable facts from the last 7 days of episodes.
4. **Prune** old episode summaries (>90d) and session logs (>180d). Never delete MEMORY.md/USER.md by mtime.

### Overflow

When MEMORY.md exceeds ~100 entries, append new entries to `episodes/.pending.md`; GC drains them after decaying old ones.

### Optional: vector search

For large stores, index `memories/` and `sessions/` with embeddings (OpenAI, Gemini, Voyage, or local Ollama). Config depends on the agent.

### File layout

```
$WORKSPACE/
├── memories/
│   ├── MEMORY.md      ← hot memory (loaded every session)
│   └── USER.md        ← user profile
├── episodes/
│   ├── YYYY-MM-DD.md  ← daily summaries
│   ├── .pending.md    ← overflow queue
│   └── .gc.log        ← GC audit log
├── sessions/          ← raw transcripts (optional)
└── SOUL.md            ← agent persona (optional)
```

---

## Verification

1. Tell your agent: "Remember that my favorite color is blue."
2. Start a new session.
3. Ask: "What's my favorite color?" — it should find it in MEMORY.md.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Agent doesn't remember anything | Confirm MEMORY.md is loaded at session start (rule / CLAUDE.md / system prompt) |
| Memory grows unbounded | Set up the `memory-gc` cron job; check decay rules |
| Session-end extraction misses things | Prefer incremental capture; if extracting, raise turn count (40-50) |
| Auto-extraction writes nothing | The extractor CLI isn't installed or authenticated (e.g. `cursor-agent login`) |
| Recall returns nothing | Use both grep (exact) AND semantic search (fuzzy) |
| `.pending.md` keeps growing | GC isn't running or MEMORY.md is at capacity — decay more aggressively |
