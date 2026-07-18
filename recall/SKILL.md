---
name: recall
preloaded: true
description: |
  Retrieve memory from past sessions. Use whenever the user asks about past
  conversations, prior decisions, "what did we do about X", "when did we
  last...", "do you remember...", or anything where the answer might live
  outside the current session's context.
---

# recall

Three storage tiers, searched cheapest first. Stop at the tier that answers
the question confidently. Do not expand further if more context is not
helping — that is the uncertainty gate.

## Storage tiers

| Tier      | Source                              | Cost                  |
|-----------|-------------------------------------|-----------------------|
| Hot       | `MEMORY.md`, `USER.md`              | ~0 (already in prompt) |
| Topic     | `memories/INDEX.md` → topic `*.md`  | cat index, then 1 file |
| Plans     | `~/.hermes/plans/*.md` + `archive/` | ls/grep filenames     |
| Episodes  | `~/.hermes/episodes/*.md`           | grep, small files     |
| Sessions  | `~/.hermes/sessions/*.jsonl`        | grep, large files     |

**"Where is the plan/PR for X" → check `plans/` FIRST, not episodes.** Plan
files are named by task (`desktop-frontend-chat.md`, `pr-options-history-body.md`).
A completed plan lives in `plans/archive/`. Episodes only summarize what
happened and will mislead: an "options-history" episode may describe a backend
CLI fix while the plan the user wants is a separate desktop-page UI rework with
a similar name. Match the user's actual subject (page vs CLI), not just the
keyword. Run:
```bash
shopt -s nullglob
plan_files=(~/.hermes/plans/*.md ~/.hermes/plans/archive/*.md)
if ((${#plan_files[@]})); then
  printf '%s\n' "${plan_files[@]}" | grep -Fi -- '<keyword>' || true
  grep -Fil -- '<phrase>' "${plan_files[@]}" || true
fi
```
Then read the matching file and report its path + whether it's archived or active.
Do not equate `plans/archive/` with shipped work; shipping status requires checking
the relevant PR, commit, or product artifact surface.

Topic files hold big durable context (architecture, runbooks, research,
theses). Episodes answer "did this happen, and when". Raw sessions answer
"what was the exact error we hit" — the detail the summary dropped.

## Disclosure levels

Run these in order. Stop as soon as you can answer confidently (see
"Uncertainty gate" below).

### L0 — hot memory
Check `MEMORY.md` and `USER.md` (already in your system prompt). If the
answer is there, you are done. Hot memory also contains
`[meta] Topic file: X.md = ...` pointers — if one matches the query, jump
straight to L0.5 and read that file.

### L0.5 — topic files (raw-text store)
For questions about a known subject area (an architecture, a runbook, a
research dump, a saved thesis), the answer often lives in a topic file, not
the episodes. Read the registry first, then the one file that matches:
```bash
cat ~/.hermes/memories/INDEX.md          # registry: filename | description | updated | size
cat ~/.hermes/memories/<file>.md         # the matching topic file
```
The INDEX descriptions let you route without opening every file. This tier is
cheap and high-signal — prefer it over episodes whenever the query is about a
durable subject rather than "when did X happen".

