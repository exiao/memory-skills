#!/usr/bin/env python3
"""Two-pass semantic prune for .pending.md.

Proven pattern from May 2026 sessions. Run AFTER dedup-pending.py (which catches
exact duplicates). This catches semantic duplicates and cross-category overlap.

Usage: python3 /path/to/memory-gc/scripts/prune_pending.py

Expected reduction: 191->31 entries (84% removal) on typical daily pending files.

Key insight: project namespace sprawl is the #1 duplication source. A single
project often generates entries under several related namespaces, e.g.
proj:<name>, proj:<name>-wiki, proj:<name>-agent, proj:<name>/<subdir>,
proj:<name>-cli. The mega_topic function in Pass 2 collapses entries that
share a project-namespace root into one group.
"""

import hashlib
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

PENDING = Path.home() / ".hermes/episodes/.pending.md"
GC_LOG = PENDING.parent / ".gc.log"

if not PENDING.exists():
    print(f"Pending file {PENDING} does not exist; nothing to prune.")
    raise SystemExit(0)

lines = [l.strip() for l in PENDING.read_text().splitlines() if l.strip()]
print(f"Input: {len(lines)} entries")

# Parse entries
entries = []
for line in lines:
    m = re.match(r'^(memory|user)\t\[(\d{4}-\d{2}-\d{2})\]\[([^\]]+)\]\s*(.+)$', line, re.IGNORECASE)
    if m:
        entries.append({
            'target': m.group(1).lower(), 'date': m.group(2),
            'cat': m.group(3), 'content': m.group(4), 'raw': line
        })
    else:
        entries.append({'target': 'unknown', 'date': '', 'cat': 'unknown',
                        'content': line, 'raw': line})

# -- Pass 1: Category-based hard drops + intra-category topic dedup --

TASK_REVIEW_DAYS = 14
TMP_REVIEW_DAYS = 7
COMPLETED_TASK_PATTERNS = [
    re.compile(r'\b(completed|resolved|abandoned|cancelled|canceled)\b'),
    re.compile(r'\bno longer needed\b'),
    re.compile(
        r'\b(?:is|was|has been|have been|marked|mark as|mark)\s+'
        r'(?:complete|done|resolved|closed|merged|abandoned|cancelled|canceled)\b'
    ),
]

# Fact patterns that are transient operational data, not durable memory.
# These get re-extracted every session but have no lasting architectural value.
TRANSIENT_FACT_KEYWORDS = [
    # Ad campaign metrics (change daily)
    'meta ads daily run', 'ad set budget crept', 'spend cap at',
    # Disk / cleanup (one-off operational)
    'disk cleanup', 'photorec', 'testdisk', 'recovered/',
    # Token usage / billing snapshots
    'all-time token usage',
    # PR status snapshots (stale within hours)
    'ready to merge', 'review comments addressed',
    # Specific earnings data (ephemeral)
    'earnings: eps',
]

RULE_MINUTIAE_KEYWORDS = [
    'frontmatter parser', 'regex pattern', 'prisma', 'pydantic',
    'css var', 'test mock data', 'campaign-level spending',
    'special ad category', 'meta special ad', 'force re-push',
    'head sha stale', 'trigger ci', 'gh auth switch',
    'not-null constraint', 'migration', 'lint formatting',
]

