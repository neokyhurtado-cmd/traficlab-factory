"""Parser for the ``[ASTRA_DIRECTIVE:v1]`` envelope.

A directive is the structured block of ``KEY = VALUE`` lines that follows
the exact marker ``[ASTRA_DIRECTIVE:v1]`` in a GitHub comment. Anything
outside the block is free-form prose and is discarded by the parser.

The parser is fail-closed: any malformed envelope raises ``DirectiveParseError``.
A comment without the marker simply returns ``None`` (information-only).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

MARKER = "[ASTRA_DIRECTIVE:v1]"

# Actions the watcher knows how to dispatch. Anything else is a parse error
# so we never silently invent a behaviour for an unknown verb.
VALID_ACTIONS = frozenset({
    "CONTINUE",
    "REAUDIT_FIX",
    "INVESTIGATE",
    "TEST",
    "BUILD",
    "OPEN_PR",
})

_REQUIRED_KEYS = (
    "ACTION",
    "REPOSITORY",
    "ISSUE",
    "TARGET_BRANCH",
    "EXPECTED_HEAD",
    "SCOPE",
    "AUTO_NEXT_SAFE_GATE",
    "REQUIRES_HUMAN_GO_REAL",
    "DIRECTIVE_ID",
)

_TRUE_TOKENS = frozenset({"YES", "TRUE", "1"})
_FALSE_TOKENS = frozenset({"NO", "FALSE", "0"})


@dataclass(frozen=True)
class Directive:
    """Immutable parsed directive record.

    The watcher treats ``directive_id`` as the durable idempotency key:
    two comments with the same ``directive_id`` are the same directive.
    """

    action: str
    repository: str
    issue: int
    target_branch: str
    expected_head: str
    scope: str
    auto_next_safe_gate: bool
    requires_human_go_real: bool
    directive_id: str


class DirectiveParseError(ValueError):
    """Raised when an envelope is malformed. The watcher treats this as a
    hard failure: it must NOT execute anything from the comment."""


def _coerce_bool(token: str, field: str) -> bool:
    upper = token.strip().upper()
    if upper in _TRUE_TOKENS:
        return True
    if upper in _FALSE_TOKENS:
        return False
    raise DirectiveParseError(
        f"{field} must be YES/NO/true/false/1/0, got {token!r}"
    )


def _extract_envelope(body: str) -> Optional[str]:
    """Return the substring that starts at the marker and contains the
    envelope, or ``None`` if the marker is absent.

    The envelope runs from the marker line until the first line that does NOT
    look like ``KEY = VALUE`` (the prose / trailing section of the comment).
    Blank lines and free-form prose terminate the block.
    """
    idx = body.find(MARKER)
    if idx < 0:
        return None
    after = body[idx + len(MARKER):]
    # Skip any leading blank lines between the marker and the first key.
    started = False
    lines = []
    for line in after.splitlines():
        stripped = line.strip()
        if not started:
            if not stripped:
                continue
            started = True
        if not stripped:
            # Blank line: end of the envelope.
            break
        if "=" not in stripped:
            # Prose line (e.g. "Thanks!"): end of the envelope.
            break
        lines.append(line)
    if not started:
        return None
    return "\n".join(lines)


def _parse_envelope(envelope: str) -> dict[str, str]:
    """Parse `KEY = VALUE` lines into a dict. Tolerates surrounding whitespace.

    Comments (`# ...`) are stripped from the end of lines so the issue author
    can annotate values without breaking the parser. Duplicate keys raise.
    """
    out: dict[str, str] = {}
    for raw in envelope.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            raise DirectiveParseError(
                f"malformed line (expected KEY = VALUE): {raw!r}"
            )
        key, _, value = line.partition("=")
        key = key.strip().upper()
        # Strip trailing inline comment.
        if "#" in value:
            value = value.split("#", 1)[0]
        value = value.strip()
        if key in out:
            raise DirectiveParseError(f"duplicate key {key}")
        out[key] = value
    return out


def parse_directive(body: str) -> Optional[Directive]:
    """Parse a comment body into a ``Directive``.

    Returns ``None`` if the marker is absent (information-only comment).
    Raises ``DirectiveParseError`` if the marker is present but the
    envelope is malformed.
    """
    if not body:
        return None
    envelope = _extract_envelope(body)
    if envelope is None:
        return None
    fields = _parse_envelope(envelope)

    missing = [k for k in _REQUIRED_KEYS if k not in fields or not fields[k]]
    if missing:
        raise DirectiveParseError(
            f"missing required directive fields: {', '.join(missing)}"
        )

    action = fields["ACTION"].strip().upper()
    if action not in VALID_ACTIONS:
        raise DirectiveParseError(
            f"unknown ACTION {action!r}; valid: {sorted(VALID_ACTIONS)}"
        )

    try:
        issue = int(fields["ISSUE"].strip())
    except ValueError as e:
        raise DirectiveParseError(
            f"ISSUE must be an integer, got {fields['ISSUE']!r}"
        ) from e

    return Directive(
        action=action,
        repository=fields["REPOSITORY"].strip(),
        issue=issue,
        target_branch=fields["TARGET_BRANCH"].strip(),
        expected_head=fields["EXPECTED_HEAD"].strip(),
        scope=fields["SCOPE"].strip(),
        auto_next_safe_gate=_coerce_bool(fields["AUTO_NEXT_SAFE_GATE"], "AUTO_NEXT_SAFE_GATE"),
        requires_human_go_real=_coerce_bool(fields["REQUIRES_HUMAN_GO_REAL"], "REQUIRES_HUMAN_GO_REAL"),
        directive_id=fields["DIRECTIVE_ID"].strip(),
    )
