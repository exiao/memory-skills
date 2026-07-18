# Generic / File-Based Setup

Platform-specific install for any agent that can read and write files (OpenCode, Hermes Agent, OpenClaw, or a custom runtime). For the entry format, categories, episode format, recall, and GC, see the shared spec in [`../SKILL.md`](../SKILL.md).

## Step 1: Create the workspace

Use the canonical `~/.hermes` root that `memory-gc` and `recall` operate on. If your agent uses a different config dir, either point it at this workspace or update every `memory-gc`/`recall` command to your alternate root (don't split them, or GC prunes the wrong tree).

| Agent | Config location |
|-------|-----------------|
| OpenCode | `~/.opencode/` |
| Hermes Agent | `~/.hermes/` |
| OpenClaw | `~/.openclaw/workspace/` |
| Generic | point your agent at `~/.hermes/` |

```bash
WORKSPACE="$HOME/.hermes"
mkdir -p "$WORKSPACE/memories" "$WORKSPACE/episodes" "$WORKSPACE/sessions"
mkdir -p "$WORKSPACE/plans/archive"
```

Create `MEMORY.md` and `USER.md` under `memories/` per the shared spec.

## Step 2: Load at session start

Point your agent's system prompt / operating-instructions file (`AGENTS.md`, `SOUL.md`, etc.) at the store:

```markdown
## Memory
- Read `~/.hermes/memories/MEMORY.md` and `USER.md` at the start of each session.
- **Capture incrementally:** append durable facts to MEMORY.md as `[YYYY-MM-DD][cat] content`
  the moment they appear — do not wait for session end.
- Never fabricate a creation date or invent history.
```

## Step 3: Session-end extraction

If your agent has no session-end hook, use one of:

**Manual prompt** — end sessions with:
> "Before we end, write any important decisions, preferences, or facts from this session to MEMORY.md using the `[YYYY-MM-DD][cat] content` format, and a one-paragraph episode to episodes/YYYY-MM-DD.md."

**Operating-instructions rule** — add to `AGENTS.md` / `SOUL.md`:
```markdown
## Session End
Before ending any session, review the conversation for durable facts, decisions, or
corrections and write them to MEMORY.md. Append a 1-paragraph episode to episodes/YYYY-MM-DD.md.
```

Incremental capture (Step 2) is the reliable path; session-end extraction is a backstop.

## Step 4: Backup

Treat memory as irreplaceable:

```bash
cd "$WORKSPACE"
git init
echo -e ".DS_Store\n.env\n**/*.key\n**/*.pem\n**/secrets*" > .gitignore
git add memories/ episodes/
[ -f SOUL.md ] && git add SOUL.md
git commit -m "Initial memory setup"
gh repo create agent-memory --private --source . --push
```

Consider a periodic cron backup that auto-commits and pushes.