# Generic coding rules that are common knowledge, not durable memory.
# These get re-extracted every session because they appear in code reviews
# and PR fixes, but they encode no project-specific convention.
GENERIC_CODING_KEYWORDS = [
    # Syntax / formatting
    'f-string', 'f_string', 'backslash', 'import line', 'line-length',
    'ruff format', "ruff's", 'eslint', 'compound statements',
    # Git basics
    'git stash pop', 'git stash apply', 'merge conflict', 'conflict marker',
    '<<<<<<', 'push commit', 'push after', 'always push commits',
    'must be staged', 'force re-push',
    # Security patterns (common knowledge)
    'xss', 'html_escape', 'innerhtml', 'textcontent', 'path traversal',
    'os.sep', 'symlinks', 'toctou', 'race condition',
    # Error handling patterns
    'bare except', 'silent exception', 'try/except', 'try/finally',
    'catch-all exception', 'logger.warning not logger.error',
    'explicit error handling', 'graceful fallback', 'graceful shutdown',
    'transient failures', '5xx responses', 'response.ok',
    'async error responses', 'async polling handlers',
    # Testing patterns
    'caplog fixture', 'pytest-xdist', 'get_or_create', 'update_or_create',
    'test fixtures', 'test assertions on nav',
    # Validation patterns
    'type validation', 'validate command prefix', 'type-check phone',
    'fuzzy string matching', 'substring containment', 'full phrase match',
    'datetime string parsing', 'fromisoformat',
    # API / HTTP patterns
    'fetch api resolves on 4xx', 'stale response guards',
    'batch operations returning counts', 'connection leak',
    'db connection', 'pool exhaustion',
    # General coding
    'cache key function', 'cache key functions', 'import and reuse',
    'stub dataclass', 'backward compat', 'must be wrapped', 'auto-wrap',
    'set -e', 'executable scripts', 'process-wide file descriptor',
    'concurrent file writes', 'global variable scope', 'iife wrapping',
    'importlib.reload', 'cross-test module',
    # CI / review patterns
    'github actions ci failures at', 'fine-grained pat',
    'claude code review workflows', 'claude code review lgtm',
    'codex code review flags', 'dismiss codex', 'dismiss reviews',
    'stale changes_requested',
    # Framework-specific (not project-specific)
    'sector snapshot validation', 'middleware validation',
    'identical constraints', 'mega-file splits', 'ordered exec',
    'stripincompletemath', 'remarkmath',
]

PROJECT_RULE_SCOPE_RE = re.compile(
    r'\b(?:proj:[\w./~:-]+|this project|this repo|this repository|'
    r'for project [\w./~-]+|for repo [\w./~-]+|for repository [\w./~-]+)\b'
)

USER_RULE_SCOPE_RE = re.compile(
    r'\b(?:user wants|user prefers|the user wants|the user prefers|'
    r'i want|i prefer|my tests|my repos?|my scripts?|my code)\b'
)


def _age_days(yyyy_mm_dd):
    try:
        entry_date = datetime.strptime(yyyy_mm_dd, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None
    return (date.today() - entry_date).days


def _drop_task(e):
    """Drop only tasks that are stale enough for review or clearly complete."""
    content_lower = e['content'].lower()
    if any(pattern.search(content_lower) for pattern in COMPLETED_TASK_PATTERNS):
        return True
    age = _age_days(e.get('date', ''))
    return age is not None and age > TASK_REVIEW_DAYS


def _drop_tmp(e):
    """Drop temporary entries only after their short review window expires."""
    age = _age_days(e.get('date', ''))
    return age is not None and age > TMP_REVIEW_DAYS


def _content_key(content, max_len=96):
    """Stable, readable content fingerprint for conservative dedupe keys."""
    normalized = ''.join(ch if ch.isalnum() else ' ' for ch in content.casefold())
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    if not normalized:
        digest = hashlib.sha1(content.encode('utf-8')).hexdigest()[:12]
        return f'raw:{digest}'
    digest = hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:12]
    return f"{normalized[:max_len]}:{digest}"


def _is_project_scoped_rule(content_lower):
    """True when a rule names a project/repo scope and should get manual triage."""
    return bool(PROJECT_RULE_SCOPE_RE.search(content_lower))


def _is_user_scoped_rule(content_lower):
    """True when a rule encodes a user's own coding preference."""
    return bool(USER_RULE_SCOPE_RE.search(content_lower))


