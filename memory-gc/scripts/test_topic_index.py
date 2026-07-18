#!/usr/bin/env python3
"""Tests for topic_index.py — the memory-gc topic-file maintenance script.

All work happens in a tempdir; the real ~/.hermes is never touched.
Run: python3 test_topic_index.py
"""
import importlib.util
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("topic_index", HERE / "topic_index.py")
ti = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ti)

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def make_sandbox():
    mem = Path(tempfile.mkdtemp(prefix="ti-test-")) / "memories"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("# mem\n", encoding="utf-8")
    return mem


def write(mem, name, body="# x\nbody\n", mtime=None):
    p = mem / name
    p.write_text(body, encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(p, (mtime, mtime))
    return p


def run():
    today = "2026-05-31"

    print("\n[1] rebuild-index lists topic files, excludes core")
    mem = make_sandbox()
    write(mem, "alpha.md")
    write(mem, "beta-notes.md")
    write(mem, "USER.md")          # core, excluded
    write(mem, "MEM_ARCH.md")      # core, excluded
    write(mem, "stale.bak")        # not .md
    n = ti.rebuild_index(mem)
    idx = (mem / "INDEX.md").read_text(encoding="utf-8")
    check("returns 2 rows", n == 2)
    check("alpha listed", "| alpha.md |" in idx)
    check("beta listed", "| beta-notes.md |" in idx)
    check("USER.md excluded", "| USER.md |" not in idx)
    check("MEM_ARCH excluded", "| MEM_ARCH.md |" not in idx)
    check("INDEX self excluded", "| INDEX.md |" not in idx)
    check("header present", idx.startswith("# Topic File Index"))
    check("new files get default desc", "(no description)" in idx)

    print("\n[2] rebuild preserves existing descriptions")
    # seed a description, add a new file, rebuild
    idx_path = mem / "INDEX.md"
    txt = idx_path.read_text(encoding="utf-8").replace(
        "| alpha.md | (no description) |", "| alpha.md | my alpha desc |")
    idx_path.write_text(txt, encoding="utf-8")
    write(mem, "gamma.md")
    ti.rebuild_index(mem)
    idx2 = idx_path.read_text(encoding="utf-8")
    check("existing desc preserved", "| alpha.md | my alpha desc |" in idx2)
    check("new file gets default", "| gamma.md | (no description) |" in idx2)

    print("\n[3] archive-candidates: stale AND unreferenced only")
    mem = make_sandbox()
    old = time.time() - 200 * 86400
    new = time.time()
    write(mem, "stale-unref.md", mtime=old)        # stale + unref -> candidate
    write(mem, "stale-ref.md", mtime=old)          # stale but referenced -> keep
    write(mem, "fresh-unref.md", mtime=new)        # unref but fresh -> keep
    write(mem, "fresh-ref.md", mtime=new)          # fresh + ref -> keep
    (mem / "MEMORY.md").write_text(
        "# mem\n[2026-01-01][meta] Topic file: stale-ref.md = x\n"
        "[2026-01-01][meta] Topic file: fresh-ref.md = y\n", encoding="utf-8")
    cands = ti.archive_candidates(mem)
    check("only stale-unref is a candidate", cands == ["stale-unref.md"])
    check("referenced stale file kept", "stale-ref.md" not in cands)
    check("fresh unref file kept", "fresh-unref.md" not in cands)

    print("\n[4] archive-candidates is a pure query (no files moved)")
    check("stale-unref still on disk after query", (mem / "stale-unref.md").exists())
    check("no archive dir created by query", not (mem / "archive").exists())

    print("\n[5] apply_archive moves only candidates, never deletes")
    moved = ti.apply_archive(mem, cands)
    check("returns moved list", moved == ["stale-unref.md"])
    check("file gone from memories", not (mem / "stale-unref.md").exists())
    check("file now in archive", (mem / "archive" / "stale-unref.md").exists())
    check("referenced file untouched", (mem / "stale-ref.md").exists())
    check("MEMORY.md untouched", (mem / "MEMORY.md").read_text(encoding="utf-8").startswith("# mem"))

    print("\n[6] apply_archive never clobbers an existing archived file")
    mem = make_sandbox()
    write(mem, "dup.md", body="# new content\n", mtime=time.time() - 200 * 86400)
    (mem / "archive").mkdir()
    (mem / "archive" / "dup.md").write_text("# OLD ARCHIVED\n", encoding="utf-8")
    ti.apply_archive(mem, ["dup.md"])
    check("old archived copy preserved",
          (mem / "archive" / "dup.md").read_text(encoding="utf-8") == "# OLD ARCHIVED\n")
    others = [p for p in (mem / "archive").glob("dup-*.md")]
    check("new copy archived under suffixed name", len(others) == 1)

    print("\n[7] empty / no-candidate cases are safe")
    mem = make_sandbox()
    check("no candidates on empty dir", ti.archive_candidates(mem) == [])
    check("apply_archive([]) is a noop", ti.apply_archive(mem, []) == [])
    check("rebuild on empty dir writes 0 rows", ti.rebuild_index(mem) == 0)

    print("\n[8] missing parent directories are created safely")
    missing_mem = Path(tempfile.mkdtemp(prefix="ti-test-missing-")) / "missing" / "memories"
    check("rebuild creates missing mem dir", ti.rebuild_index(missing_mem) == 0)
    check("INDEX exists in created mem dir", (missing_mem / "INDEX.md").exists())
    missing_archive_mem = Path(tempfile.mkdtemp(prefix="ti-test-archive-")) / "missing" / "memories"
    check("apply_archive tolerates missing parent mem dir", ti.apply_archive(missing_archive_mem, ["ghost.md"]) == [])
    check("archive dir created with parents", (missing_archive_mem / "archive").exists())

    print("\n[9] only curated INDEX rows protect stale files")
    mem = make_sandbox()
    old = time.time() - 200 * 86400
    write(mem, "indexed-only.md", mtime=old)
    (mem / "INDEX.md").write_text(
        ti.INDEX_HEADER + "| indexed-only.md | durable topic | 2026-01-01 | 1KB |\n",
        encoding="utf-8")
    check("stale curated INDEX-listed file is not an archive candidate",
          ti.archive_candidates(mem) == [])

    mem = make_sandbox()
    write(mem, "generated-only.md", mtime=old)
    ti.rebuild_index(mem)
    check("stale generated INDEX inventory remains an archive candidate",
          ti.archive_candidates(mem) == ["generated-only.md"])

    print("\n[10] CLI entrypoint works end to end")
    mem = make_sandbox()
    write(mem, "cli.md", mtime=time.time() - 200 * 86400)
    rc = ti.main(["rebuild-index", "--mem-dir", str(mem)])
    check("rebuild-index returns 0", rc == 0)
    check("cli.md indexed", "| cli.md |" in (mem / "INDEX.md").read_text(encoding="utf-8"))
    write(mem, "orphan.md", mtime=time.time() - 200 * 86400)
    rc = ti.main(["archive-candidates", "--mem-dir", str(mem), "--apply"])
    check("archive --apply returns 0", rc == 0)
    check("generated stale cli.md archived via CLI", (mem / "archive" / "cli.md").exists())
    check("unindexed orphan.md archived via CLI", (mem / "archive" / "orphan.md").exists())

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    return FAIL == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
