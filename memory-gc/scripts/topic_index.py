#!/usr/bin/env python3
"""Maintain the topic-file tier (Tier-2 raw-text store) for memory-gc.

Two responsibilities, both safe to run unattended:

1. ``rebuild-index`` — regenerate ``memories/INDEX.md`` from the topic files
   actually on disk, preserving existing one-line descriptions.
2. ``archive-candidates`` — list topic files that are stale (> N days since
   modified) and unreferenced by MEMORY.md hot pointers or human-curated INDEX
   rows. Generated ``(no description)`` INDEX inventory rows do not protect a
   stale file. With ``--apply`` it MOVES candidates into ``memories/archive/``.
   It never deletes and never touches a referenced file.

The logic lives here (not as inline heredocs in SKILL.md) so it is testable and
reusable. ``test_topic_index.py`` exercises every branch in a tempdir.

Usage:
    python3 topic_index.py rebuild-index
    python3 topic_index.py archive-candidates            # dry run, prints list
    python3 topic_index.py archive-candidates --apply     # actually archive
    # tests pass --mem-dir to point at a sandbox:
    python3 topic_index.py rebuild-index --mem-dir /tmp/sandbox/memories
"""
from __future__ import annotations

import argparse
import datetime
import shutil
import time
from pathlib import Path

# Files that are never topic files (core memory + the index itself).
CORE = {"MEMORY.md", "USER.md", "MEM_ARCH.md", "INDEX.md"}
STALE_DAYS = 120

INDEX_HEADER = (
    "# Topic File Index\n\n"
    "Auto-maintained by memory-gc. Tier-2 raw-text store registry.\n"
    "MEMORY.md keeps only a few hot `[meta] Topic file:` pointers; this INDEX is authoritative.\n"
    "recall reads this file first to route to the right topic file instead of guessing names.\n"
    "Core files (MEMORY, USER, MEM_ARCH, INDEX) are intentionally excluded.\n\n"
    "| File | Description | Updated | Size |\n|------|-------------|---------|------|\n"
)


def default_mem_dir() -> Path:
    return Path.home() / ".hermes" / "memories"


def topic_files(mem: Path) -> list[str]:
    """Sorted topic-file names in ``mem`` (excludes core, *.bak, dotfiles)."""
    return sorted(
        n
        for n in (p.name for p in mem.glob("*.md"))
        if n not in CORE and not n.endswith(".bak") and not n.startswith(".")
    )


def parse_existing_descriptions(idx: Path) -> dict[str, str]:
    """Pull ``filename -> description`` from an existing INDEX.md table."""
    out: dict[str, str] = {}
    if not idx.exists():
        return out
    for line in idx.read_text(encoding="utf-8").splitlines():
        if line.startswith("| ") and ".md " in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and cells[0].endswith(".md"):
                out[cells[0]] = cells[1]
    return out


def curated_index_references(idx: Path) -> set[str]:
    """Topic files with human-curated INDEX descriptions.

    ``rebuild_index`` inventories every topic file on disk and assigns new files
    ``(no description)``. Those generated inventory rows should not, by
    themselves, protect stale files from archival; otherwise a rebuild right
    before ``archive-candidates`` makes every current file look referenced.
    """
    return {
        name
        for name, desc in parse_existing_descriptions(idx).items()
        if desc and desc != "(no description)"
    }


def _size_label(nbytes: int) -> str:
    return f"{nbytes // 1024}KB" if nbytes >= 1024 else f"{nbytes}B"


def rebuild_index(mem: Path) -> int:
    """Rewrite INDEX.md from disk, preserving known descriptions. Returns row count."""
    mem.mkdir(parents=True, exist_ok=True)
    idx = mem / "INDEX.md"
    existing = parse_existing_descriptions(idx)
    rows = []
    for name in topic_files(mem):
        st = (mem / name).stat()
        updated = datetime.date.fromtimestamp(st.st_mtime).isoformat()
        desc = existing.get(name, "(no description)")
        rows.append(f"| {name} | {desc} | {updated} | {_size_label(st.st_size)} |")
    idx.write_text(INDEX_HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return len(rows)


def archive_candidates(mem: Path, stale_days: int = STALE_DAYS) -> list[str]:
    """Topic files that are stale AND unreferenced. Pure query, no side effects."""
    memory_path = mem / "MEMORY.md"
    memory_text = memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""
    indexed = curated_index_references(mem / "INDEX.md")
    now = time.time()
    out = []
    for name in topic_files(mem):
        p = mem / name
        referenced = f"Topic file: {name}" in memory_text or name in indexed
        stale = (now - p.stat().st_mtime) > stale_days * 86400
        if stale and not referenced:
            out.append(name)
    return out


def apply_archive(mem: Path, names: list[str]) -> list[str]:
    """Move named files into ``memories/archive/``. Returns the names moved."""
    if not names:
        return []
    arch = mem / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in names:
        src = mem / name
        if not src.exists():
            continue
        dest = arch / name
        if dest.exists():  # never clobber an earlier archived version
            dest = arch / f"{src.stem}-{int(time.time())}{src.suffix}"
        shutil.move(str(src), str(dest))
        moved.append(name)
    return moved


def main(argv=None):
    ap = argparse.ArgumentParser(description="Maintain the topic-file tier.")
    ap.add_argument("command", choices=["rebuild-index", "archive-candidates"])
    ap.add_argument("--mem-dir", type=Path, default=None,
                    help="memories dir (default ~/.hermes/memories)")
    ap.add_argument("--apply", action="store_true",
                    help="for archive-candidates: actually move files")
    ap.add_argument("--stale-days", type=int, default=STALE_DAYS)
    args = ap.parse_args(argv)
    mem = args.mem_dir or default_mem_dir()

    if args.command == "rebuild-index":
        n = rebuild_index(mem)
        print(f"INDEX rebuilt: {n} topic files")
        return 0

    cands = archive_candidates(mem, args.stale_days)
    print(f"archive candidates (stale >{args.stale_days}d AND unreferenced):",
          cands or "none")
    if args.apply and cands:
        moved = apply_archive(mem, cands)
        rebuild_index(mem)  # keep INDEX consistent after a move
        print(f"archived {len(moved)}: {moved}")
        print("Remember: drop any orphan [meta] pointer for these via the memory tool.")
    elif cands:
        print("dry run — pass --apply to move them. Sanity-check the list first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
