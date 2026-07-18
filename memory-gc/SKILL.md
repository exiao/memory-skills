---
name: memory-gc
description: |
  Daily memory garbage collection for MEMORY.md / USER.md. Apply decay rules,
  drain .pending.md, consolidate near-duplicates, maintain canonical theme tags,
  prune old episode and session files. Invoke when asked to "run memory GC",
  "clean up memory", "apply memory decay", or from the scheduled cron job.
preloaded: true
---

# memory-gc

Daily garbage collection pass for the Hermes memory system. Read this whole
skill before taking any action. Execute steps in order. Use the `memory` tool
for MEMORY.md / USER.md mutations; use the terminal for filesystem pruning.

## Inputs you already have

- `MEMORY.md` and `USER.md` are already in your system prompt (the snapshot
  shown at the top of this session). Read them there. Each entry looks like:
  ```
  [YYYY-MM-DD][cat] content
  ```

## Tool availability

The `memory` tool IS available in cron (toolset enabled, config has
memory_enabled:true). Use it normally. If it returns "Memory is not available", fall back to direct file
editing via `FilePatch` on `~/.hermes/memories/MEMORY.md`.

**Pitfall — MemoryStore target values:** Current Hermes memory tool schemas may expose
`target` as `"memory"` (for MEMORY.md) and `"user"` (for USER.md); older runtimes
or docs may refer to `"MemoryStore"`. Use the target names from the live tool schema
first. If MEMORY writes fail with target/remapping errors, use `FilePatch` directly
on `~/.hermes/memories/MEMORY.md` instead. The `"user"` target works reliably.

**Pitfall — serial hot-memory mutations:** Do not parallelize multiple `memory`
tool mutations against the same target when capacity, separators, or later
old_text matches depend on the previous mutation. The tool returns a fresh
snapshot after each write; parallel removals/replacements can race or make the
reported usage misleading. Archive removals in one Python pass if useful, then
run `memory remove/replace/add` calls serially for MEMORY.md or USER.md.

When using FilePatch:
- Remove entries by replacing the entry text AND its trailing `§` separator
  line together in one replacement (match `<entry text>\n§` → empty string).
  This avoids orphaned separators.
- If the entry is the LAST in the file (no trailing `§`), remove just the entry
  text and the preceding `\n§\n` from the entry above it.
- Clean up resulting blank lines with portable Python afterward:
```bash
python3 - <<'PY'
from pathlib import Path
p = Path.home() / '.hermes/memories/MEMORY.md'
p.write_text('\n'.join(l for l in p.read_text().splitlines() if l.strip()) + '\n')
PY
```
- The same safety rails apply: never touch `[rule]` or `[meta]` entries.

**Pitfall — multibyte characters:** MEMORY.md may contain unicode (arrows,
special chars in old entries). Use Python for age computation rather than
awk, which chokes on multibyte sequences in some locales.

**Pitfall — block removal sweeps interleaved keepers (DATA LOSS):** When
removing 2+ entries via a single block-replace, NEVER assume the block is
homogeneous. Non-target entries (especially `[rule]` / `[meta]`) are often
interleaved between the entries you want gone. A whole-block `old_string` →
condensed `new_string` will silently delete every interleaved keeper. Before
any block replace: read the EXACT lines in the block (FileRead the range, do
not trust memory), confirm every entry in `old_string` is genuinely a removal
target, and copy any interleaved keepers verbatim into `new_string`. After the
patch, `grep -c` for a distinctive phrase from each keeper to verify it
survived. This bit during a topic-pointer consolidation: two `[rule]` entries
sat between the pointers and were swept up; they had to be restored in a
follow-up patch.

**Pitfall — FilePatch `§` uniqueness:** The `§` separator appears on every
entry boundary. `old_string` containing just `<text>\n§` will often match
multiple locations. Always include enough surrounding context (adjacent
entry text on both sides) to make the match unique. Alternatively, batch
multiple adjacent removals into a single FilePatch that replaces the whole
multi-entry block at once — this is more reliable than individual removals
and is the PREFERRED approach when removing 2+ entries. Include the preceding
entry's text as an anchor in old_string and keep it in new_string.

**Pitfall — last entry has no trailing `§`:** The final entry in MEMORY.md
typically has no `§` after it. When removing the last entry, your replacement
must also consume the `§\n` that preceded it (from the second-to-last entry's
separator). When removing a middle entry, consume it plus its trailing `\n§\n`.
Always verify with `tail -5` after patching to confirm no orphaned separators
or missing newlines.

**Pitfall — malformed separators (concatenated `§`):** Occasionally the `§`
separator gets concatenated to the end of an entry line instead of appearing
on its own line (e.g., `...fallback.§` instead of `...fallback.\n§`). When
you encounter this during removal or relocation, fix the formatting in the
same FilePatch operation: split the concatenated `§` onto its own line. If
removing the entry, just include the malformed form in `old_string`. If
keeping adjacent entries, normalize the separator. Detect early with:
`grep '.\§' ~/.hermes/memories/MEMORY.md` (any non-newline char before `§`).

**Pitfall — pending drain in cron:** The `memory` tool IS available in cron.
Always drain pending. Never skip it.

