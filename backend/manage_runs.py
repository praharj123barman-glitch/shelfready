"""Housekeeping for stored reviews (backend/runs).

    python -m manage_runs stats                 how many runs, and real disk use
    python -m manage_runs share                 store identical files once (lossless, see runs.py)
    python -m manage_runs prune --keep 50       list the runs that would be deleted (dry run)
    python -m manage_runs prune --keep 50 --yes delete all but the newest 50 runs, then unused shared files

Waivers and reviewer notes live in runs/feedback.json and are never touched;
neither are the AI answer cache (runs/ai_cache) or the eval workspace.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import runs


def run_folders() -> list[Path]:
    """Review folders, newest first (only finished runs: they have a result)."""
    folders = [p for p in runs.RUNS_DIR.iterdir()
               if p.is_dir() and p.name.isalnum() and (p / "result.json").exists() and (p / "inputs.json").exists()]
    # inputs.json is written when the run is saved and is never shared, so its time is the run's own
    return sorted(folders, key=lambda p: ((p / "inputs.json").stat().st_mtime, p.name), reverse=True)


def disk_use(root: Path) -> tuple[int, int]:
    """(bytes as listed, bytes actually on disk): hard-linked files count once on disk."""
    listed, seen, actual = 0, set(), 0
    for path in root.rglob("*"):
        if path.is_file():
            stat = path.stat()
            listed += stat.st_size
            if (stat.st_dev, stat.st_ino) not in seen:
                seen.add((stat.st_dev, stat.st_ino))
                actual += stat.st_size
    return listed, actual


def mb(n: int) -> str:
    return f"{n / 1024 / 1024:,.0f} MB"


def stats() -> None:
    listed, actual = disk_use(runs.RUNS_DIR)
    print(f"{len(run_folders())} runs; files total {mb(listed)}, on disk {mb(actual)}")


def share() -> None:
    saved = sum(runs.share_identical_files(folder) for folder in run_folders())
    print(f"shared identical files: {mb(saved)} freed")
    stats()


def prune(keep: int, confirmed: bool) -> None:
    old = run_folders()[keep:]
    if not confirmed:
        print(f"would delete {len(old)} of {len(old) + keep} runs (oldest first): "
              + ", ".join(p.name for p in old[:10]) + (" ..." if len(old) > 10 else ""))
        print("nothing deleted; add --yes to delete")
        return
    for folder in old:
        shutil.rmtree(folder)
    orphans = [b for b in runs.blobs_dir().glob("*") if b.is_file() and b.stat().st_nlink == 1]
    for blob in orphans:  # no run links to it any more
        blob.unlink()
    print(f"deleted {len(old)} runs and {len(orphans)} unused shared files")
    stats()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats")
    sub.add_parser("share")
    p = sub.add_parser("prune")
    p.add_argument("--keep", type=int, required=True, help="number of newest runs to keep")
    p.add_argument("--yes", action="store_true", help="really delete (otherwise only list)")
    args = parser.parse_args()
    if args.command == "stats":
        stats()
    elif args.command == "share":
        share()
    else:
        prune(args.keep, args.yes)


if __name__ == "__main__":
    main()
