"""Thin GitHub client abstraction.

The watcher talks to GitHub through two operations:

  - ``list_comments_since(repo, since_id)`` — pull comments newer than a
    previously seen id.
  - ``post_comment(repo, issue_number, body)`` — post an ACK or a RESULT.

We deliberately wrap both behind a small interface so the rest of the
watcher is test-defined and never imports ``gh`` directly. The production
implementation shells out to the ``gh`` CLI (which is already installed and
authenticated on the orchestrator host). Tests inject a fake.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Protocol


class GitHubClient(Protocol):
    """The interface every watcher component depends on."""

    def list_comments_since(self, repo: str, since_id: int) -> list["RemoteComment"]:
        ...

    def post_comment(self, repo: str, issue_number: int, body: str) -> int:
        ...


@dataclass(frozen=True)
class RemoteComment:
    """A GitHub issue comment, normalised across the JSON shapes ``gh``
    and the GitHub REST API both use."""

    id: int
    author: str
    body: str
    url: str
    issue_number: int


class GHCLIError(RuntimeError):
    """Raised when the underlying ``gh`` invocation fails."""


class GHCLIClient:
    """Production client. Invokes the ``gh`` CLI as a subprocess.

    Why subprocess and not PyGithub? Per #18 the watcher's runtime must be
    compatible with the existing orchestrator host setup, which already has
    ``gh`` authenticated. A second token layer would expand the attack
    surface without operational benefit.
    """

    def __init__(self, gh_bin: str = "gh", timeout: int = 60) -> None:
        self._gh = gh_bin
        self._timeout = timeout

    def list_comments_since(self, repo: str, since_id: int) -> list[RemoteComment]:
        cmd = [
            self._gh, "api",
            f"/repos/{repo}/issues/comments",
            "-q", ".[] | {id: .id, user: .user.login, body: .body, html_url: .html_url, issue_url: .issue_url}",
            "--paginate",
        ]
        # gh api does not natively support since-id; we filter client-side.
        # For very large histories this would be inefficient, but the watcher
        # polls every 5 minutes and only walks forward from last_seen_comment_id,
        # so the working set is small.
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
        if proc.returncode != 0:
            raise GHCLIError(
                f"gh api list comments failed for {repo} (exit {proc.returncode}): "
                f"{proc.stderr.strip()[:300]}"
            )
        out: list[RemoteComment] = []
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise GHCLIError(f"could not parse gh comment JSON: {e}") from e
            cid = int(obj["id"])
            if cid <= since_id:
                continue
            issue_url = obj.get("issue_url", "")
            # /repos/{owner}/{repo}/issues/{n}
            try:
                issue_number = int(issue_url.rsplit("/", 1)[-1])
            except (ValueError, IndexError):
                # Defensive: ignore comments we cannot resolve to an issue.
                continue
            out.append(RemoteComment(
                id=cid,
                author=obj.get("user") or "",
                body=obj.get("body") or "",
                url=obj.get("html_url") or "",
                issue_number=issue_number,
            ))
        # Stable order: ascending by id.
        out.sort(key=lambda c: c.id)
        return out

    def post_comment(self, repo: str, issue_number: int, body: str) -> int:
        cmd = [
            self._gh, "issue", "comment",
            str(issue_number),
            "--repo", repo,
            "--body", body,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
        if proc.returncode != 0:
            raise GHCLIError(
                f"gh issue comment failed for {repo}#{issue_number} "
                f"(exit {proc.returncode}): {proc.stderr.strip()[:300]}"
            )
        # gh prints a URL to the created comment on success. We don't need
        # the comment id for correctness; the watcher tracks ids via its own
        # state. Return 0 to indicate "posted" — the URL is in stdout for
        # humans reading logs.
        return 0


class FakeGitHubClient:
    """In-memory client for tests. Records every post_comment() call."""

    def __init__(
        self,
        initial_comments: list[RemoteComment] | None = None,
    ) -> None:
        self._comments: list[RemoteComment] = list(initial_comments or [])
        self.posted: list[tuple[str, int, str]] = []

    def add(self, c: RemoteComment) -> None:
        self._comments.append(c)

    def list_comments_since(self, repo: str, since_id: int) -> list[RemoteComment]:
        # The repo arg is ignored by the fake — tests scope their fixtures.
        return [c for c in self._comments if c.id > since_id]

    def post_comment(self, repo: str, issue_number: int, body: str) -> int:
        self.posted.append((repo, issue_number, body))
        # Synthesise a new id higher than any existing one.
        new_id = (max((c.id for c in self._comments), default=0) + 1)
        self._comments.append(RemoteComment(
            id=new_id,
            author="hermes-bot",
            body=body,
            url=f"https://github.com/{repo}/issues/{issue_number}#issuecomment-{new_id}",
            issue_number=issue_number,
        ))
        return new_id
