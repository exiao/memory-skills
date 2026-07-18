# Cursor Setup

Platform-specific install for the memory system in Cursor. For the entry format, categories, episode format, recall, and GC, see the shared spec in [`../SKILL.md`](../SKILL.md).

Cursor has no `~/.hermes`-style plugin that can run an extractor model for you, so the mapping differs from Claude Code. In Cursor, an **always-applied rule is the primary engine** (it loads and captures memory in-context, reliably and at zero extra token cost), and **hooks** are an optional automation layer.

**Cursor itself is the LLM, so no third-party CLI is required.** The reliability trick is to have the rule capture memory **incrementally** — writing each durable fact the moment it appears, in the same turn — rather than at session end. Sessions often end with no final agent turn, so any "save it at the end" strategy silently loses data. The optional `cursor-agent` hook below is only a backstop for catching the final turns automatically; if you have no CLI, incremental rule capture alone is a complete setup.

## Choose your scope first

Everything below depends on whether memory is **project-local** or **global**, and the paths differ. Pick one and use its column throughout.

| | Project-local | Global |
|---|---------------|--------|
| Memory store | `<repo>/.cursor/memory/` | `~/.cursor/memory/` |
| Rule | `<repo>/.cursor/rules/memory.mdc` | **User Rules** (Settings → Rules), not a file — see note below |
| Hook config | `<repo>/.cursor/hooks.json` | `~/.cursor/hooks.json` |
| Hook command | `.cursor/hooks/memory-extract.sh` (cwd = repo root) | absolute path, e.g. `$HOME/.cursor/hooks/memory-extract.sh` (cwd = `~/.cursor`, so a relative path resolves wrong) |
| Rule paths inside the rule | relative (`.cursor/memory/...`) | **absolute** (`~/.cursor/memory/...`) — relative paths resolve against the active project, not home |

Project and global hooks **merge**, so a project `.cursor/hooks.json` coexists with `~/.cursor/hooks.json`.

> **Global rule caveat.** Cursor does not reliably load `.mdc` files from `~/.cursor/rules/` as global rules — filesystem `.mdc` rules are project rules under a workspace `.cursor/rules/`. For cross-project memory, paste the rule body into **Settings → Rules → User Rules** instead, or keep a per-repo rule in each project. Don't assume a `~/.cursor/rules/memory.mdc` file is active globally.

## Step 1: Bootstrap the store

Create the directories and seed files before anything reads them (project-local shown; for global, swap `.cursor` for `~/.cursor`):

```bash
MEM=".cursor/memory"           # or "$HOME/.cursor/memory" for global
mkdir -p "$MEM/episodes"
[ -f "$MEM/MEMORY.md" ] || printf '# MEMORY.md\n\n> Durable facts. Loaded every session. Format: [YYYY-MM-DD][cat] content\n\n' > "$MEM/MEMORY.md"
[ -f "$MEM/USER.md" ] || printf '# USER.md\n\n- **Name:**\n- **Timezone:**\n- **Communication style:**\n- **Key preferences:**\n' > "$MEM/USER.md"
```

**Project-local: keep memory out of git.** `MEMORY.md`/`USER.md` hold personal preferences, relationships, and environment facts. A broad `git add .cursor` would publish them. Add an ignore:

```bash
echo ".cursor/memory/" >> .gitignore
```

## How the concepts map

| Generic concept | Cursor primitive |
|-----------------|------------------|
| Load memory at session start | `alwaysApply` rule (project) or User Rules (global) — instructs the agent to read the store first |
| Operating instructions (AGENTS.md / CLAUDE.md) | The same rule, or your `AGENTS.md` (Cursor reads it) |
| Session-end extraction hook | `sessionEnd` hook in `hooks.json` → script that spawns `cursor-agent` (optional) |
| Daily GC | The `memory-gc` workflow (see [`../../memory-gc/SKILL.md`](../../memory-gc/SKILL.md)), run via `cron` / `launchd` |

## Directory layout

```
.cursor/
├── rules/
│   └── memory.mdc          ← alwaysApply rule: load + capture + recall (project scope)
├── hooks.json              ← optional: sessionEnd → extraction hook
├── hooks/
│   └── memory-extract.sh   ← optional: spawns cursor-agent to extract at session end
└── memory/
    ├── MEMORY.md           ← hot memory
    ├── USER.md             ← user profile
    └── episodes/
        ├── YYYY-MM-DD.md   ← daily summaries
        └── .pending.md     ← overflow queue
```

## The rule (primary mechanism)

`.cursor/rules/memory.mdc` — `alwaysApply: true` so it loads every session. (For global scope, paste the body below into Settings → User Rules and make every path absolute.)

