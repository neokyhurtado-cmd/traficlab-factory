from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class ProviderResult:
    status: str
    answers: Mapping[str, Any]
    metadata: Mapping[str, Any]
    error: str | None = None


class DecisionProvider(Protocol):
    def evaluate(
        self,
        *,
        state: Mapping[str, Any],
        questions: Mapping[str, Any],
    ) -> ProviderResult: ...


class DisabledProvider:
    def evaluate(
        self,
        *,
        state: Mapping[str, Any],
        questions: Mapping[str, Any],
    ) -> ProviderResult:
        return ProviderResult(
            status="DISABLED",
            answers={},
            metadata={},
            error="Jev shadow provider is disabled",
        )


class VercelJevProvider:
    """Optional Jev bridge through Vercel AI Gateway.

    Constructing this object never installs a package and never makes a network
    call. A live call requires an explicit AI_GATEWAY_API_KEY, Node on PATH,
    and the pinned optional AI SDK dependency installed under jev_shadow/node.

    The key is inherited by the child process and is never serialized into
    task state, stdout or evidence by this module.
    """

    def __init__(self, *, timeout_seconds: int = 20) -> None:
        self.timeout_seconds = timeout_seconds
        self.bridge = Path(__file__).with_name("node") / "bridge.mjs"

    def evaluate(
        self,
        *,
        state: Mapping[str, Any],
        questions: Mapping[str, Any],
    ) -> ProviderResult:
        if not os.environ.get("AI_GATEWAY_API_KEY"):
            return ProviderResult("UNAVAILABLE", {}, {}, "AI_GATEWAY_API_KEY is not set")
        node = shutil.which("node")
        if not node:
            return ProviderResult("UNAVAILABLE", {}, {}, "node is not available")
        if not self.bridge.is_file():
            return ProviderResult("UNAVAILABLE", {}, {}, "Jev bridge is missing")

        payload = json.dumps(
            {"state": dict(state), "questions": dict(questions)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            proc = subprocess.run(
                [node, str(self.bridge)],
                input=payload,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ProviderResult("ERROR", {}, {}, f"{type(exc).__name__}: {exc}")

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "unknown provider failure")[-2000:]
            return ProviderResult("ERROR", {}, {}, err)

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return ProviderResult("ERROR", {}, {}, f"invalid provider JSON: {exc}")

        return ProviderResult(
            status="OK",
            answers=data.get("answers", {}),
            metadata=data.get("metadata", {}),
        )