kept = []
dropped_pass1 = 0
for e in entries:
    cat = e['cat'].lower()
    if cat == 'tmp' and _drop_tmp(e):
        dropped_pass1 += 1
        continue
    if cat == 'task' and _drop_task(e):
        dropped_pass1 += 1
        continue
    if cat == 'fact':
        content_lower = e['content'].lower()
        if any(kw in content_lower for kw in TRANSIENT_FACT_KEYWORDS):
            dropped_pass1 += 1
            continue
    if cat == 'rule':
        content_lower = e['content'].lower()
        project_scoped = _is_project_scoped_rule(content_lower)
        user_scoped = _is_user_scoped_rule(content_lower)
        if not (project_scoped or user_scoped) and any(kw in content_lower for kw in RULE_MINUTIAE_KEYWORDS):
            dropped_pass1 += 1
            continue
        if not (project_scoped or user_scoped) and any(kw in content_lower for kw in GENERIC_CODING_KEYWORDS):
            dropped_pass1 += 1
            continue
    kept.append(e)

print(f"Pass 1 hard drops: {len(kept)} kept, {dropped_pass1} dropped")


def topic_key(e):
    """Intra-category topic key. Keep longest entry per key."""
    content = e['content'].lower()
    cat = e['cat'].lower()
    target = e.get('target', 'unknown')

    if cat.startswith('proj:'):
        project = cat
        if 'knowledge' in content or 'wiki' in content or 'entity' in content:
            return f"{target}:{project}:knowledge:{_content_key(content)}"
        if 'proxy' in content or 'gateway' in content:
            return f"{target}:{project}:proxy:{_content_key(content)}"
        if 'roadmap' in content or 'phase' in content:
            return f"{target}:{project}:roadmap:{_content_key(content)}"
        if 'middleware' in content or 'validation' in content or 'gate' in content:
            return f"{target}:{project}:validation:{_content_key(content)}"
        if 'sentry' in content or 'write_todos' in content:
            return f"{target}:{project}:sentry:{_content_key(content)}"
        pr_match = re.search(r'pr\s*#?(\d+)', content)
        if pr_match:
            return f"{target}:{project}:pr{pr_match.group(1)}:{_content_key(content)}"
        if 'sandbox' in content or 'vps' in content:
            return f"{target}:{project}:sandbox:{_content_key(content)}"
        if 'dashboard' in content or 'business insights' in content:
            return f"{target}:{project}:dashboard:{_content_key(content)}"
        if 'auth' in content or 'bearer' in content or 'cookie' in content:
            return f"{target}:{project}:auth:{_content_key(content)}"
        if 'issue' in content and 'cluster' in content:
            return f"{target}:{project}:issues:{_content_key(content)}"
        if 'site' in content or 'design system' in content or 'unified' in content:
            return f"{target}:{project}:sites:{_content_key(content)}"
        return f"{target}:{project}:other:{_content_key(content)}"

    if cat == 'fact':
        return f'{target}:fact:{_content_key(content)}'

    if cat == 'rule':
        if 'memory' in content:
            return f'{target}:rule:memory:{_content_key(content)}'
        if 'git' in content and ('auth' in content or 'token' in content):
            return f'{target}:rule:git-auth:{_content_key(content)}'
        return f'{target}:rule:{_content_key(content)}'

    if cat == 'pref':
        if re.search(r'\b(?:ui|tool|tools)\b', content):
            return f'{target}:pref:ui-tool:{_content_key(content)}'
        return f'{target}:pref:{_content_key(content)}'

    if cat == 'meta':
        return f'{target}:meta:{_content_key(content)}'

    return f'{target}:{cat}:{_content_key(content)}'


topic_groups = defaultdict(list)
for e in kept:
    topic_groups[topic_key(e)].append(e)

after_pass1 = []
for key, group in topic_groups.items():
    group.sort(key=lambda x: len(x['content']), reverse=True)
    after_pass1.append(group[0])

print(f"Pass 1 topic dedup: {len(after_pass1)} entries")


