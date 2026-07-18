# .pending.md Overflow: Root Cause and Fix

## Problem (May 2026)

`.pending.md` grew to 2165 lines. Same facts repeated 10-50x across sessions.

## Root Causes

### 1. Session-end plugin had no dedup awareness
`~/.hermes/plugins/memory-session-end/extract.md` told the LLM "0-5 entries"
but gave it NO context about what MEMORY.md or .pending.md already contained.
Every session about a given project dutifully extracted project facts already
captured 5 sessions ago.

### 2. GC never drained pending in cron
The skill text said "skip if memory tool unavailable (cron)" but the memory
tool WAS available (toolset enabled, config has memory_enabled:true). The GC
agent was successfully using it for evictions/consolidations in the same run,
then skipping the drain step because the instruction told it to.

### 3. Evictions went back to pending (circular)
Step 8 said "copy evicted entries to .pending.md" creating a feedback loop:
evict → lands in pending → can't drain → accumulates forever.

## Fixes Applied

### Session-end plugin (`~/.hermes/plugins/memory-session-end/`)

1. **extract.md**: Max 0-3 entries (was 0-5), zero is default, added "NEVER
   re-extract anything in ALREADY IN MEMORY/PENDING sections"
2. **__init__.py `_extract()`**: Injects MEMORY.md (3KB) + .pending.md (2KB)
   into transcript so extraction LLM sees existing knowledge
3. **__init__.py `_spill()`**: Checks first 80 chars of content against
   existing .pending.md before appending (dedup safety net)

### GC skill (`~/.hermes/skills/memory/memory-gc/SKILL.md`)

1. Removed all "skip in cron" / "memory unavailable" language
2. Step 3: Capacity-aware confidence gate (over 70% = evict uncertain entries)
3. Step 3: Dedicated memory file redundancy check
4. Step 4: Wired in `~/.hermes/scripts/dedup-pending.py` as first action
5. Step 8: Target lowered from 80%/4800 to 70%/4200
6. Step 8: Evictions logged to .gc.log, NOT copied back to .pending.md

### Dedup script (`~/.hermes/scripts/dedup-pending.py`)

Deterministic pre-processing before LLM judgment:
- Normalizes text (lowercase, strips PR numbers, dates, SHAs, paths)
- Groups by 80-char prefix, keeps most recent date per group
- Removes entries already in MEMORY.md (60-char match)
- Removes stale tasks (>14 days)

## June 2026 evolution: the topic-file blind spot (Root Cause #1, part 2)

The May fix injected MEMORY.md + .pending.md into the extraction prompt, but
NOT the ~28 topic files (`memories/*.md` excluding core), which hold the bulk
of durable project knowledge (a busy project topic file can reach 20-25KB).
So sessions touching those projects kept
re-deriving facts that already lived in a topic file the extractor couldn't see.
That re-extraction flood is what pushes `.pending.md` past 100 and triggers the
GC bulk-discard path (the "359 pending discarded" event).

Fix shipped in `memory-session-end/__init__.py`:
- `_load_topic_context(turns)`: builds a bounded (~8KB) digest of the top-5
  topic files by deterministic token-set (Jaccard) overlap with the transcript
  (file name + headers + 200-char lead), excludes core files
  (memory/user/mem_arch/index/user_details). Injected as a third
  `=== ALREADY IN TOPIC FILES (do NOT re-extract) ===` block in `_extract`.
- `_spill` dedup upgraded from 80-char substring to two-layer:
  substring + `_too_similar` token-set Jaccard (threshold 0.6) so reordered /
  lightly-reworded re-extractions are caught (substring missed them).
- Entry cap hard-enforced in code: `entries[:3]` in `_on_session_end`, so a
  chatty extraction can't flood pending regardless of model drift.
- Tests: `plugins/memory-session-end/test_blindspot.py` (relevance selection,
  core-file exclusion, byte cap, semantic dedup, entry cap), wired into
  `run_tests.sh`.

### Jaccard dedup limit (honest tradeoff)
Token-set Jaccard catches reordering and light rewording (score ~1.0) but a
HEAVY synonym swap ("runs once" → "executes a single time", "before" →
"prior to") drops to ~0.39 and is kept. That's the known ceiling of
dependency-free token matching; embeddings would be needed to close it, not
worth the dependency. When writing tests, use realistic near-duplicates
(reorder + minor wording), not aggressive synonym swaps, or the test asserts
behavior the design intentionally doesn't have.

## WORKFLOW PITFALL: the plugin may already be mid-fixed

Before re-implementing ANY fix to `memory-session-end/__init__.py`, read the
current file end-to-end first. The plugin lives in the agent home directory (`~/.hermes`), often under an
auto-backup remote, and is edited in place; a prior session's
work shows up as `MM` git status, a stray `__init__.py.bak`, and helper
functions that already exist. A June 2026 session planned the whole topic-file
fix, started implementing, and only avoided shipping a duplicate function block
because Pyright flagged `reportRedeclaration`. Cost: a wasted FilePatch +
revert. Check `git status plugins/memory-session-end/` and grep for the helper
names you intend to add BEFORE writing. This is the general "grep target files
first" rule applied to this specific high-churn file.

## Manual Prune Technique

When pending is 1000+ lines, LLM judgment is too expensive. Use this pattern:

```python
# 1. Count duplication by topic
grep -oE '\[proj:[^]]+\]' .pending.md | sort | uniq -c | sort -rn

# 2. For topics with >5 entries, consolidate to ONE entry per distinct fact
# 3. Kill: stale tasks, rules already in SOUL.md, PR numbers, commit SHAs
# 4. Target: <50 entries from any starting point
```

## Key Insight

The memory system is designed for cheap re-extraction. If something matters,
the session-end plugin will re-capture it from a future session. This means
eviction is low-cost, and "unsure = keep" is the wrong default when memory
is full. Better: "unsure + over 70% = evict."
