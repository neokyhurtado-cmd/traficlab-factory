"""Zero-copy GitHub directive -> Orca auto-wake bridge.

Opt-in is explicit in Directive.scope:
EXECUTION_TARGET=ORCA or ORCA_RUN_REQUIRED=YES.
The existing GitHub poller remains the only scheduler.
"""
from __future__ import annotations

import json, os, re, shlex, shutil, subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Protocol

from directive_watcher.directive_parser import Directive

_TRUE = {"1", "TRUE", "YES", "ON"}


class OrcaAutoWakeError(RuntimeError):
    pass


@dataclass(frozen=True)
class OrcaWakeResult:
    run_key: str
    run_id: str
    worktree_id: str
    terminal_handle: str
    action: str


class OrcaRunner(Protocol):
    def call(self, args: list[str], *, env: Mapping[str, str] | None = None,
             timeout_seconds: int = 60) -> dict[str, Any]: ...


def _tokens(scope: str) -> dict[str, str]:
    out = {}
    for chunk in re.split(r"[;\n]+", scope or ""):
        if "=" not in chunk:
            continue
        k, v = chunk.split("=", 1)
        out[k.strip().upper()] = v.strip()
    return out


def directive_requests_orca(d: Directive) -> bool:
    t = _tokens(d.scope)
    return t.get("EXECUTION_TARGET", "").upper() == "ORCA" or t.get("ORCA_RUN_REQUIRED", "").upper() in _TRUE


def _walk(v: Any) -> Iterable[dict[str, Any]]:
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from _walk(x)
    elif isinstance(v, list):
        for x in v:
            yield from _walk(x)