**Pitfall — memory tool threat scanner:** The memory tool may block otherwise safe replacements if the new content contains sensitive-path patterns such as exact secret-file paths. When shortening or normalizing existing memory entries, preserve the meaning with safer generalized wording (e.g. "source env files" instead of naming a private env file) rather than falling back to direct file edits. Do not bypass scanner blocks for entries involving secrets.

**Pitfall — shell writes blocked by git guard:** Dedicated memory files
(`~/.hermes/memories/*.md`) live inside a git-tracked directory. Shell write
commands like `cat >>` or heredocs can be intercepted by the
`block-dangerous-merges` plugin, which scans shell commands for git-like
patterns and may false-positive on writes to tracked paths. Always use
`FilePatch` (mode=replace, extending the last line) to append to dedicated
memory files. This bypasses shell interception entirely.

**Pitfall — all-or-nothing patches:** FilePatch validates every hunk before
writing. One no-op hunk (old text identical to new text) or stale hunk aborts
the entire multi-file patch, even if the other hunks are good. For large memory
shortening passes, remove no-op hunks before submitting, or split risky edits
into smaller patches so one stale line does not cancel the whole pass.

## Decay rules (from the `[meta] Memory format` entry)

| cat                    | action                                              |
|------------------------|-----------------------------------------------------|
| `fact`, `pref`         | review at 60d: still true? keep or `remove`         |
| `env`                  | review at 30d: still accurate? keep or `remove`     |
| `proj:<path-or-namespace>` | review at 21d; `remove` only when an explicit filesystem path no longer exists |
| `rel:<name>`           | never decay; `remove` only with explicit evidence the relationship/contact fact is obsolete or the user asks |
| `task`                 | review at 14d; `remove` if completed or abandoned   |
| `tmp`                  | hard `remove` at 7d — no review                     |
| `rule`, `meta`         | never decay                                         |

"Review" = a judgment call by you. Err on the side of keeping. When removing,
log the removal in the final report.

## Archival logging (ALL removals — deduplicated)

Before deleting ANY entry — whether a step-2 hard drop, a step-3 review
removal, a step-4 pending discard, or a step-8 capacity eviction — append its
full content to `~/.hermes/episodes/.gc.log` so nothing is truly lost. The
archive must be **deduplicated**: never write an entry whose content already
exists in `.gc.log`.

Use this helper for every removal. It is idempotent — calling it twice with
the same content writes only once:

```bash
gc_archive() {  # usage: gc_archive "<full entry text>"
  local entry="$1"
  local log="$HOME/.hermes/episodes/.gc.log"
  touch "$log"
  # Dedup: skip if this exact entry body is already archived (fixed-string match)
  grep -Fqx "$entry" "$log" || printf '%s\n' "$entry" >> "$log"
}
```

For batch removals, collect the bodies and archive them in one pass, still
deduplicated:

```bash
python3 - <<'PY'
from pathlib import Path
log = Path.home() / '.hermes/episodes/.gc.log'
log.touch()
existing = set(log.read_text().splitlines())
removed = [
    # paste full entry bodies being removed this run, one string each
]
with log.open('a') as f:
    for e in removed:
        if e not in existing:
            f.write(e + '\n')
            existing.add(e)
PY
```

Run the appropriate archive step IMMEDIATELY before each removal/discard
below. The capacity-eviction log in step 8 is now subsumed by this rule (still
dedup before appending). Do NOT copy archived entries back into `.pending.md`
or MEMORY.md — `.gc.log` is a one-way archive, not a re-injection source.

## Procedure

### 1. Compute ages

For each entry in MEMORY.md and USER.md, parse the leading `[YYYY-MM-DD]`
and compute the age in days relative to today. Skip any entry without a
parseable date — report it as unparseable.

**USER.md core profile exception:** USER.md often starts with a prose profile
block before the first `§`. Treat that first non-dated block as expected core
profile, not a parse anomaly. Only report unparseable dated-entry areas below
the core profile separator.

Also detect malformed separators: `grep '.\§' ~/.hermes/memories/MEMORY.md`.
Fix any concatenated `§` characters (entry text with `§` appended without
newline) during the first FilePatch operation that touches the affected area.

If only a few MEMORY.md or USER.md entries are unparseable while the rest of the
file parses, do not stop the whole run. Treat them as malformed hot-memory entries:
archive the full text first, then either normalize them into a dated entry if the
category is obvious or, preferably, relocate durable project/runtime content into
the relevant topic file and remove it from hot memory. For USER.md below the core
profile separator, use `memory` target `user` with `action: replace` when the
entry is merely missing a leading date/category. Keep the user preference intact,
add the earliest defensible date visible inside the malformed text, and re-check
parsing after the patch. If USER.md is slightly over its 5000-char limit because
of that malformed entry, it is still safe to normalize/shorten that one entry as
part of parse repair; do not treat this as permission to rewrite the core profile
or run a broad USER preference consolidation.

### 2. Apply hard drops (no review, no judgment)

