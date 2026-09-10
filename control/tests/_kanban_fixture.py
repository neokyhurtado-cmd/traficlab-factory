"""Kanban fixture helper for the smoke suite.

The smoke checks for Mission goal / KPI strip / code tiles / open PRs
all require the kanban.db to have a populated state. Without seeding,
those checks fail with "Cargando meta activa..." or "0 tiles" when the
real kanban has no active goal or no open PRs.

Strategy (replacement for the old snapshot+restore in-place design):
  1. Copy SMOKE_KANBAN_FIXTURE into a fresh temporary kanban.db.
  2. Caller passes that temp path to the BFF via CONTROL_KANBAN_DB.
  3. After the smoke run, the temp db is unlinked.

  The real kanban.db is NEVER touched. No in-place snapshot/restore.
  No race with other Hermes/Control processes reading the real kanban.

Usage:

  # Standalone CLI:
  $ python _kanban_fixture.py /path/to/fixture.db /path/to/temp_bff_dir /tmp/bff_args.txt
      Creates /tmp/temp_bff_dir/kanban.db from fixture, writes the path
      to the args file so a wrapper script can pick it up.

  # Programmatic:
  from _kanban_fixture import stage_fixture_kanban
  temp_kanban = stage_fixture_kanban("/path/to/fixture.db")  # returns Path
  try:
      # ... run BFF with CONTROL_KANBAN_DB=<temp_kanban> and the smoke ...
  finally:
      temp_kanban.unlink(missing_ok=True)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path


def stage_fixture_kanban(fixture: str | os.PathLike, dest_dir: str | os.PathLike | None = None) -> Path:
    """Copy SMOKE_KANBAN_FIXTURE (or the path argument) into a fresh temp
    kanban.db. Returns the path to the staged file. Caller is responsible
    for unlinking it.

    Args:
      fixture: path to the source fixture kanban.db.
      dest_dir: optional directory in which to create the temp file.
                If omitted, uses tempfile.mkdtemp() and the caller still
                owns the unlink.
    """
    fixture_path = Path(fixture).resolve()
    if not fixture_path.exists():
        raise FileNotFoundError(f"kanban fixture not found: {fixture_path}")

    if dest_dir is None:
        dest_dir = Path(tempfile.mkdtemp(prefix="smoke_kanban_"))
    else:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

    staged = dest_dir / "kanban.db"
    shutil.copy2(fixture_path, staged)
    return staged


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage a kanban fixture into a fresh temp DB; "
                    "do NOT overwrite the real kanban. The temp path is "
                    "printed to stdout. Pass it to the BFF via "
                    "CONTROL_KANBAN_DB=<path>.",
    )
    parser.add_argument("--fixture", required=True,
                        help="Path to the kanban.db fixture to copy.")
    parser.add_argument("--out-dir", default=None,
                        help="Directory to stage the temp kanban into "
                             "(default: a fresh tempfile.mkdtemp()).")
    args = parser.parse_args()

    if args.out_dir:
        dest_dir = Path(args.out_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        staged = stage_fixture_kanban(args.fixture, dest_dir=dest_dir)
    else:
        staged = stage_fixture_kanban(args.fixture)

    sys.stdout.write(str(staged) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
