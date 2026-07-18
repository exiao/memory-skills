# Claude Code Setup

Platform-specific install for the memory system in Claude Code. For the entry format, categories, episode format, recall, and GC, see the shared spec in [`../SKILL.md`](../SKILL.md).

Claude Code can load memory via `CLAUDE.md` and run **native session-end hooks/plugins**, so it supports automatic extraction out of the box.

## Workspace

Use the canonical `~/.hermes` root — it's the tree that `memory-gc` and `recall` already operate on, so GC, drain, and recall work with zero extra wiring:

```bash
WORKSPACE="$HOME/.hermes"
mkdir -p "$WORKSPACE/memories" "$WORKSPACE/episodes" "$WORKSPACE/sessions"
```

A project `.claude/` store is possible but **not** picked up by `memory-gc`/`recall` unless you retarget every one of their commands at that path (otherwise it goes unpruned and unrecalled). Prefer `~/.hermes` unless you have a specific reason to keep memory per-repo.

Create `MEMORY.md` and `USER.md` under `memories/` per the shared spec.

## Load at session start

Add a memory section to your `CLAUDE.md` so the store loads every session:

```markdown
## Memory
- Read `~/.hermes/memories/MEMORY.md` and `USER.md` at the start of each session.
- **Capture incrementally:** the moment the user states a durable fact, preference, decision,
  or constraint, append it to MEMORY.md as `[YYYY-MM-DD][cat] content` — do not wait for session end.
- Categories: fact, pref, env, proj:<path>, rel:<name>, task, tmp, rule, meta. `[rule]` = hard constraints.
- Never fabricate a creation date or invent history.
```

## Session-end extraction (recommended)

> **Timeout.** Claude Code's `SessionEnd` hooks run on a short default budget (~1.5s), far too little to read a transcript, call a model, and write files. Detach a fast background worker (`... &` and return immediately, like the Cursor hook) or raise the per-hook timeout, otherwise the extractor is killed before it writes anything.

Configure a `SessionEnd` hook (or plugin) that:

1. Pulls the last 30-40 turns from the session transcript.
2. Sends them to a fast model with the extraction prompt below.
3. Writes extracted entries to `MEMORY.md` / `USER.md`.
4. Appends an episode summary to `episodes/YYYY-MM-DD.md`.
5. Writes overflow rows to `episodes/.pending.md` when hot memory is full.

**Extraction prompt template:**

```
Review this conversation. Extract durable memories worth keeping.

Return JSON:
{
  "entries": [
    {"cat": "fact|pref|env|proj:<path-or-namespace>|rel:<name>|task|tmp|rule|meta", "target": "MEMORY|USER", "content": "..."}
  ],
  "episode": { "summary": "One paragraph summary of the session", "tags": ["tag1", "tag2"] }
}

Rules:
- Only extract what's worth remembering across sessions
- Skip small talk, debugging noise, routine commands
- Prefer specific facts over vague summaries
- project context → proj:<path>; another person → rel:<name>; the user → USER
- If nothing worth saving, return empty arrays
```

If you can't run a hook, fall back to a manual end-of-session prompt or the `CLAUDE.md` "Session End" instruction (see [`generic.md`](generic.md)).