def _text(d: Mapping[str, Any], *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _id(payload: Any, keys: tuple[str, ...]) -> str:
    for d in _walk(payload):
        value = _text(d, *keys)
        if value:
            return value
    return ""


def _bool(payload: Any, key: str) -> Optional[bool]:
    for d in _walk(payload):
        if isinstance(d.get(key), bool):
            return d[key]
    return None


class SubprocessOrcaRunner:
    def __init__(self, command: str | None = None) -> None:
        command = command or self.resolve_command()
        self.argv0 = shlex.split(command, posix=(os.name != "nt"))

    @staticmethod
    def resolve_command() -> str:
        explicit = os.environ.get("ORCA_CLI_COMMAND", "").strip() or os.environ.get("ORCA_BIN", "").strip()
        if explicit:
            return explicit
        for name in ("orca", "orca.exe", "orca-ide"):
            found = shutil.which(name)
            if found:
                return found
        local = os.environ.get("LOCALAPPDATA", "").strip()
        if local:
            base = Path(local) / "Programs" / "orca" / "resources" / "bin"
            for leaf in ("orca", "orca.exe", "orca.cmd"):
                p = base / leaf
                if p.exists():
                    return str(p)
        raise OrcaAutoWakeError("Orca CLI not found")

    @staticmethod
    def _json(stdout: str) -> dict[str, Any]:
        text = (stdout or "").strip()
        if not text:
            return {}
        candidates = [text, *reversed(text.splitlines())]
        for candidate in candidates:
            try:
                value = json.loads(candidate)
                return value if isinstance(value, dict) else {"result": value}
            except json.JSONDecodeError:
                pass
        raise OrcaAutoWakeError("Orca returned non-JSON output")

    def call(self, args: list[str], *, env: Mapping[str, str] | None = None,
             timeout_seconds: int = 60) -> dict[str, Any]:
        merged = os.environ.copy()
        if env:
            merged.update({k: str(v) for k, v in env.items()})
        p = subprocess.run([*self.argv0, *args], capture_output=True, text=True,
                           env=merged, timeout=timeout_seconds, check=False)
        if p.returncode:
            detail = (p.stderr or p.stdout or "").strip()
            raise OrcaAutoWakeError(f"orca rc={p.returncode}: {' '.join(args)} :: {detail[:600]}")
        return self._json(p.stdout)


class OrcaAutoWakeBridge:
    """One durable Orca Run per repository/issue/target-branch lineage."""

    def __init__(self, *, registry_path: str | Path, runner: OrcaRunner | None = None,
                 hermes_command: str | None = None) -> None:
        self.path = Path(registry_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.runner = runner or SubprocessOrcaRunner()
        self.hermes_command = hermes_command or os.environ.get("ORCA_HERMES_COMMAND", "").strip() or "hermes -p orchestrator"
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            v = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(v, dict) and isinstance(v.get("runs"), dict):
                return v
        except (OSError, json.JSONDecodeError):
            pass
        return {"version": 1, "runs": {}}

    def _save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def run_key(d: Directive) -> str:
        return f"{d.repository}#{d.issue}:{d.target_branch}"

    def _repo_id(self, repository: str) -> str:
        payload = self.runner.call(["repo", "list", "--json"])
        full, name = repository.lower(), repository.rsplit("/", 1)[-1].lower()
        best = None
        for d in _walk(payload):
            rid = _text(d, "id", "repoId", "repo_id")
            if not rid or "::" in rid:
                continue
            blob = json.dumps(d, sort_keys=True).lower()
            score = (10 if full in blob else 0) + (4 if _text(d, "name", "displayName").lower() == name else 0)
            if score and (best is None or score > best[0]):
                best = (score, rid)
        if not best:
            raise OrcaAutoWakeError(f"repo not registered in Orca: {repository}")
        return best[1]

    def _exists(self, kind: str, ident: str, flag: str) -> bool:
        if not ident:
            return False
        try:
            self.runner.call([kind, "show", flag, ident, "--json"])
            return True
        except OrcaAutoWakeError:
            return False

    def _worktree(self, repo_id: str, d: Directive, record: dict[str, Any]) -> str:
        wid = str(record.get("worktree_id") or "")
        if self._exists("worktree", f"id:{wid}", "--worktree"):
            return wid
        payload = self.runner.call(["worktree", "list", "--repo", f"id:{repo_id}", "--json"])
        targets = {d.target_branch, f"refs/heads/{d.target_branch}", f"origin/{d.target_branch}"}
        for obj in _walk(payload):
            candidate = _text(obj, "id", "worktreeId", "worktree_id")
            if "::" in candidate and _text(obj, "branch", "branchName", "branch_name", "ref") in targets:
                return candidate
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", f"autowake-{d.repository.rsplit('/',1)[-1]}-{d.issue}")[:56]
        args = ["worktree", "create", "--repo", f"id:{repo_id}", "--name", name,
                "--base-branch", d.target_branch, "--no-parent", "--setup", "skip", "--json"]
        try:
            payload = self.runner.call(args, timeout_seconds=120)
        except OrcaAutoWakeError as e:
            if "setup" not in str(e).lower() and "unknown option" not in str(e).lower():
                raise
            payload = self.runner.call([x for x in args if x not in {"--setup", "skip"}], timeout_seconds=120)
        for obj in _walk(payload):
            candidate = _text(obj, "id", "worktreeId", "worktree_id")
            if "::" in candidate:
                return candidate
        raise OrcaAutoWakeError("worktree create returned no full worktree id")

    def _terminal(self, worktree_id: str, d: Directive, record: dict[str, Any]) -> str:
        handle = str(record.get("terminal_handle") or "")
        if self._exists("terminal", handle, "--terminal"):
            return handle
        payload = self.runner.call(["terminal", "list", "--worktree", f"id:{worktree_id}", "--json"])
        for obj in _walk(payload):
            h = _text(obj, "handle", "terminalHandle", "terminal_handle")
            if h and "hermes" in json.dumps(obj, sort_keys=True).lower():
                return h
        payload = self.runner.call(["terminal", "create", "--worktree", f"id:{worktree_id}",
                                    "--title", f"Hermes coordinator #{d.issue}",
                                    "--command", self.hermes_command, "--json"])
        handle = _id(payload, ("handle", "terminalHandle", "terminal_handle"))
        if not handle:
            raise OrcaAutoWakeError("terminal create returned no handle")
        return handle

    def _idle(self, handle: str) -> None:
        for ms in (60000, 120000):
            payload = self.runner.call(["terminal", "wait", "--terminal", handle, "--for", "tui-idle",
                                        "--timeout-ms", str(ms), "--json"], timeout_seconds=ms // 1000 + 15)
            if _bool(payload, "satisfied") is True:
                return
        raise OrcaAutoWakeError(f"Hermes terminal never became idle: {handle}")

    def _identity(self, handle: str) -> dict[str, str]:
        payload = self.runner.call(["terminal", "show", "--terminal", handle, "--json"])
        env = {"ORCA_TERMINAL_HANDLE": handle}
        for obj in _walk(payload):
            pane, tab = _text(obj, "paneKey", "pane_key"), _text(obj, "tabId", "tab_id")
            if pane:
                env["ORCA_PANE_KEY"] = pane
            if tab:
                env["ORCA_TAB_ID"] = tab
            if pane or tab:
                break
        return env

    def _run(self, d: Directive, handle: str, record: dict[str, Any]) -> tuple[str, str]:
        run_id = str(record.get("run_id") or "")
        env = self._identity(handle)
        run_exists = False
        if run_id:
            try:
                self.runner.call(["orchestration", "run-show", "--id", run_id, "--json"])
                run_exists = True
            except OrcaAutoWakeError:
                run_exists = False
        if run_exists:
            self.runner.call(["orchestration", "run-use", "--id", run_id, "--json"], env=env)
            return run_id, "resumed"
        objective = f"[factory-auto-wake:{self.run_key(d)}] GitHub #{d.issue} {d.action}"
        payload = self.runner.call(["orchestration", "run-create", "--objective", objective, "--json"], env=env)
        for obj in _walk(payload):
            candidate = _text(obj, "run_id", "runId", "id")
            if candidate.startswith(("run_", "run-")):
                return candidate, "created"
        raise OrcaAutoWakeError("run-create returned no run id")

    @staticmethod
    def _prompt(d: Directive, source_comment_id: int, run_id: str) -> str:
        return (
            "ZERO-COPY ORCA DIRECTIVE. You are the Hermes coordinator in the already-bound Orca Run. "
            "Do not create another Run and never ask David to copy/paste.\n\n"
            f"ORCA_RUN_ID={run_id}\nREPOSITORY={d.repository}\nISSUE_OR_PR={d.issue}\n"
            f"SOURCE_COMMENT_ID={source_comment_id}\nTARGET_BRANCH={d.target_branch}\n"
            f"EXPECTED_HEAD={d.expected_head}\nACTION={d.action}\nSCOPE={d.scope}\n\n"
            "Orca owns worktree/Run/terminals/browser. Hermes coordinates. Use MiniMax/mcode as the writer; "
            "if mcode is not a first-class Orca agent, create an Orca terminal running mcode, wait for tui-idle, "
            "and send the bounded task there. Use Orca browser/Design Mode or Playwright from this worktree. "
            "Reuse this Run/worktree; no duplicate visual branch. Do not merge/release/deploy or write SUINI "
            "without exact owner authorization. On completion or blocker, post a durable callback to this same "
            "GitHub issue/PR with ORCA_RUN_ID, HEAD, tests, browser evidence, blocker, and next safe gate."
        )

    def start_or_resume(self, d: Directive, *, source_comment_id: int, execution_id: str) -> OrcaWakeResult:
        if not directive_requests_orca(d):
            raise OrcaAutoWakeError("directive did not request Orca")
        key = self.run_key(d)
        runs = self.state.setdefault("runs", {})
        record = dict(runs.get(key) or {})
        if record.get("last_directive_id") == d.directive_id:
            return OrcaWakeResult(key, str(record.get("run_id") or ""), str(record.get("worktree_id") or ""),
                                  str(record.get("terminal_handle") or ""), "idempotent")
        repo_id = self._repo_id(d.repository)
        wid = self._worktree(repo_id, d, record)
        handle = self._terminal(wid, d, record)
        self._idle(handle)
        run_id, action = self._run(d, handle, record)
        self.runner.call(["terminal", "send", "--terminal", handle, "--text",
                          self._prompt(d, source_comment_id, run_id), "--enter", "--wait-submit", "10", "--json"],
                         timeout_seconds=30)
        runs[key] = {"run_id": run_id, "worktree_id": wid, "terminal_handle": handle,
                     "repository": d.repository, "issue": d.issue, "target_branch": d.target_branch,
                     "last_directive_id": d.directive_id, "last_execution_id": execution_id,
                     "last_source_comment_id": source_comment_id}
        self._save()
        return OrcaWakeResult(key, run_id, wid, handle, action)
