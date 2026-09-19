"""Tests for the evidence + status helpers."""
from __future__ import annotations

from directive_watcher.evidence import (
    evidence_visual_root,
    prepare_execution_dir,
    read_manifest,
)
from directive_watcher.status import WatcherStatus, read_status, write_status


def test_prepare_execution_dir_creates_canonical_layout(tmp_path):
    p = prepare_execution_dir(tmp_path, "exec-1", "d-1", 100)
    assert (p / "before").is_dir()
    assert (p / "after").is_dir()
    assert (p / "manifest.json").is_file()
    assert (p / "notes.md").is_file()
    manifest = read_manifest(tmp_path, "exec-1")
    assert manifest is not None
    assert manifest["execution_id"] == "exec-1"
    assert manifest["directive_id"] == "d-1"
    assert manifest["source_comment_id"] == 100
    # before/after are absolute paths inside the temp dir.
    assert manifest["before_dir"].endswith("before")
    assert manifest["after_dir"].endswith("after")


def test_prepare_execution_dir_is_idempotent(tmp_path):
    p1 = prepare_execution_dir(tmp_path, "exec-1", "d-1", 100)
    p2 = prepare_execution_dir(tmp_path, "exec-1", "d-1", 100)
    assert p1 == p2
    # Notes file still present (we don't overwrite if it already exists).
    assert (p1 / "notes.md").is_file()


def test_evidence_root_layout(tmp_path):
    p = evidence_visual_root(tmp_path)
    assert str(p).replace("\\", "/").endswith("evidence/visual")


def test_status_roundtrip(tmp_path):
    s = WatcherStatus(
        watcher_status="healthy",
        last_poll_at=int(time.time_ns() // 1_000_000_000),
        last_seen_comment_id=42,
        queue_depth=0,
        last_result="d-1",
        last_result_status="READY_FOR_ASTRA_REAUDIT",
    )
    path = tmp_path / "status.json"
    write_status(path, s)
    loaded = read_status(path)
    assert loaded.watcher_status == "healthy"
    assert loaded.last_seen_comment_id == 42
    assert loaded.last_result == "d-1"


def test_status_unknown_when_file_missing(tmp_path):
    s = read_status(tmp_path / "nope.json")
    assert s.watcher_status == "unknown"


import time  # noqa: E402  (used above for the roundtrip test)