### L1 — list episode dates
```bash
ls ~/.hermes/episodes/ | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$' | sort
```
Useful when the user gives a rough date ("last Tuesday", "a couple weeks
ago") — pick the right file and skip to L3.

### L2 — theme match on tag line (canonical themes)
The `[meta] Episode tags (canonical)` entry in MEMORY.md lists searchable
themes. If the user's query maps to one of those themes, grep only the
`tags:` line of each episode file — precise, no false positives from
passing mentions:
```bash
shopt -s nullglob
episode_files=(~/.hermes/episodes/*.md)
((${#episode_files[@]})) && grep -l "^tags:.*\b<theme>\b" "${episode_files[@]}" || true
shopt -u nullglob
```

### L2.5 — content match across episode files
If L2 misses (query not in canonical themes) or returns nothing, grep
anywhere in episode files:
```bash
shopt -s nullglob
episode_files=(~/.hermes/episodes/*.md)
((${#episode_files[@]})) && grep -Fil -- "<query>" "${episode_files[@]}" || true
shopt -u nullglob
```

### L3 — cat one episode file
Once you have candidate date(s), read the full day's summaries:
```bash
cat ~/.hermes/episodes/<YYYY-MM-DD>.md
```
Each session block has `summary:` and `tags:`. This is usually enough.

### L4 — grep raw session transcripts
When an episode summary dropped the detail you need (exact error string,
code snippet, command used), grep the raw sessions:
```bash
shopt -s nullglob
session_files=(~/.hermes/sessions/*.jsonl)
((${#session_files[@]})) && grep -Fl -- "<query>" "${session_files[@]}" || true
shopt -u nullglob
```
Expensive — only do this if episodes are too coarse.

### L5 — read one raw session
```bash
jq -r '.messages[] | select(.role=="user" or .role=="assistant") | "\(.role): \(.content)"' \
  ~/.hermes/sessions/<session>.jsonl | less
```
Or a simple `cat` if the jsonl is small. Stop here; do not keep searching.

### Recovering specific content (ASCII wireframes, specs, code blocks)

When you need the exact text of something from a past session and episode summaries only have the gist:

```bash
# 1. Find which session file contains the distinctive string
shopt -s nullglob
session_files=(~/.hermes/sessions/*.jsonl)
((${#session_files[@]})) && grep -Fl -- "DISTINCTIVE_PHRASE" "${session_files[@]}" || true
shopt -u nullglob

# 2. Extract the content field containing it
python3 -c "
import json
with open('SESSION_FILE') as f:
    for line in f:
        if 'DISTINCTIVE_PHRASE' not in line: continue
        obj = json.loads(line)
        for key in ['content', 'text']:
            v = obj.get(key, '')
            if isinstance(v, str) and 'DISTINCTIVE_PHRASE' in v:
                print(v[:8000])
                raise SystemExit
"
```

Essential when the user references a wireframe or spec from a prior session and you need the exact layout to compare against an implementation.

## Uncertainty gate

After each tier, self-rate your confidence in the current answer on a
0–1 scale:

1. Start at L0. If confidence ≥ 0.7, answer.
2. Else expand one tier (L0 → L0.5 → L1 → ...). Re-answer. Re-score.
3. If confidence gained from this tier is < 0.1 (context did not help),
   **stop** — more context is noise. Tell the user what you found and
   what's still uncertain.
4. Hard cap at L5. If still low confidence there, say you don't know.
   Do not fabricate.

Skipping tiers is fine when the query shape makes the lower tier irrelevant
(e.g. date-shaped query → straight to L3; exact-error query → straight
to L4).

## Optional — synthesis subagent (context-window protection)

The tiers above read files into *your* context. Usually fine. But when a recall would
pull in a lot of bulk — multiple topic files plus several episode days, or a deep L4/L5
transcript grep — and you're mid-task and want to keep your working context clean, you
can delegate the read instead of catting it all into your own window.

Hand the candidate files to a subagent; it reads them and returns ONLY the facts
relevant to the query as JSON. The raw bulk never enters your context — you get back a
short, cited answer.

Reach for this only when all three hold:
1. the cheap tiers (L0–L0.5) already missed,
2. answering needs ≥3 large files (topic files and/or episode days), AND
3. you're in the middle of other work and context budget matters.

For a quick lookup where one `cat` answers the question, skip it — the subagent
round-trip isn't worth the latency.

**Launch it read-only** (no Edit/Write/patch — a retrieval pass must be unable to
mutate). Give it the file manifest plus bodies and the query. Contract:

> You read persistent memory files and extract facts to answer a query. Return a JSON
> object: `relevant_facts` (array, max 7, each 1–2 sentences, lifted verbatim from a
> file body — never derived from general knowledge or your own reasoning) and
> `cited_memories` (array of filenames you drew from, matching the manifest exactly).
> You are a retrieval step, not the assistant: do not answer or solve the query
> yourself. If no file covers it, return `relevant_facts: []` and `cited_memories: []`.

Then answer from the returned facts, citing the files it named. If it returns empty,
fall back to reading the files inline or tell the user what's missing — don't fabricate.

## Output shape

- If a single clear answer emerged, state it with the episode date as
evidence: *"On 2026-04-15 we fixed the Anthropic proxy routing — the
`_get_model_config()` merge patch."*
- If the user is asking you to resume unfinished work, do not stop at locating the session. Extract the pending action, then complete or continue it with the appropriate tools. Report both the source session and the completed continuation.
- If multiple episodes matched, list them briefly with dates and let the user pick.
- If nothing matched, say so — do not invent.


## Project artifact verification

When the user asks where a previous run/upload lives locally or whether it updated another surface, do not answer from recall alone. Verify the actual artifact surfaces for that project: workspace/output directories, local databases, generated docs/wiki files, and git history where applicable. For a project that generates artifacts in several places, a project-scoped reference (e.g. `<project>/references/local-run-artifact-verification.md`) should enumerate them: the workspace, any output directory, a local database, and generated docs/wiki files are separate surfaces and can disagree after later regenerations.

### A plan in `archive/` does NOT mean the feature shipped

`plans/archive/` only means a plan was filed away — it does NOT prove the code
landed. Episode summaries compound this: a summary may say a feature is
"completed/shipped" when only the *plan doc* (or a surge mockup) was produced.
Never report a feature as shipped based on plan location or summary wording
alone. Verify against the real code surfaces before answering "is X shipped?":

```bash
# 1. The canonical checkout on its default branch
git -C <repo> branch --show-current          # confirm you're on master/main
grep -Fic -- "<FeatureMarker>" <repo>/<file> # e.g. ChatPanel, the function name

# 2. Every plausible feature branch (don't trust just one)
while IFS= read -r b; do
  echo "$b: $(git -C <repo> show "$b":<file> | grep -Fic -- '<FeatureMarker>')"
done < <(
  git -C <repo> for-each-ref --format='%(refname:short)' refs/heads refs/remotes |
    grep -iE "<feature-stem>" || true
)

# 3. Did any PR ever touch that file with that change?
git -C <repo> log --all --oneline -S "<FeatureMarker>" -- <file>
gh pr list --repo <org/repo> --state all --search "<feature>" --limit 10

# 4. If it's a hosted demo/site, curl the LIVE surface too — a surge/Render
#    preview can lag or diverge from the repo, and vice versa.
curl -s https://<site> | grep -Fic -- "<FeatureMarker>"
```

If grep returns 0 across the checkout, all candidate branches, PR history, AND
the live site, the feature is unbuilt — say so plainly, regardless of what the
archived plan or episode summary claims. "Plan archived" + "code absent" = the
plan was filed without implementation; offer to pick it up as a fresh build.

## Project-local session extraction

When a project runs its own Hermes Agent instance (e.g. at
`~/projects/<project>/hermes_home/`), its sessions live in THAT project's
`hermes_home/sessions/`, not `~/.hermes/sessions/`. If workspace output
files are missing but the run log shows completion, extract outputs from
the session JSON's `write_file` tool call arguments. See
`references/hermes-agent-session-extraction.md` for the extraction pattern.

## High-confidence mode (anti-hallucination)

When the stakes are high (exact past decisions, specific numbers, resolving
contradictory memories), use the verbatim-quote extraction pattern from
`references/anti-hallucination-recall-pattern.md`. Two-step: extract only
exact quotes with line numbers, then synthesize citing only those quotes.
Costlier but prevents confabulation.

## Safety rails

- Never expose content from `~/.hermes/.env`, `auth.json`, `state.db`, or
  anything in `~/.ssh/` / `~/.aws/`. `recall` reads only `episodes/` and
  `sessions/`.
- Never share raw transcript content from group-chat sessions without
  summarizing first. Signal UUIDs, phone numbers, and third-party PII
  must not appear in your answer even if they appear in the transcript.

## Pitfalls

- **UX wireframes and design specs** often live in assistant responses in
  raw session transcripts, not in episode summaries. Episode summaries say
  "mapped out UX" but drop the actual wireframe. When the user references
  a past wireframe ("this was what was supposed to be built"), go straight
  to L4 (grep sessions) with structural keywords: page titles, box-drawing
  chars (`+--`, `|`), or domain terms like "SUB-NAV", "PRIMARY TAB",
  "FEED", etc. Use `json.dumps(obj)` containment check on each line, then
  extract from the matching message's `content` key.
- **Session JSON structure varies.** Messages may be at `obj['content']`,
  `obj['messages'][n]['content']`, or `obj['parts'][n]['text']`. Always
  check all three patterns when doing L5 extraction.
