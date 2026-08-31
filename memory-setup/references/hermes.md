# Hermes Agent Setup

Platform-specific install for the memory system in Hermes Agent. For the entry format, categories, episode format, recall, and GC, see the shared spec in [`../SKILL.md`](../SKILL.md).

Hermes loads `memories/MEMORY.md` and `memories/USER.md` into the system prompt on every turn and exposes **plugin lifecycle hooks**, so session-end extraction can be fully automatic. The store lives at `~/.hermes/` — the same root `memory-gc` and `recall` already operate on, so no retargeting is needed.

## Step 1: Bootstrap the workspace

Same layout as every other platform (shared spec in [`../SKILL.md`](../SKILL.md)), and Hermes already uses this root:

```bash
WORKSPACE="$HOME/.hermes"
mkdir -p "$WORKSPACE/memories" "$WORKSPACE/episodes" "$WORKSPACE/sessions"
[ -f "$WORKSPACE/memories/MEMORY.md" ] || printf '# MEMORY.md\n\n> Durable facts. Loaded every session. Format: [YYYY-MM-DD][cat] content\n\n' > "$WORKSPACE/memories/MEMORY.md"
[ -f "$WORKSPACE/memories/USER.md" ] || printf '# USER.md\n\n- **Name:**\n- **Timezone:**\n- **Communication style:**\n- **Key preferences:**\n' > "$WORKSPACE/memories/USER.md"
```

## Step 2: Capture incrementally

Add a memory section to `~/.hermes/SOUL.md` (or your `AGENTS.md`) so facts are written as they appear, not only at session end:

```markdown
## Memory
- Read `~/.hermes/memories/MEMORY.md` and `USER.md` at the start of each session.
- **Capture incrementally:** append durable facts as `[YYYY-MM-DD][cat] content`
  the moment they appear — do not wait for session end.
- Categories: fact, pref, env, proj:<path>, rel:<name>, task, tmp, rule, meta.
- Never fabricate a creation date or invent history.
```

