# Medium pending survivor relocation

Use this when `.pending.md` is already pruned but still leaves a medium survivor set, roughly 100-150 entries. The goal is to preserve class-level learning without draining hot memory.

## Pattern

1. Archive every survivor body first, deduplicated into `~/.hermes/episodes/.gc.log`.
2. Read survivors by topic and discard one-off task state, PR numbers, statuses, and personal/closed-loop facts.
3. Relocate durable facts into existing topic files as compact `GC Consolidated Notes` bullets.
4. Create a new topic file only when no umbrella exists and the topic is likely to recur.
5. Rebuild `INDEX.md`, then fill in compact descriptions for any new files left as `(no description)`.
6. Add only tiny hot pointers for newly created files if MEMORY.md has budget. Do not pointer every file touched.
7. Clear `.pending.md`, then run the final tail recheck before appending the GC summary.

## Handling odd survivor lines

The prune script can leave lines without a `TARGET\t` prefix. Treat the whole line as the body for archive and triage. If it is personal state, a completed search, a specific PR status, or an operational snapshot likely to be stale in a week, archive and discard rather than draining.

## Good relocation targets

- A project's architecture, eval, routing, and pipeline facts → that project's topic file (e.g. `<project-a>.md`).
- A second product's facts → its own topic file (`<project-b>.md`), or a narrower topic file if one already exists.
- A standalone service's facts → `<service>.md`.
- Runtime, provider, memory, backup, and subagent facts → `assistant-runtime-notes.md` or `INFRASTRUCTURE.md`.
- Repeated tool evaluations → one existing eval topic file rather than a new one per tool.

## What not to preserve as hot memory

- Specific PR numbers, mergeability, branch state, cron run IDs, one-off Render build status, exact ad metrics snapshots, and completed apartment/search state.
- Project facts that are now represented in topic files.
- Topic-file pointers for old or already-indexed files unless the file was created this run and needs a short-term hot route.
