"""ACK and RESULT composers.

Both composers take a structured set of facts and produce the exact body the
watcher posts back to the source issue. They are deliberately separated
from the protocol transport (``gh_client.post_comment``) so the format can
be unit-tested without any I/O.
"""
from __future__ import annotations

from dataclasses import dataclass


ACK_MARKER = "[HERMES_ACK:v1]"
RESULT_MARKER = "[HERMES_RESULT:v1]"


@dataclass(frozen=True)
class AckFacts:
    directive_id: str
    source_comment_id: int
    execution_id: str
    head_before: str | None


def format_ack(facts: AckFacts) -> str:
    """Compose the ACK body the watcher posts after a successful claim."""
    head = facts.head_before or "NONE"
    return (
        f"{ACK_MARKER}\n"
        f"DIRECTIVE_ID = {facts.directive_id}\n"
        f"SOURCE_COMMENT_ID = {facts.source_comment_id}\n"
        f"EXECUTION_ID = {facts.execution_id}\n"
        f"STATUS = CLAIMED\n"
        f"HEAD_BEFORE = {head}\n"
    )


@dataclass(frozen=True)
class ResultFacts:
    directive_id: str
    execution_id: str
    source_comment_id: int
    status: str  # one of READY_FOR_ASTRA_REAUDIT, BLOCKED_EXTERNAL_REAL,
                 # SCIENTIFIC_DECISION_REQUIRED, HUMAN_GO_REAL_REQUIRED
    head_after: str | None
    tests: str
    evidence: str  # path or URL — kept opaque, but echoed verbatim


def format_result(facts: ResultFacts) -> str:
    """Compose the RESULT body the watcher posts on completion."""
    head = facts.head_after or "NONE"
    return (
        f"{RESULT_MARKER}\n"
        f"DIRECTIVE_ID = {facts.directive_id}\n"
        f"EXECUTION_ID = {facts.execution_id}\n"
        f"SOURCE_COMMENT_ID = {facts.source_comment_id}\n"
        f"STATUS = {facts.status}\n"
        f"HEAD_AFTER = {head}\n"
        f"TESTS = {facts.tests}\n"
        f"EVIDENCE = {facts.evidence}\n"
    )


def parse_result_status(body: str) -> str | None:
    """Convenience: extract STATUS from a HERMES_RESULT body, or None.

    Used by tests and by the recovery code that scans the issue thread to
    cross-check the watcher's own state.
    """
    if RESULT_MARKER not in body:
        return None
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("STATUS"):
            return line.split("=", 1)[1].strip()
    return None