- `[tmp]` entries older than 7 days → `memory` tool, `action: remove`, `old_text` = shortest unique substring.
- `[proj:<path-or-namespace>]` entries where the tag is explicitly an absolute
  filesystem path (or `~` expanded against the current home) and that resolved
  path does not exist on disk → archive + remove. Do **not** hard-drop
  `proj:./...` or `proj:../...` merely by resolving them against the GC process
  cwd; cron may run from `~/.hermes`, not the original project. Only prune a
  relative project tag after resolving it against a known/stored project root
  captured with the memory entry. If no such base is available, treat it like a
  namespace and review/relocate by content. Namespace-only project tags such as
  `proj:<name>-wiki`, `proj:<name>-agent`, or `proj:<name>` are not path checks;
  review them by content and keep/relocate if still useful.

### 3. Apply review rules

For each entry past its review threshold (from the table above):
- If it's still plausibly accurate / still used → keep.
- If it is obviously stale (refers to resolved tmp state, abandoned project,
  superseded decision) → remove.

**Confidence gate (capacity-aware):** Check `wc -c ~/.hermes/memories/MEMORY.md`
against 70% of the configured `memory_char_limit` (read it from config — see
step 8; e.g. limit 8000 → 5600).
- If MEMORY.md is OVER the 70% target: "Unsure" = evict. The system
  will re-extract from future sessions if it matters.
- If MEMORY.md is UNDER the 70% target: "Unsure" = keep. There's room, no harm.

**Dedicated memory file check:** Before keeping a `[proj:*]` entry, check if a
dedicated file exists at `~/.hermes/memories/` that covers the same project
(e.g., `<project-a>.md`, `<project-b>.md`, `<service>.md`,
`INFRASTRUCTURE.md`). If the entry's content is already in that file, remove
it from MEMORY.md — it's redundant. If the entry contains NEW info not yet in
the dedicated file, MOVE it there (append to the appropriate section) then
remove from MEMORY.md. This "relocate" pattern is the best way to reclaim
MEMORY.md capacity without losing information.

### 4. Triage `.pending.md` (prune BEFORE draining)

First, run the deterministic dedup script to remove obvious duplicates. If the
runtime has not installed `~/.hermes/scripts/dedup-pending.py`, use the inline
fallback below rather than failing the GC run:

```bash
if [ -x ~/.hermes/scripts/dedup-pending.py ]; then
  python3 ~/.hermes/scripts/dedup-pending.py
else
  python3 - <<'PY'
from pathlib import Path
p = Path.home() / '.hermes/episodes/.pending.md'
if p.exists():
    seen = set(); out = []
    for line in p.read_text().splitlines():
        if line and line not in seen:
            seen.add(line); out.append(line)
    p.write_text('\n'.join(out) + ('\n' if out else ''))
PY
fi
```

Then check what remains:

```bash
test -s ~/.hermes/episodes/.pending.md && wc -l ~/.hermes/episodes/.pending.md
```

**If pending > 100 lines, run a manual prune pass FIRST.** The session-end
plugin has no awareness of existing memory and will re-extract known facts
every session. Expect massive duplication (same project fact repeated 10-50x
with slight rephrasing). The dedup script catches exact duplicates but misses
semantic duplicates (same fact rephrased differently), so expect ~0 removals
from the script even with 100+ duplicate entries.