# -- Pass 2: Cross-category mega-topic dedup --
# Collapses project namespace sprawl (the #1 duplication source) without
# hardcoding any specific project name. Entries under proj:<root>,
# proj:<root>-<suffix>, and proj:<root>/<subdir> all collapse to one group,
# sub-keyed by a detected topic word so distinct project facts still survive.
# Non-project facts keep content-derived keys; generic words like "auth" must
# not collapse unrelated durable facts before manual triage.

# Common sub-topic words seen across projects. Tune for your own workspace.
SUBTOPIC_WORDS = [
    'roadmap', 'phase', 'knowledge', 'wiki', 'entity', 'ingest',
    'auth', 'proxy', 'gateway', 'sandbox', 'deploy', 'launch',
    'dashboard', 'site', 'design system', 'validation', 'middleware',
    'issue', 'cluster', 'eval', 'pipeline', 'schema', 'migration',
    'market', 'events', 'health',
]


KNOWN_SPRAWL_SUFFIXES = {'agent', 'cli', 'site', 'wiki'}


def _strip_sprawl_suffix(name):
    root, sep, suffix = name.rpartition('-')
    if sep and suffix in KNOWN_SPRAWL_SUFFIXES:
        return root
    return name


def _ns_root(cat):
    """Reduce a proj: category to its namespace root.

    proj:foo-agent -> foo ; proj:foo/bar -> foo ; proj:foo-wiki -> foo.
    proj:/Users/me/repo-a and proj:./repo-a stay intact so explicit paths stay distinct.
    Hyphenated project names without a known sprawl suffix are preserved.
    """
    ns = cat.split(':', 1)[1] if ':' in cat else cat
    if ns.startswith(('/', './', '../', '~/')) or ns in {'.', '..', '~'}:
        path = re.sub(r'/+', '/', ns).rstrip('/') or ns
        parent, sep, leaf = path.rpartition('/')
        if not sep:
            return _strip_sprawl_suffix(path)
        leaf = _strip_sprawl_suffix(leaf)
        return f'{parent}/{leaf}' if parent else f'/{leaf}'
    ns = ns.split('/', 1)[0]
    return _strip_sprawl_suffix(ns)


def mega_topic(e):
    """Cross-category topic key that collapses namespace sprawl generically."""
    c = e['content'].lower()
    cat = e['cat'].lower()
    target = e.get('target', 'unknown')

    if cat.startswith('proj:'):
        root = _ns_root(cat)
        for w in SUBTOPIC_WORDS:
            if w in c:
                return f'{target}:{root}:{w.replace(" ", "-")}:{_content_key(c)}'
        return f'{target}:{root}:other:{_content_key(c)}'

    return f'unique:{target}:{cat}:{_content_key(c)}'


groups = defaultdict(list)
for e in after_pass1:
    groups[mega_topic(e)].append(e)

final = []
for topic, group in groups.items():
    group.sort(key=lambda x: len(x['content']), reverse=True)
    final.append(group[0])
    if len(group) > 1:
        print(f"  Collapsed {len(group)} entries for '{topic}'")

print(f"\nFinal: {len(final)} entries")

# Preserve original order
idx_map = {id(e): i for i, e in enumerate(entries)}
final.sort(key=lambda e: idx_map.get(id(e), 999))


def _archive_removed(removed):
    """Append every pruned row to the recoverable GC log before rewriting pending."""
    if not removed:
        return
    GC_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(GC_LOG, 'a') as log:
        log.write(f"\n# prune_pending {date.today().isoformat()} removed {len(removed)} entries\n")
        for e in removed:
            log.write(e['raw'] + '\n')


final_ids = {id(e) for e in final}
_archive_removed([e for e in entries if id(e) not in final_ids])

with open(PENDING, 'w') as f:
    for e in final:
        f.write(e['raw'] + '\n')

print(f"Written to {PENDING}")
