"""Thin GitHub client abstraction.

The watcher talks to GitHub through three operations:

  - ``list_comments_since(repo, since_id)`` — pull comments newer than a
    previously seen id.
  - ``post_comment(repo, issue_number, body)`` — post an ACK or a RESULT.
  - ``get_branch_head(repo, branch)`` — resolve the HEAD sha of a branch
    for the EXPECTED_HEAD_BINDING contract (CONTEXT_BINDING_FAIL_CLOSED,
    PR #19 closeout).

We deliberately wrap both behind a small interface so the rest of the
watcher is test-defined and never imports ``gh`` directly. The production
implementation shells out to the ``gh`` CLI (which is already installed and
authenticated on the orchestrator host). Tests inject a fake.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Optional, Protocol


class GitHubClient(Protocol):
    """The interface every watcher component depends on."""

    def list_comments_since(self, repo: str, since_id: int) -> list["RemoteComment"]:
        ...

    def list_recent_comments(self, repo: str, limit: int = 50) -> list["RemoteComment"]:
        """Return the most recent N comments for the repo, in id-ascending
        order. Used by the edit-detection window (Fix #3): we re-fetch the
        last N comments each tick and compare body_sha against the seen
        table — any mismatch is an edit that must be surfaced, NOT
        silently re-executed.

        Production callers should keep ``limit`` small (e.g. 50) to bound
        the per-tick cost; the production gh CLI uses ``gh api
        /repos/.../comments --paginate`` already.
        """
        ...

    def post_comment(self, repo: str, issue_number: int, body: str) -> int:
        ...

    def get_branch_head(self, repo: str, branch: str) -> Optional[str]:
        """Resolve the current HEAD sha of ``repo``'s ``branch``.

        Contract: CONTEXT_BINDING_FAIL_CLOSED / HEAD_BINDING (PR #19
        closeout). Returns ``None`` if the branch cannot be resolved
        (404, network error, missing repo). The watcher treats
        ``None`` as a fail-closed BLOCK — no silent default, no dispatch.
        """
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
    """Raised when the underlying ``gh`` invocation fails.

    Subclasses carry the exit code + the last ~300 chars of stderr so the
    retry classifier can decide whether to retry without parsing the
    error string.
    """

    def __init__(self, message: str, *, exit_code: int = -1, stderr: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr

    @property
    def is_retryable(self) -> bool:
        """True if the underlying gh error is transient and worth retrying.

        Rules (per Fix #5 from the Astra re-audit):
          - 5xx HTTP errors → retryable (gh surfaces them as exit != 0
            with the status code in stderr)
          - 429 (rate limit) → retryable
          - 4xx (auth, not found, bad request) → NOT retryable
          - ConnectionError / TimeoutError → retryable
          - JSONDecodeError → NOT retryable (don't loop on bad response)
          - exit code 0 with garbled stdout → NOT retryable
          - any other non-zero exit → retryable (best-effort)
        """
        # Subprocess.TimeoutExpired is handled at the call site (separate
        # flow that subclasses this or wraps it).
        code = self.exit_code
        if code == 0:
            return False
        # Look for an HTTP status in stderr.
        for token in ("429", "500", "502", "503", "504"):
            if token in self.stderr:
                return True
        # Auth / 4xx → don't retry.
        for token in ("401", "403", "404", "422"):
            if token in self.stderr:
                return False
        # Default: non-zero exit codes that we can't classify get a
        # retry budget. The retry wrapper has its own max_attempts so
        # this never loops forever.
        return True


class GHCLIRateLimitError(GHCLIError):
    """Specific exception for HTTP 429 from gh. Always retryable."""
    pass


class GHCLINonRetryableError(GHCLIError):
    """Specific exception for 4xx errors that must NOT be retried.

    Retrying them is wasteful — same auth/permission state will just
    produce the same 4xx again.
    """
    pass


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

    def list_recent_comments(self, repo: str, limit: int = 50) -> list[RemoteComment]:
        """Production list-recent — uses gh api and returns the latest ``limit``
        comments. We rely on GitHub's default order (newest first) and
        then sort ascending by id for stable iteration.

        This is the production seam for edit-detection (Fix #3). Each
        tick the handler compares the sha256 of every returned comment
        against ``directive_seen``; a mismatch is an edit. We deliberately
        do NOT narrow by ``since_id`` here — the point is to revisit the
        last window of already-seen comments.
        """
        cmd = [
            self._gh, "api",
            f"/repos/{repo}/issues/comments",
            "-q", ".[] | {id: .id, user: .user.login, body: .body, html_url: .html_url, issue_url: .issue_url, updated_at: .updated_at}",
            "--paginate",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
        if proc.returncode != 0:
            raise GHCLIError(
                f"gh api list comments (recent) failed for {repo} "
                f"(exit {proc.returncode}): {proc.stderr.strip()[:300]}"
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
            issue_url = obj.get("issue_url", "")
            try:
                issue_number = int(issue_url.rsplit("/", 1)[-1])
            except (ValueError, IndexError):
                continue
            out.append(RemoteComment(
                id=cid,
                author=obj.get("user") or "",
                body=obj.get("body") or "",
                url=obj.get("html_url") or "",
                issue_number=issue_number,
            ))
        out.sort(key=lambda c: c.id)
        return out[-limit:] if len(out) > limit else out

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

    def get_branch_head(self, repo: str, branch: str) -> Optional[str]:
        """Resolve HEAD sha for ``repo``'s ``branch`` via ``gh api``.

        Production path: ``gh api /repos/{repo}/git/ref/heads/{branch}``
        returns JSON with the ``object.sha``. We pass through ``None``
        on any non-zero exit so the watcher can BLOCK fail-closed
        (CONTEXT_BINDING_FAIL_CLOSED / HEAD_BINDING).
        """
        cmd = [
            self._gh, "api",
            f"/repos/{repo}/git/ref/heads/{branch}",
            "-q", ".object.sha",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
        except subprocess.TimeoutExpired:
            return None
        if proc.returncode != 0:
            return None
        sha = (proc.stdout or "").strip()
        return sha or None


class FakeGitHubClient:
    """In-memory client for tests. Records every post_comment() call."""

    DEFAULT_TEST_HEAD = "1111111111111111111111111111111111111111"

    def __init__(
        self,
        initial_comments: list[RemoteComment] | None = None,
        branch_heads: dict[tuple[str, str], str] | None = None,
        seed_default_branch: bool = True,
    ) -> None:
        self._comments: list[RemoteComment] = list(initial_comments or [])
        self.posted: list[tuple[str, int, str]] = []
        # (repo, branch) → head sha. Tests seed this via set_branch_head.
        self._branch_heads: dict[tuple[str, str], str] = dict(branch_heads or {})
        if seed_default_branch:
            # Seed (repo, "main") for every repo that already has any
            # branch_head seeded AND for every repo that shows up in
            # ``_comments``. Tests that need stricter control can pass
            # ``seed_default_branch=False`` and set everything explicitly.
            for (r, _b), sha in list(self._branch_heads.items()):
                self._branch_heads.setdefault((r, "main"), sha)
            seen_repos = {c.url.split("/issues/")[0].split("github.com/")[-1]
                          for c in self._comments if "github.com/" in c.url}
            for r in seen_repos:
                self._branch_heads.setdefault((r, "main"), self.DEFAULT_TEST_HEAD)

    def add(self, c: RemoteComment) -> None:
        self._comments.append(c)
        # New comment → new repo to consider for the auto-seed.
        if "github.com/" in c.url:
            r = c.url.split("/issues/")[0].split("github.com/")[-1]
            self._branch_heads.setdefault((r, "main"), self.DEFAULT_TEST_HEAD)

    def set_branch_head(self, repo: str, branch: str, sha: str) -> None:
        """Seed the fake gh client's view of HEAD for ``repo``'s ``branch``."""
        self._branch_heads[(repo, branch)] = sha

    def list_comments_since(self, repo: str, since_id: int) -> list[RemoteComment]:
        # The repo arg is ignored by the fake — tests scope their fixtures.
        return [c for c in self._comments if c.id > since_id]

    def list_recent_comments(self, repo: str, limit: int = 50) -> list[RemoteComment]:
        # The fake returns the last ``limit`` comments regardless of repo arg.
        return self._comments[-limit:] if len(self._comments) > limit else list(self._comments)

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

    def get_branch_head(self, repo: str, branch: str) -> Optional[str]:
        return self._branch_heads.get((repo, branch))