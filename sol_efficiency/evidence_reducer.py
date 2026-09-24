"""Evidence-preserving reduction for archived observations."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .observation_pack import ObservationPack, ObservationRef

_DEFAULT_SIGNAL = re.compile(
    r"\b(error|errors|fail|failed|failure|exception|traceback|assert(?:ion(?:error)?)?|"
    r"blocked|warning|warn|passed|pass|success|successful)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EvidenceFinding:
    line_no: int
    text: str
    verified: bool

    def render(self) -> str:
        marker = "verified" if self.verified else "unverified"
        return f"L{self.line_no} [{marker}] {self.text}"


@dataclass(frozen=True)
class EvidenceDigest:
    observation: ObservationRef
    findings: tuple[EvidenceFinding, ...]
    omitted_line_count: int

    @property
    def verified(self) -> bool:
        return all(f.verified for f in self.findings)

    def compact_text(self) -> str:
        parts = [
            self.observation.compact_token(),
            f"signals={len(self.findings)} omitted_lines={self.omitted_line_count}",
        ]
        parts.extend(f.render() for f in self.findings)
        return "\n".join(parts)


class EvidenceReducer:
    """Archive raw evidence first, then emit only exact, verified signal lines."""

    def __init__(self, pack: ObservationPack, *, max_findings: int = 12) -> None:
        self.pack = pack
        self.max_findings = max(1, int(max_findings))

    def reduce(self, text: str, *, label: str = "") -> EvidenceDigest:
        ref = self.pack.archive(text, label=label)
        lines = text.splitlines()
        hits: list[EvidenceFinding] = []
        for line_no, line in enumerate(lines, start=1):
            if not _DEFAULT_SIGNAL.search(line):
                continue
            recalled = self.pack.recall(
                ref.handle, start_line=line_no, end_line=line_no
            )
            hits.append(
                EvidenceFinding(
                    line_no=line_no,
                    text=line,
                    verified=(recalled == line),
                )
            )
            if len(hits) >= self.max_findings:
                break

        if not hits and lines:
            candidates = list(range(1, min(3, len(lines)) + 1))
            if len(lines) > 3:
                candidates.extend(range(max(4, len(lines) - 1), len(lines) + 1))
            seen: set[int] = set()
            for line_no in candidates:
                if line_no in seen or len(hits) >= self.max_findings:
                    continue
                seen.add(line_no)
                line = lines[line_no - 1]
                recalled = self.pack.recall(
                    ref.handle, start_line=line_no, end_line=line_no
                )
                hits.append(
                    EvidenceFinding(
                        line_no=line_no,
                        text=line,
                        verified=(recalled == line),
                    )
                )

        return EvidenceDigest(
            observation=ref,
            findings=tuple(hits),
            omitted_line_count=max(0, len(lines) - len(hits)),
        )
