# GC overflow relocation pattern

Use this when `.pending.md` remains large after `dedup-pending.py` and `prune_pending.py`, especially 200+ survivors.

## Goal

Preserve durable class-level learning without draining noisy PR/task/status facts into hot `MEMORY.md` or `USER.md`.

## Pattern

1. Archive every surviving pending body to `~/.hermes/episodes/.gc.log` before discarding.
2. Count survivors by target, category, and project namespace before reading the whole file.
3. Group durable information into broad topics, not one pending line per memory entry.
4. Write concise sections into existing topic files when possible:
   - `<project-a>.md` for one project's agent/CLI/eval/coverage/pipeline architecture.
   - `<project-b>.md` for another product's backend/frontend/data-quality/deploy quirks.
   - `assistant-runtime-notes.md` for runtime/provider/skill-bundle/tooling behavior.
   - `INFRASTRUCTURE.md` for local services, cron, launchd, gateway, routing.
5. Create a new topic file only for a genuinely broad durable class, such as investing research notes, not a PR or one-off incident.
6. Clear `.pending.md` after relocation/discard.
7. Rebuild `INDEX.md` and give new files useful one-line descriptions. Avoid leaving `(no description)` for files created this run.
8. Add hot `[meta] Topic file:` pointers only for new or materially touched high-value files, then re-check `MEMORY.md` size and shorten only if it exceeds the computed 70% target (`TARGET=$((LIMIT*70/100))`, where `LIMIT` is the configured or default `memory_char_limit`).

## What not to preserve

- PR numbers, commit SHAs, merge-ready statuses, CI snapshots, Typefully draft IDs.
- Duplicate facts already captured in dedicated topic files.
- Generic coding practices, stale task state, or resolved debugging narratives.
- Exact private IDs or secrets. Generalize or omit sensitive operational identifiers.

## Useful report phrasing

If everything is healthy after the fast path: `pending overflow archived and relocated; MEMORY/USER under target; pending cleared.`
