"""Durable observation packing with exact recall and integrity verification."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

_HANDLE_RE = re.compile(r"^obs://sha256/([0-9a-f]{64})$")


class ObservationIntegrityError(RuntimeError):
    """Raised when archived evidence no longer matches its recorded digest."""


@dataclass(frozen=True)
class ObservationRef:
    handle: str
    sha256: str
    path: str
    byte_count: int
    line_count: int
    head: tuple[str, ...]
    tail: tuple[str, ...]
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["head"] = list(self.head)
        out["tail"] = list(self.tail)
        return out

    def compact_token(self) -> str:
        return (
            f"{self.handle} bytes={self.byte_count} lines={self.line_count} "
            f"sha256={self.sha256}"
        )


class ObservationPack:
    """Content-addressed local archive for verbose tool/worker observations.

    The original bytes stay recoverable by handle. Repeated content is
    deduplicated naturally because the file path is derived from SHA-256.
    """

    def __init__(
        self,
        root: str | os.PathLike[str] = ".sol_artifacts/observations",
        *,
        threshold_bytes: int = 4096,
        preview_lines: int = 6,
    ) -> None:
        self.root = Path(root)
        self.threshold_bytes = int(threshold_bytes)
        self.preview_lines = max(1, int(preview_lines))
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _paths(self, sha256: str) -> tuple[Path, Path]:
        bucket = self.root / sha256[:2]
        return bucket / f"{sha256}.txt", bucket / f"{sha256}.json"

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass

    def archive(
        self,
        text: str,
        *,
        label: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> ObservationRef:
        if not isinstance(text, str):
            raise TypeError("ObservationPack only archives text observations")
        data = text.encode("utf-8")
        sha = self._digest(data)
        content_path, meta_path = self._paths(sha)
        if not content_path.exists():
            self._atomic_write(content_path, data)

        lines = text.splitlines()
        head = tuple(lines[: self.preview_lines])
        tail = tuple(lines[-self.preview_lines :]) if lines else tuple()
        ref = ObservationRef(
            handle=f"obs://sha256/{sha}",
            sha256=sha,
            path=str(content_path),
            byte_count=len(data),
            line_count=len(lines),
            head=head,
            tail=tail,
            label=label,
        )
        meta = {
            "schema": "OBSERVATION_PACK_V1",
            "created_at": int(time.time()),
            "observation": ref.to_dict(),
            "metadata": dict(metadata or {}),
        }
        if not meta_path.exists():
            self._atomic_write(
                meta_path,
                json.dumps(meta, sort_keys=True, indent=2, default=str).encode("utf-8"),
            )
        return ref

    @staticmethod
    def sha_from_handle(handle: str) -> str:
        match = _HANDLE_RE.match(handle)
        if not match:
            raise ValueError(f"invalid observation handle: {handle!r}")
        return match.group(1)

    def content_path(self, handle: str) -> Path:
        sha = self.sha_from_handle(handle)
        return self._paths(sha)[0]

    def verify(self, handle: str) -> bool:
        sha = self.sha_from_handle(handle)
        path = self._paths(sha)[0]
        if not path.exists():
            return False
        return self._digest(path.read_bytes()) == sha

    def recall(
        self,
        handle: str,
        *,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> str:
        sha = self.sha_from_handle(handle)
        path = self._paths(sha)[0]
        if not path.exists():
            raise FileNotFoundError(f"observation not found: {handle}")
        data = path.read_bytes()
        actual = self._digest(data)
        if actual != sha:
            raise ObservationIntegrityError(
                f"observation digest mismatch: expected {sha}, got {actual}"
            )
        text = data.decode("utf-8")
        lines = text.splitlines()
        if start_line < 1:
            raise ValueError("start_line must be >= 1")
        if end_line is None:
            end_line = len(lines)
        if end_line < start_line:
            raise ValueError("end_line must be >= start_line")
        return "\n".join(lines[start_line - 1 : end_line])

    def should_pack(self, text: str) -> bool:
        return len(text.encode("utf-8")) >= self.threshold_bytes
