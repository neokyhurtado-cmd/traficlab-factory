"""Kanban fixture helper for the smoke suite.

The smoke checks for Mission goal / KPI strip / code tiles / open PRs
all require the kanban.db to have a populated state. Without seeding,
those checks fail with "Cargando meta activa..." or "0 tiles" when the
real kanban has no active goal or no open PRs.

This helper:
  1. Snapshots the real kanban.db (if it exists).
  2. Copies a fixture kanban.db (passed via SMOKE_KANBAN_FIXTURE) over it.
  3. Yields control back via a context manager.
  4. Restores the original kanban.db on exit.

Usage:
  from contextlib import contextmanager

  @contextmanager
  def kanban_fixture():
      fixture = os.environ.get("SMOKE_KANBAN_FIXTURE")
      real_kanban = real_kanban_path()  # same logic as BFF's sources.py
      if not fixture or not os.path.exists(fixture):
          yield  # no-op
          return
      backup = real_kanban + ".smoke-backup"
      if os.path.exists(real_kanban):
          shutil.copy2(real_kanban, backup)
      else:
          backup_unused = True
      shutil.copy2(fixture, real_kanban)
      try:
          yield
      finally:
          if os.path.exists(backup):
              shutil.copy2(backup, real_kanban)
              os.unlink(backup)
          elif os.path.exists(real_kanban):
              os.unlink(real_kanban)
"""
from contextlib import contextmanager
from pathlib import Path
import os
import shutil


def real_kanban_path() -> Path:
    env = os.environ.get("CONTROL_KANBAN_DB")
    if env:
        return Path(env)
    return (Path.home() / "AppData" / "Local" / "hermes"
            / "kanban" / "boards" / "traficlabpro" / "kanban.db")


@contextmanager
def kanban_fixture():
    """Install the SMOKE_KANBAN_FIXTURE over the real kanban DB during
    the smoke run, then restore. No-op if SMOKE_KANBAN_FIXTURE is unset
    or if the fixture file doesn't exist."""
    fixture = os.environ.get("SMOKE_KANBAN_FIXTURE")
    real = real_kanban_path()
    if not fixture or not os.path.exists(fixture):
        yield
        return
    backup = real.with_suffix(real.suffix + ".smoke-backup")
    real_existed = real.exists()
    if real_existed:
        shutil.copy2(real, backup)
    shutil.copy2(fixture, real)
    try:
        yield
    finally:
        if real_existed and backup.exists():
            shutil.copy2(backup, real)
            backup.unlink()
        elif not real_existed and real.exists():
            real.unlink()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Seed kanban from fixture, run command, restore.")
    parser.add_argument("--fixture", required=True, help="Path to kanban.db fixture")
    parser.add_argument("--real", default=None, help="Override real kanban path")
    parser.add_argument("cmd", nargs="+", help="Command to run with kanban installed")
    args = parser.parse_args()
    if args.real:
        os.environ["CONTROL_KANBAN_DB"] = args.real
    os.environ["SMOKE_KANBAN_FIXTURE"] = args.fixture
    import subprocess
    with kanban_fixture():
        result = subprocess.run(args.cmd)
        sys.exit(result.returncode)