This alone is a complete setup. Step 3 is a backstop that catches what incremental capture missed, and it is where the interesting failure modes live. Also set up [`memory-gc`](../../memory-gc/SKILL.md) on a daily schedule and back the store up per [`generic.md`](generic.md#step-4-backup).

## Step 3: Pick the right hook (read this before writing a plugin)

Hermes fires four session lifecycle hooks. One of them is named misleadingly, and picking it costs a model call on every message you send.

| Hook | When it actually fires | Use for extraction? |
|------|------------------------|---------------------|
| `on_session_start` | Session begins | No |
| `on_session_end` | **After every user message** | **No — see below** |
| `on_session_finalize` | Idle expiry, CLI exit, `/new`'s finalize leg | **Yes** |
| `on_session_reset` | `/new` and `/reset`, after the new session exists | **Yes** |

**`on_session_end` is a per-turn cleanup hook despite the name.** `agent/turn_finalizer.py` fires it at the end of every `run_conversation()` call, and `run_conversation()` is called once per user message. The core's own comment says so:

> `run_conversation()` is called once per user message in multi-turn sessions. Shutting down after every turn would kill the provider before the second message. Actual session-end cleanup is handled by the CLI (atexit / /reset) and gateway (session expiry).

Registering a full transcript extraction there means one auxiliary LLM call per message, each re-reading a transcript that grows every turn. Measured on a real install: **428 extractions across 41 sessions in one day**, one session firing 46 times, for what should have been 41 calls. The extractor's own dedup discarded most of the output — after paying for it.

Register on `on_session_finalize` and `on_session_reset` instead.

## Step 4: Write the plugin

A plugin is a directory under `~/.hermes/plugins/<name>/` with a `plugin.yaml` and an `__init__.py` exporting `register(ctx)`.

```yaml
# ~/.hermes/plugins/memory-session-end/plugin.yaml
name: memory-session-end
version: "1.0"
description: "Extract durable memories and an episode summary at real session boundaries."
hooks:
  - on_session_finalize
  - on_session_reset
```

The `hooks:` list is documentation — the loader honors what `register()` actually calls — but keep it accurate or the next reader debugs the wrong file.

```python
# ~/.hermes/plugins/memory-session-end/__init__.py
import json, logging, threading, time
from collections import OrderedDict
from pathlib import Path

logger = logging.getLogger(__name__)
MIN_TURNS = 3
PROMPT = (Path(__file__).parent / "extract.md").read_text(encoding="utf-8")


def _load_transcript(session_id: str):
    """Return [(role, content), ...] for this session, or [] on failure."""
    try:
        from hermes_state import SessionDB   # hermes-agent is on sys.path
        msgs = SessionDB().get_messages(session_id) or []
    except Exception as exc:
        logger.warning("transcript load failed: %s", exc)
        return []
    return [
        (m.get("role") or "", m.get("content") or "")
        for m in msgs
        if m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str) and m["content"].strip()
    ]


def _extract(turns):
    """Call the auxiliary model. Returns a dict or None."""
    from agent.auxiliary_client import get_text_auxiliary_client
    client, model = get_text_auxiliary_client(task="memory_extract")
    if client is None or not model:
        logger.info("no auxiliary client available, skipping")
        return None
    convo = "\n\n".join(f"{r}: {c}" for r, c in turns[-40:])
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": f"{PROMPT}\n\n{convo}"}],
        timeout=15,
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return None


def _run_extraction(session_id: str) -> None:
    """The actual work. Runs on a background thread."""
    turns = _load_transcript(session_id)
    if len(turns) < MIN_TURNS:
        return
    result = _extract(turns)
    if not isinstance(result, dict):
        return
    # Cap entries in code, not just in the prompt — models drift and a chatty
    # extraction will otherwise flood the overflow queue.
    entries = (result.get("entries") or [])[:3]
    # Write entries to MEMORY.md / USER.md and result["episode"] to
    # episodes/YYYY-MM-DD.md per the shared spec.


# --- boundary plumbing: the part that is easy to get wrong -----------------

_extracted_lock = threading.Lock()
_extracted: "OrderedDict[str, float]" = OrderedDict()
_EXTRACTED_MAX = 512


def _claim_session(session_id: str) -> bool:
    """True if this caller owns extraction for session_id. First hook wins."""
    with _extracted_lock:
        if session_id in _extracted:
            return False
        _extracted[session_id] = time.time()
        while len(_extracted) > _EXTRACTED_MAX:
            _extracted.popitem(last=False)
        return True


def _on_boundary(session_id: str = "", platform: str = "", reason: str = "",
                 old_session_id: str = "", **_ignored) -> None:
    session_id = old_session_id or session_id   # reset reports the NEW id
    if not session_id or not _claim_session(session_id):
        return
    threading.Thread(
        target=_run_extraction, args=(session_id,), daemon=False
    ).start()


def register(ctx):
    ctx.register_hook("on_session_finalize", _on_boundary)
    ctx.register_hook("on_session_reset", _on_boundary)
```

`extract.md` holds the extraction prompt — the JSON-returning template in [`claude-code.md`](claude-code.md#session-end-extraction-recommended) works as-is.

Spawn a thread rather than extracting inline: finalize hooks run on the gateway event loop, and a synchronous model call stalls `/new` and session teardown for its full duration. Use `daemon=False` so the work survives process shutdown.

## The two traps

Both cost real debugging time, and neither raises an error.

**1. `/new` fires both hooks.** A reset runs the finalize leg (`gateway/slash_commands.py`, `reason="new_session"`) and then the reset leg. Without `_claim_session` above, the same conversation is extracted twice and billed twice.

**2. `on_session_reset` reports the NEW session's id.** It passes `session_id` = the freshly created session and puts the conversation that just ended in `old_session_id`. Extracting `session_id` there reads an empty transcript and silently writes nothing — the failure looks like "the extractor stopped working," with no error. Hence `old_session_id or session_id`.

## When memory actually lands

- `/new` or `/reset` — immediately.
- Otherwise — at idle expiry, governed by `session_reset.idle_minutes` in `config.yaml`.

The gateway's expiry watcher wakes every 300 seconds, but that is only the **poll cadence**. It finalizes a session only once `entry.updated_at + idle_minutes` has passed (`gateway/session.py`), so with the default `idle_minutes: 4320` it looks 288 times a day and finds nothing for three days. Lowering `idle_minutes` to get faster memory also shortens conversation lifetime and drops context — they are the same knob. If you want extraction minutes after you stop talking without touching session lifetime, run an idle timer inside the plugin and keep `on_session_finalize` as the backstop.

Sessions whose reset policy is `mode: none` never expire, so they never finalize. On those, `/new` is the only boundary that triggers extraction.

## Step 5: Enable and verify

A Hermes plugin needs **both** halves, or it loads nothing and says nothing:

1. the plugin directory present in `<profile>/plugins/` (a symlink into `~/.hermes/plugins/` is fine), and
2. an entry in `plugins.enabled` in that profile's `config.yaml`:

```yaml
plugins:
  enabled:
    - memory-session-end
```

Either alone is silent. Verify against the running loader rather than by reading config:

```bash
HERMES_HOME=~/.hermes/profiles/<name> hermes plugins list
```

To confirm which hook a plugin actually landed on — `has_hook()` returns true if *any* plugin registered it, so it can't tell you the owner:

```python
from hermes_cli import plugins as P
mgr = P._delivery_manager()
P.invoke_hook("on_session_finalize", session_id="")   # force lazy discovery
for h in ("on_session_end", "on_session_finalize", "on_session_reset"):
    print(h, [getattr(f, "__module__", "?") for f in mgr.iter_hook_callbacks(h)])
```

Run it with the venv Hermes uses (`~/.hermes/hermes-agent/.venv/bin/python`); the system python is older and fails on the core's type syntax.

Plugins are loaded at gateway boot, so a hook change is not live until the gateway restarts.

## Worker profiles

If you run separate profiles for delegated workers (a kanban board, subagent lanes), think before enabling extraction in them. Their conversations are task execution, not context about you, and their durable output usually already lives in the ticket. Enabling it there pays for one model call per lane per task and tends to produce `MEMORY.md` files that stay empty while episode files pile up unread.

Keep extraction on the profiles you personally talk to.
