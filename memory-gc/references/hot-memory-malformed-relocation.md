# Hot-memory malformed entries and pending relocation pattern

Use this when a GC run finds a small number of malformed hot-memory entries plus a pruned `.pending.md` survivor set that is still too large or too project-specific to drain into MEMORY.md.

## Pattern

1. Parse MEMORY.md and USER.md by `\n§\n` blocks. Treat USER.md block 0 as the expected prose profile. Anything below that must be dated.
2. For malformed USER.md entries where a date appears mid-entry, use `memory` target `user`, `action=replace`, and normalize to a single `[YYYY-MM-DD][cat]` entry. Preserve the earliest visible date and meaning.
3. For malformed MEMORY.md entries that are actually project or ref detail, archive the original full body to `episodes/.gc.log`, move the durable detail into the right topic file, then replace the hot entry with a short dated `[meta]` pointer or remove it if INDEX already routes it.
4. If `.pending.md` remains in the 50 to 100 survivor range after `prune_pending.py`, do not drain blindly. Archive every survivor body individually, consolidate by project, append class-level bullets to topic files, then clear pending.
5. After touching a topic file, rebuild INDEX and add a hot `[meta] Topic file:` pointer only for newly created or materially touched files that lack a pointer. Keep pointer descriptions tiny.
6. Re-verify before logging: MEMORY/USER parse cleanly, no malformed `§` lines remain, pending is empty, and MEMORY is under the computed 70% target. Reuse the main GC limit calculation (`LIMIT` from `memory_char_limit`, default `8000`; `TARGET=$((LIMIT*70/100))`) instead of hard-coding an old byte target.

## Why

This preserves useful architectural/runtime knowledge without stuffing hot memory with PR statuses, stale tasks, or narrow error narratives. The archive stays lossless, topic files carry durable detail, and MEMORY remains a route map plus high-value rules/preferences.