```markdown
---
description: Persistent cross-session memory. Load at session start, capture durable facts, recall on demand.
alwaysApply: true
---

# Memory

This workspace has a persistent memory store at `.cursor/memory/`.

## At session start
Read `.cursor/memory/MEMORY.md` and `.cursor/memory/USER.md` before substantive work.

## Capturing memory (save incrementally — do not wait for session end)
Append the moment a durable fact appears. As soon as the user states a durable fact,
preference, decision, correction, or constraint, append it to `.cursor/memory/MEMORY.md`
in the same turn — do not defer to the end of the session (sessions often end with no
final turn, so deferred saves are lost). Format: `[YYYY-MM-DD][cat] content`, preceded by
a `§` line. Categories: fact, pref, env, proj:<path>, rel:<name>, task, tmp, rule, meta
(`[rule]` = hard constraint). Skip small talk and noise. Never fabricate a creation date.
If MEMORY.md exceeds ~100 entries, append to `.cursor/memory/episodes/.pending.md` instead.

## Recalling the past
Search in order, stop when confident: hot (MEMORY.md/USER.md) → episodes/*.md (grep by tag/date) → raw chat history.
Use both exact (ripgrep) and meaning-based search. If nothing is found, say you have no
record of it — never invent history.
```

The categories are inlined above (not just referenced) because the shared `SKILL.md` is usually not present in the project where this rule runs.

## Optional step: automatic session-end extraction (`cursor-agent`)

This step is **entirely optional** — skip it if you only have the Cursor app, since incremental rule capture already covers you. If `cursor-agent` is installed *and authenticated* (`cursor-agent login`; it has its own auth, separate from `gh`), you can add a `sessionEnd` hook as a backstop that auto-extracts the final turns. Keep it **opt-in** (LLM calls cost tokens) and **recursion-guarded** (the extractor's own session would otherwise re-trigger the hook in an infinite loop). Any headless agent CLI works in place of `cursor-agent` (e.g. `claude -p`, `codex exec`, `gemini -y`).

**Prerequisites for the hook:** `cursor-agent` (authenticated) and `jq` (the hook parses the transcript path with it). Install `jq` via `brew install jq` if missing — without it the hook silently no-ops.

`.cursor/hooks.json` (project scope shown; for global, use `~/.cursor/hooks.json` with an absolute `command`):

```json
{
  "version": 1,
  "hooks": {
    "sessionEnd": [
      { "command": ".cursor/hooks/memory-extract.sh" }
    ]
  }
}
```

`.cursor/hooks/memory-extract.sh` (make it executable):

```bash
#!/usr/bin/env bash
set -uo pipefail
# Recursion guard: the extractor runs cursor-agent, whose sessionEnd re-fires this hook.
[ "${CURSOR_MEMORY_EXTRACTING:-}" = "1" ] && exit 0
# Opt-in: rule-based capture is the default; enable via CURSOR_MEMORY_AUTO_EXTRACT=1
[ "${CURSOR_MEMORY_AUTO_EXTRACT:-}" = "1" ] || exit 0
command -v jq >/dev/null 2>&1 || exit 0   # hook needs jq; no-op if absent

input="$(cat 2>/dev/null || true)"
# Resolve the store relative to this script's parent dir so the same script works
# for both project (<repo>/.cursor/hooks/...) and global (~/.cursor/hooks/...) installs.
MEM="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/memory"
T="$(printf '%s' "$input" | jq -r '.transcript_path // .transcript // empty' 2>/dev/null || true)"
[ -n "$T" ] && [ -f "$T" ] || exit 0

DATE="$(date +%Y-%m-%d)"
PROMPT="Read the transcript at $T and $MEM/MEMORY.md (to avoid dupes). Append durable
memories to $MEM/MEMORY.md as [$DATE][cat] content lines (each preceded by §). If
MEMORY.md already has ~100+ entries, append to $MEM/episodes/.pending.md instead so GC
drains it safely. Also write a one-paragraph episode to $MEM/episodes/$DATE.md. Skip
noise. Be terse. Do nothing else."

# --trust accepts the workspace-trust prompt for a headless run. Note: this transcript is
# untrusted input — do NOT add -f/--force, which would grant unattended tool/shell approval
# to anything the transcript injects. Plain -p only needs file read/write here.
CURSOR_MEMORY_EXTRACTING=1 nohup cursor-agent -p --trust --output-format text "$PROMPT" >/dev/null 2>&1 &
exit 0
```

**Enabling it where Cursor can see it.** The hook reads `CURSOR_MEMORY_AUTO_EXTRACT` from the Cursor process environment, not your terminal. `export CURSOR_MEMORY_AUTO_EXTRACT=1` in a shell only affects that shell — the desktop app (or an already-running Cursor) never sees it. Either launch Cursor from the same exported shell, or set the variable in the hook command itself (e.g. wrap the command, or hardcode the guard). After editing `hooks.json`, check **Settings → Hooks**; restart Cursor if the hook doesn't load.

## Daily GC

The `.cursor/memory/` store is not on the `~/.hermes` root that the `memory-gc` and `recall` skills assume. Either point those workflows at `.cursor/memory/` (retarget every path), or copy the GC logic to operate on this tree. There is no `memory-gc.py` shipped — see [`../../memory-gc/SKILL.md`](../../memory-gc/SKILL.md) for the actual decay / drain / prune workflow and its `scripts/`. Scheduling a nonexistent `memory-gc.py` silently does nothing.

## Notes

- `mdc` rules live only in `.cursor/rules/`; filesystem `.mdc` files are project rules, so for cross-project memory use **Settings → User Rules** (see the global caveat above) or a per-repo rule.
- Cursor's `sessionEnd` payload shape can vary; the hook above probes common transcript fields and no-ops if none is found.
- The rule alone is a complete, reliable setup — the hook is purely a backstop.