**Preferred: scripted semantic prune.** Use the proven two-pass script at
`scripts/prune_pending.py` (in this skill's directory):

```bash
SKILL_DIR="${SKILL_DIR:-$HOME/.hermes/skills/memory-gc}"
python3 "$SKILL_DIR/scripts/prune_pending.py"
```

If your runtime exposes the loaded skill directory under a different variable or
path, set `SKILL_DIR` to that `memory-gc/` folder first. The script is bundled
inside this skill; do not use a path with an extra category directory unless you
actually installed it there.

Pass 1 hard-drops `[tmp]` entries, stale/completed `[task]` entries, and rule minutiae,
then deduplicates within each category by topic key (keeps longest per topic).
Pass 2 collapses cross-category namespace sprawl (the #1 duplication source:
a single project may generate entries under `proj:<name>`,
`proj:<name>-wiki`, `proj:<name>-agent`, `proj:<name>/<subdir>`,
`proj:<name>-cli`, `proj:<name>-site` — all one project).

**Target:** Prune to <50 entries. For files of 100-200 lines, expect 84%
removal (191→31 proven). For 600+ lines, expect the script to reach ~50-100
entries after expanded generic-rule and transient-fact filtering (updated May
2026 to drop common coding patterns like error handling, XSS, race conditions,
validation, CI patterns, and transient operational facts like ad metrics and
PR statuses). If still >50 after the script, a short inline Python pass
targeting remaining PR-specific facts and project-detail duplicates typically
closes the gap.

If the prune script still leaves >100 lines, do NOT drain them into MEMORY.md.
Treat that as semantic-prune miss, then run a second manual pass: relocate durable
project/runtime facts into dedicated memory files, discard PR/task minutiae, and
clear `.pending.md`. Pending overflow is cheaper to discard than to pollute
MEMORY.md or USER.md.

**Emergency fast path for 200+ survivors:** Use counters before reading the whole
file. Count targets/categories/topic keywords, then archive every surviving
`TARGET\tLINE` body individually. Do not hand-drain hundreds of PR statuses into
MEMORY.md. Instead, preserve only class-level learning by writing concise grouped
sections into the relevant topic files (for example a project's architecture, its data
quality, assistant-runtime routing, investing research), then clear pending. If
you create or materially update topic files, rebuild `INDEX.md`, add compact
non-empty descriptions for new files that otherwise show `(no description)`, and
add only the few hot `[meta] Topic file:` pointers needed for files created or
materially touched this run. This preserves useful architectural/runtime facts
without ballooning MEMORY.md.

If the prune script leaves **50-100 entries**, do not blindly drain just because
it is under the hard stop. Read the survivors and apply the fast path below:
relocate durable architectural/runtime facts into dedicated files, discard
PR/task/status minutiae, and clear pending. In practice, a 283→80 prune can
still contain mostly duplicate project state that belongs in a project topic file
(`<project-a>.md`, `<project-b>.md`) or `INFRASTRUCTURE.md`, not MEMORY.md.

If the script's topic keys don't cover a new project, extend the `mega_topic`
function with a new block matching the project's namespace variants.

Fallback manual prune pass (if scripting feels overkill for <50 entries):
1. **Count by topic:** `grep -oE '\[proj:[^]]+\]' .pending.md | sort | uniq -c | sort -rn`
2. **Nuke duplicates:** For any topic with >5 entries, read them all and write
   ONE consolidated entry per genuinely distinct fact. Discard the rest.
3. **Review tasks:** Remove `[task]` entries only when they are past the 14-day
   review window or clearly completed/abandoned; keep active follow-ups for the
   normal drain/review path.
4. **Kill redundant rules:** Remove rules already captured in SOUL.md or MEMORY.md.
5. **Kill generic coding rules:** Discard ALL rules about language syntax
   (f-strings, imports, line length), basic git usage (stash, merge conflicts,
   push after commit), linting/formatting (ruff, eslint), or general software
   practices (cache keys, error handling, path validation). These are common
   knowledge, not durable memory. Only keep rules that encode a *project-specific
   convention* or a *user-specific preference* not derivable from first principles.
6. **Kill project minutiae:** PR numbers, commit SHAs, specific file paths, and
   intermediate debugging steps are not durable. Keep only architectural decisions.

Then drain the surviving entries:

**Fast path — when dedicated files cover most projects:** After pruning, if
every surviving `[proj:*]` entry maps to an existing dedicated memory file
AND surviving `[rule]`/`[fact]` entries are project-specific code rules (not
general agent rules), relocate architectural facts to dedicated files and
discard everything else. In practice this is the common case: the prune script
drops tasks/tmp, and what remains is project-specific detail that belongs
in `<project-a>.md`, `<project-b>.md`, `<service>.md`, etc. Batch
related facts into a single new subsection per file (e.g.,
"### Code Rules (May 2026)") rather than appending one entry at a time. After
relocation, clear pending with no drain into MEMORY.md.

**Relocate before draining -- this is the highest-ROI move.** After pruning
duplicates, check if surviving `[proj:*]` entries contain architectural facts
that belong in a dedicated memory file (`<project-a>.md`,
`<project-b>.md`, `<service>.md`, etc.). If so, append the
information as a new subsection to the appropriate dedicated file and discard
the pending entry. In practice, a single GC run can relocate 5-10 entries into
2-3 new subsections in a dedicated file, preserving all information without
consuming any MEMORY.md capacity. Only entries that don't fit any dedicated
file should be candidates for draining into MEMORY.md.

When the prune script leaves a small but still duplicate-heavy survivor set
(<50 lines), do a consolidation pass before appending to dedicated files: group
same-topic pending lines (e.g. several WhatsApp/Bloom CTA lines, several Modal
batch timeout lines) into one concise bullet block per dedicated file. Archive
all survivor lines individually before clearing `.pending.md`, even if only the
consolidated version was relocated.

When the prune script still leaves a medium survivor set (~100-200 lines), use
the same consolidation pattern instead of hand-draining: archive every survivor
body, group by durable topic, append a compact "GC Consolidated Notes" subsection
to the relevant topic files, and clear pending. Treat PR status, merge state, and
one-off review outcomes as discardable; preserve only class-level rules, durable
architecture, routing quirks, and user-approved product decisions. This proved
workable on 312→164 and 203→126 pending runs by relocating grouped notes into
project, service, runtime, taxonomy, and persona topic files while keeping
MEMORY.md at capacity target. After relocation, remove or shorten any redundant
hot-memory entry that now duplicates the topic file rather than draining a new
hot entry.

Each non-empty line is `TARGET\tLINE`. **Before discarding any line, archive it
with `gc_archive` (deduplicated — see "Archival logging" above).** For each line:
- If MEMORY.md already contains the same information (even rephrased) → archive + discard.
- If a dedicated memory file already covers it → archive + discard (it was relocated or already known).
- If it's a stale `[task]` entry (>14d) → archive + discard.
- If genuinely new and MEMORY.md has room → add via `memory` tool.
- If no room → archive + discard (it wasn't important enough to survive triage).

The bulk pending discards from the prune script (step 4) are generic rules /
PR minutiae and need NOT be archived individually; only archive the entries
that survive the prune script and reach this per-line triage. This keeps
`.gc.log` signal-rich rather than flooding it with the 600+ discarded
boilerplate entries.

**ALWAYS clear the file after processing**, even if some entries were discarded:

```bash
: > ~/.hermes/episodes/.pending.md
```

Never leave pending entries to accumulate across runs. If you processed them
(even by discarding), the file gets truncated.

**Final pending recheck:** Memory/tool writes during GC can enqueue a tiny fresh
`.pending.md` tail after the main drain. Before writing the final GC summary,
check `.pending.md` one last time. If new rows appeared, archive each body,
relocate any durable class-level fact into the right topic file, clear pending
again, rebuild INDEX if topic files changed, then append the summary as the
last `.gc.log` line. Do not leave the new tail for tomorrow.

**Contradiction pitfall:** The final pending tail can contain newer corrections
that contradict facts you just consolidated from the earlier survivor set. Do
not blindly archive-and-clear it. If a tail row corrects a relocated note,
patch the topic file immediately so the corrected fact wins, then archive and
clear the row. This commonly shows up as "root cause was X, not Y" after a
large pending consolidation.

### 5. Consolidate near-duplicates

Scan MEMORY.md and USER.md for entries that say essentially the same thing
(different dates or phrasing). Merge into one entry using
`memory` tool `action: replace`. Keep the earliest creation date.

### 6. Maintain canonical themes

Collect every tag used in episode files:

```bash
grep -h "^tags:" ~/.hermes/episodes/*.md 2>/dev/null \
  | sed 's/^tags:[[:space:]]*//' | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' \
  | sort | uniq -c | sort -rn
```

Read the current canonical list from MEMORY.md (the
`[meta] Episode tags (canonical)` entry).

- Any tag used in **≥3** episodes but missing from the canonical list →
  `memory replace` to add it to the `[meta]` entry.
- Near-duplicate tags in use (`debug`/`debugging`, `cron`/`crons`,
  `skill`/`skills`) → pick one canonical spelling. Note the merge in
  your final report (episode-file rewrite is future work, not this pass).

Keep the `[meta] Episode tags` line under ~250 characters. If it starts to
bust, switch from additive mode to consolidation mode: replace the canonical
line with the highest-signal top-used tags, keep canonical spellings, and drop
low-signal or stale tags even if they have historical count. Do not keep
expanding an already-overlong canonical line. When consolidating, prefer the
most common normalized spellings (e.g., `debugging` over `debug`, `cron` over
`crons`) and include only as many top tags as fit under the cap. It is fine to
leave frequently used long-tail tags out if adding them would make the meta
entry too long.

**Optimization:** If the tag output is large and the canonical list hasn't
changed recently, scan only the top ~30 tags for missing canonicals. Don't
waste tokens on the long tail.

### 7. Prune old files

Use recoverable deletion. The global runtime bans permanent `rm`, and `find -delete`
has the same irreversibility problem. Move stale files to `~/.Trash/memory-gc/`
instead of deleting them:

```bash
python3 - <<'PY'
from pathlib import Path
from datetime import datetime
import shutil
home = Path.home()
trash = home / '.Trash' / 'memory-gc'
trash.mkdir(parents=True, exist_ok=True)
now = datetime.now().timestamp()
for root, pattern, days in [
    (home / '.hermes/episodes', '*.md', 90),
    (home / '.hermes/sessions', '*.jsonl', 180),
]:
    if not root.exists():
        continue
    for p in root.glob(pattern):
        if p.name == '.pending.md':
            continue
        if now - p.stat().st_mtime > days * 86400:
            dest = trash / p.name
            if dest.exists():
                dest = trash / f'{dest.stem}-{int(now)}{dest.suffix}'
            shutil.move(str(p), str(dest))
PY
```

### 8. Enforce 70% capacity target

**Prefer consolidation over eviction.** Before evicting any entry, scan for
near-duplicate or overlapping entries that can be merged into one shorter entry
preserving both signals. This is especially effective when slightly over target
(< 200B) — merging two 250B entries into one 180B entry reclaims space without
losing information. Only evict when consolidation alone cannot close the gap.

**Shortening entries:** When only slightly over target (<100 chars), try
shortening wordy `[pref]` or `[env]` entries before evicting anything. Remove
filler phrases ("in YAML frontmatter" → just parenthetical, "should always be"
→ "always", "For ad creative cron/jobs, reject" → "Reject"). If MEMORY.md is
over target and contains mostly protected `[rule]` / `[meta]` entries, shorten
those too, but only as lossless compression: preserve dates, categories, force,
and behavioral meaning. Never remove `[rule]` or `[meta]` entries during GC.
This preserves meaning while reclaiming 30-50 chars per entry; a sequence of
small rewrites can close a large overage without data loss.
Use the memory tool first for MEMORY.md/USER.md. If it blocks on scanner safety,
rewrite the replacement with less sensitive wording rather than bypassing it.

After all removals and drains, check the current size of MEMORY.md AND read the
configured limit from config (do NOT hardcode it — it has changed before, e.g.
6000 → 8000 in June 2026):

```bash
wc -c ~/.hermes/memories/MEMORY.md
LIMIT=$(python3 - <<'PY'
from pathlib import Path
import re
cfg = Path.home() / '.hermes/config.yaml'
limit = ''
if cfg.exists():
    for line in cfg.read_text(encoding='utf-8').splitlines():
        m = re.match(r'\s*memory_char_limit:\s*(\d+)\s*$', line.split('#', 1)[0])
        if m:
            limit = m.group(1)
            break
print(limit or '8000')
PY
)
echo "limit=$LIMIT target(70%)=$((LIMIT*70/100))"
```

Fresh agent-agnostic installs may not have `~/.hermes/config.yaml` or a
`memory_char_limit` key yet. In that case, fail closed to the documented default
limit of 8000 chars rather than treating an empty `$LIMIT` as zero and evicting
all unprotected memory.

The target is **70% of the configured limit** (limit 8000 → target 5600;
limit 6000 → target 4200). Compute it from `$LIMIT`, never from a memorized
number. **GC must always leave the file below 100% of the limit** — parking at
99% is the exact failure mode this step exists to prevent.

**Topic-pointer demotion (the #1 bloat source — do this BEFORE eviction).**
`[meta] Topic file: X = ...` pointers duplicate `INDEX.md`, which recall reads
first. They are hot-route hints, not storage. Keep only pointers for topic files
created, modified, or heavily used in the last ~7 days; cap the total at ~5. For
every other pointer: confirm the file is in `INDEX.md`
(`grep -F '<file>.md' ~/.hermes/memories/INDEX.md`), archive the pointer with
`gc_archive`, then remove it. This is the Claude-Code Dream Phase-4 pattern
(index holds pointers; hot memory does not) and reclaims ~90 bytes per pointer
with zero information loss. Run it every pass so hot memory cannot drift back up.
Note: `[meta]` pointers are normally protected, but topic-pointer demotion is an
explicit exception — you are relocating the pointer to INDEX, not deleting info.

If the file still exceeds the target after pointer demotion, evict entries.
Eviction priority (evict from top priority first):
1. `[env]` entries older than 21 days (even if still accurate; they can be re-added if needed)
2. `[proj:*]` entries older than 14 days
3. `[fact]` entries older than 45 days
4. Longest entries first (within the same priority tier)

**When no entries meet age thresholds but file is over target:** Fall back to
evicting the longest `[env]` entries first, then longest `[proj:*]` entries,
regardless of age. Prefer entries whose content is also captured in a dedicated
memory file (e.g., `~/.hermes/memories/<project>.md`) or in a skill, since
those can be re-derived.

**`[pref]` relocation (the file-stays-at-98% failure mode).** A hot-memory file
dominated by `[rule]` + `[meta]` + long project `[pref]` entries cannot be
brought to target by the env/proj/fact ladder above — those are a small slice
of the bytes. When the file is still over target after that ladder, treat long
**project-scoped** `[pref]` entries as relocation candidates (NOT eviction —
prefs encode user-approved decisions, so move them, don't drop them):
- If a `[pref]` is scoped to a project with a dedicated file (e.g. `<project-a>.md`,
  `<project-b>.md`, `<service>.md`), append its
  content as a dated bullet to that file's notes section, archive the original
  with `gc_archive`, and remove it from MEMORY.md. This is the highest-ROI move
  when rule/meta/pref dominate — a single run can reclaim 1-2 KB.
- Generic, cross-project `[pref]` entries stay hot but get the lossless
  shortening pass (strip filler, keep the decision).
- Never relocate a `[rule]`; rules are behavioral constraints that must stay in
  the system prompt every session.

**Protected-floor guard (never silently park at 98%).** Compute the byte total
of `[rule]` + `[meta]` entries alone. If that floor already exceeds the 70%
target, the target is unreachable without shortening protected entries:
1. Run the lossless-shortening pass on the longest `[rule]`/`[meta]` entries
   (the skill already permits this — preserve dates, categories, force, and
   behavioral meaning) until the file is under 100% of the limit.
2. Relocate every project-scoped `[pref]` per the rule above.
3. If the file is STILL over the 70% target after 1-2, do not loop forever —
   stop at the lowest achievable byte count and **flag it explicitly in the
   final report** ("protected floor N chars exceeds 70% target M; durable rule
   set has outgrown hot memory, consider raising memory_char_limit or splitting
   rules into SOUL.md"). Parking just-under-limit with a flag is correct here;
   parking at 98% with no flag is the bug this guard exists to prevent.

Before removing, archive evicted entries to `~/.hermes/episodes/.gc.log` using
the deduplicated `gc_archive` helper (see "Archival logging" above). Do NOT
copy evicted entries back to `.pending.md` — this creates a circular feedback
loop where entries bounce between MEMORY.md and pending indefinitely.

Keep evicting until the file is at or below the 70% target (computed from
`$LIMIT` above), or only `[rule]` and `[meta]` entries remain.

**USER.md capacity check:** Also check `wc -c ~/.hermes/memories/USER.md`.
USER.md has a 5000-char limit and often runs near capacity (4900-5000). Before
draining any `user`-targeted pending entry, check remaining capacity first.
If USER.md is at 95%+ capacity (4750+ chars), skip the drain — the entry will
be re-extracted if it matters. Don't waste time trying to make room in USER.md;
its core profile section is stable and shouldn't be edited during GC.

**USER.md persistently over limit:** If USER.md exceeds 5000 chars on two
consecutive GC runs, flag it in the report as needing human attention. The
core profile (Identity through Temperament) is stable, but the `[pref]`
entries appended at the bottom accumulate. A human pass to consolidate or
relocate preferences is the right fix — GC should not autonomously edit the
core profile.

**USER.md escalation after 4+ runs over limit:** If USER.md has been flagged
for 4+ consecutive runs (check `.gc.log` for the pattern), GC may
autonomously consolidate `[pref]` entries at the bottom of USER.md (below the
`§` after Temperament). Rules: (a) never touch the core profile above that
`§`, (b) merge semantically overlapping prefs into one shorter entry keeping
the earliest date, (c) relocate project-specific prefs to the project's
dedicated memory file if one exists (e.g., Bloom rollout prefs →
`<project-b>.md`), (d) cap total `[pref]` entries at 6. Log all
changes. This is a pressure valve; if the user objects, revert to flag-only.

### 9. Maintain topic files & INDEX

Topic files (`memories/*.md` excluding core MEMORY/USER/MEM_ARCH/INDEX and
`*.bak`) are the Tier-2 raw-text store. The session-end plugin can now create
them and queues a `[meta] Topic file: X.md = ...` pointer into `.pending.md`
(drained in step 4). GC keeps the registry and pointers consistent.

**a. Archive stale generated-inventory topic files before the routine rebuild.**
Run the candidate query before refreshing `INDEX.md` so a just-generated inventory
row cannot protect every stale file. `INDEX.md` remains the authoritative recall
registry, but only rows with a human-curated description (not `(no description)`)
count as archival references.

```bash
SKILL_DIR="${SKILL_DIR:-$HOME/.hermes/skills/memory-gc}"

# 1. Dry run — print candidates, sanity-check them:
python3 "$SKILL_DIR/scripts/topic_index.py" archive-candidates

# 2. If the list looks right, apply (moves files + rebuilds INDEX):
python3 "$SKILL_DIR/scripts/topic_index.py" archive-candidates --apply
```

Always run the dry run first and eyeball the list — err on the side of
keeping. After `--apply`, remove any now-orphan `[meta]` pointer for the
archived files via the `memory` tool (the script prints a reminder).

**b. Rebuild `INDEX.md`** from the current topic files after archival and after
any topic-file changes. The logic lives in a tested script (`scripts/topic_index.py`),
not inline here:

```bash
SKILL_DIR="${SKILL_DIR:-$HOME/.hermes/skills/memory-gc}"
python3 "$SKILL_DIR/scripts/topic_index.py" rebuild-index
```

It regenerates the registry from disk, preserves existing one-line
descriptions, and excludes core files (MEMORY/USER/MEM_ARCH/INDEX), `*.bak`,
and dotfiles. Run it after any topic-file change (drain, relocation, archive).

**c. Prune stale published-artifact URLs.** If `~/.hermes/memories/artifacts.md`
exists, validate rows in its registry table during the topic-file maintenance pass.
For each row with an `http://` or `https://` URL, do a cheap HEAD request first and
fallback to GET only when HEAD is unsupported. Keep rows that return 2xx/3xx or
that fail due to transient network/auth errors. Move rows that clearly return
404/410/NXDOMAIN into a `## Pruned` section at the bottom with the prune date
instead of deleting them outright. This keeps the auto-populated artifact registry
useful without losing the historical trail.

**d. Reconcile pointers in MEMORY.md.** `INDEX.md` is the authoritative registry;
MEMORY.md pointers are only hot-route hints for high-value or recently touched
topic files. Do **not** add pointers for every topic file when the topic file
count is large, because this can blow the 70% hot-memory target. Instead:
- Missing pointer for a topic file you created, modified, or relocated into this
  run → add one via the `memory` tool (`[<today>][meta] Topic file: <name> = <desc>`).
  Keep descriptions extremely compact (usually 1-3 words).
- Missing pointer for an old untouched topic file → leave it to `INDEX.md`; do
  not spend hot-memory capacity on it.
- Duplicate pointers for the same file → consolidate to one (keep earliest date).
- Orphan pointer (points to a file that no longer exists) → remove it.
Note: most pointers arrive automatically through the step-4 pending drain;
this step just fixes drift for newly touched or stale hot pointers.

**Pitfall — schedule/config truth lives in `jobs.json`, not prose.** Cron
times, model/provider, and enabled state get duplicated into human docs
(`INFRASTRUCTURE.md`'s cron table, `MEM_ARCH.md`'s diagram, SOUL's capacity
note, visual-options docs) and drift over time. When reconciling any such fact,
the authoritative source is `~/.hermes/cron/jobs.json` (the job's
`schedule.expr`), never the prose. memory-gc itself runs at `0 1 * * *` (1am);
older docs that say "4am" are stale and should be corrected to match the cron,
not the reverse. Before "fixing" a doc to agree with another doc, read
`jobs.json` and let it win. Note that the separate `claude-code-memory-*` topic
files describe a Claude Code launchd port that genuinely runs at 4am — those
4am references are correct and must NOT be rewritten to 1am.

**Capacity pitfall:** Step 8 runs before topic-pointer reconciliation, but
adding missing pointers in step 9 can push MEMORY.md back over the 70%
target. Budget hot pointers before adding them: if MEMORY.md is already near
target, add only the highest-value newly touched pointers and leave the rest to
INDEX.md. If you do add multiple pointers, add them one at a time or in a small
batch, then immediately rerun `wc -c ~/.hermes/memories/MEMORY.md` before doing
more. After pointer reconciliation, rerun `wc -c ~/.hermes/memories/MEMORY.md`
and, if over target, do a quick lossless shortening pass (prefer wordy `[rule]`,
`[pref]`, and pointer descriptions) until MEMORY.md is ≤ the 70% target again.
If the file is only slightly over target after all substantive removals, keep
using `memory` `action: replace` for tiny lossless edits until the byte count is
actually under target. Do not stop at “close enough” (e.g. 1 byte over). Good
micro-shortening targets are repeated helper words (`use`, `only`, `globally`),
long pointer descriptions, long canonical tag lists, and redundant detail that
is already in a topic file. If shortening protected entries is not enough,
archive and remove redundant `[pref]`/`[fact]` entries whose detail now lives in
topic files; that is safer than leaving hot memory above target. Count
shortening as `consolidated`, not `removed`.

Tests for this script live in `scripts/test_topic_index.py`
(`python3 scripts/test_topic_index.py` — all in a tempdir).

### 10. Log and report

**Canonical log location:** The ONLY live GC log is `~/.hermes/episodes/.gc.log`.
A stale orphan can exist at `~/.hermes/memories/.gc.log` (legacy location) and
will be frozen at an old date — do not mistake it for evidence that GC stopped
running. If you find the orphan, prepend its older entries to the canonical
log (if they predate the canonical first line) and `trash` the orphan so there
is a single source of truth. Verify GC health by reading the LAST line of
`episodes/.gc.log`, not by trusting whichever log you happened to find first.

Append a one-line summary to `~/.hermes/episodes/.gc.log`:

```bash
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) memory-gc removed=N drained=N consolidated=N themes_added=N files_pruned=N" \
  >> ~/.hermes/episodes/.gc.log
```

Your final response:
- One short paragraph summarizing what changed.
- Only mention anomalies (parse failures, unexpected state, consolidations
  you are unsure about). If everything was routine, say "routine pass, N
  entries removed, M drained, K pruned" and stop.

## References

- `references/pending-overflow-fix.md` — Root cause analysis of .pending.md
  bloat (2165 lines, May 2026) and the 3-part fix for the session-end plugin
  (context injection, prompt tightening, spill dedup). Also contains the
  manual prune technique and the key insight that eviction is cheap in this
  architecture because the session-end plugin will re-extract important facts.
  June 2026 additions: the topic-file blind-spot fix (`_load_topic_context`
  digest injection that stops re-extraction of facts already in topic files —
  the real driver of overflow / bulk-discard), the two-layer spill dedup +
  hard entry cap, the Jaccard dedup ceiling, and a WORKFLOW PITFALL: always
  read `memory-session-end/__init__.py` and `git status` it before
  re-implementing — a prior session may have already shipped the fix in place.
- `references/gc-overflow-relocation.md` — Concise operational pattern for
  200+ pending survivors after prune: archive all survivor bodies, relocate
  only grouped class-level learning into topic files, rebuild/describe INDEX,
  and clear pending without hot-memory drain.
- `references/hot-memory-malformed-relocation.md` — Practical pattern for
  malformed hot-memory entries plus 50-100 pending survivors: archive originals,
  normalize USER entries, relocate project details to topic files, rebuild INDEX,
  add only tiny hot pointers, then verify clean parsing and empty pending.
- `references/medium-pending-relocation.md` — Pattern for 100-150 pending survivors:
  archive every survivor, relocate only class-level facts into topic files, create
  new topic files sparingly, fill INDEX descriptions, and discard stale task/PR/personal state.
- `scripts/prune_pending.py` — Two-pass semantic prune script. Run after the
  deterministic dedup step (external script when present, inline fallback otherwise).
  Handles project namespace sprawl (the primary duplication source). Expected 84%
  reduction on typical 100-200 line pending files.

## Dependencies

- `~/.hermes/scripts/dedup-pending.py` — optional deterministic dedup script run
  in step 4 when present; otherwise use the inline fallback there.
- `~/.hermes/plugins/memory-session-end/` — upstream producer of pending entries
  (fixed May 2026 to inject existing memory context and cap at 0-3 entries)

## Safety rails

- Never `remove` a `[rule]` or `[meta]` entry.
- Never `remove` something whose content you do not understand. Keep it.
- If MEMORY.md / USER.md is malformed (no entries parse), stop immediately
  and report. Do not attempt repair.
- Filesystem commands target only `~/.hermes/episodes`, `~/.hermes/sessions`,
  and `~/.hermes/memories` (the last for INDEX rebuild and topic-file archival
  in step 9, which only ever writes INDEX.md or moves files into
  `memories/archive/` — never deletes, never touches core MEMORY/USER/MEM_ARCH).
  Never touch `hermes-agent`, `skills`, `plans`, `config.yaml`, `.env`, or
  anything outside those directories.