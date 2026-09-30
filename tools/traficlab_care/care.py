#!/usr/bin/env python3
"""TraficLab Care: one-shot maintenance worker, no resident daemon.

Python standard library only. Product repositories and external evidence are
read-only. System cleanup remains delegated to Housekeeper; only this program's
marked disposable cache can be removed here.
"""
from __future__ import annotations

import argparse
import ast
import ctypes
import hashlib
import html
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

APP = "TraficLab Care"
VERSION = "0.1.0"
MARKER = ".traficlab-care.json"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
OWNER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
MAX_JSON_BYTES = 2 * 1024 * 1024


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path, limit=MAX_JSON_BYTES):
    p = Path(path)
    if p.stat().st_size > limit:
        raise ValueError("JSON excede el límite de tamaño")
    return json.loads(p.read_text(encoding="utf-8-sig"))


def under(path, parent):
    return Path(path).resolve().is_relative_to(Path(parent).resolve())


def reject_symlinks(path):
    p = Path(path).absolute()
    for node in (p, *p.parents):
        reparse = False
        if os.name == "nt":
            try:
                info = node.lstat()
                reparse = blocked_windows_reparse(getattr(info, "st_file_attributes", 0),
                                                  getattr(info, "st_reparse_tag", 0))
            except FileNotFoundError:
                pass
        if node.is_symlink() or reparse:
            raise ValueError("Ruta enlazada: se conserva sin modificar")


def blocked_windows_reparse(attributes, tag):
    # Cloud Files tags (OneDrive) describe sync placeholders, not path links.
    # Preserve unknown reparse types; reject symlinks/junctions/mount points.
    # MS-FSCC 2.1.2.1 documents CLOUD through CLOUD_F.
    return bool(attributes & 0x400) and (tag & 0xFFFF0FFF) != 0x9000001A


def atomic_write(path, text):
    p = Path(path)
    reject_symlinks(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".care-write-", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(temporary, p)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def command(argv, cwd=None, timeout=30):
    """No shell, no executable instructions from issues/config adapters."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": type(exc).__name__}
    if p.returncode:
        # Avoid logging credentials, private command output, or shell snippets.
        return {"ok": False, "error": "exit_" + str(p.returncode)}
    return {"ok": True, "stdout": p.stdout}


def validate_config(cfg):
    if cfg.get("schema_version") != 1:
        raise ValueError("schema_version debe ser 1")
    owner = cfg.get("owner", "")
    if not OWNER_RE.fullmatch(owner):
        raise ValueError("owner inválido")
    expected_sid = cfg.get("windows_user_sid", "")
    if expected_sid and current_windows_sid() != expected_sid:
        raise ValueError("Este perfil debe ejecutarse bajo su propia cuenta Windows")
    expected_host = cfg.get("host_name", "")
    if expected_host and expected_host.casefold() != socket.gethostname().casefold():
        raise ValueError("El perfil pertenece a otro servidor")
    root = Path(cfg.get("state_dir", ""))
    if not root.is_absolute():
        raise ValueError("state_dir debe ser absoluto y fuera de repos/vault")
    reject_symlinks(root)
    protected = list(cfg.get("protected_roots", []))
    vault = cfg.get("vault_path", "")
    if vault:
        if not Path(vault).is_absolute():
            raise ValueError("vault_path debe ser absoluto")
        protected.append(vault)
    for project in cfg.get("projects", []):
        if not REPO_RE.fullmatch(project.get("repository", "")):
            raise ValueError("repository debe tener formato owner/repo")
        local = project.get("local_path", "")
        if local:
            if not Path(local).is_absolute():
                raise ValueError("local_path debe ser absoluto")
            protected.append(local)
    for path in protected:
        if path and (under(root, path) or under(path, root)):
            raise ValueError("state_dir se solapa con una fuente protegida")
    return cfg


def current_windows_sid():
    if os.name != "nt":
        return None
    result = command(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value"], timeout=10)
    return result["stdout"].strip() if result["ok"] else None


def init_state(cfg):
    root = Path(cfg["state_dir"])
    reject_symlinks(root)
    marker = root / MARKER
    if marker.exists():
        saved = read_json(marker)
        if saved.get("app") != APP or saved.get("owner") != cfg["owner"]:
            raise ValueError("state_dir pertenece a otro programa/perfil")
    else:
        if root.exists() and any(root.iterdir()):
            raise ValueError("Directorio existente sin identidad: se conserva")
        root.mkdir(parents=True, exist_ok=True)
        write_json(marker, {"app": APP, "owner": cfg["owner"], "created_at": now_iso()})
    (root / "cache").mkdir(exist_ok=True)
    reject_symlinks(root / "cache")
    return root


class RunLock:
    def __init__(self, root):
        self.path = Path(root) / "run.lock"

    def __enter__(self):
        reject_symlinks(self.path)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            # A stale lock is reported, never silently bypassed or removed.
            raise RuntimeError("BUSY_OR_STALE_LOCK: revisar run.lock; no se cerró ningún proceso")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "host": socket.gethostname(), "at": now_iso()}, f)
        return self

    def __exit__(self, *_):
        self.path.unlink(missing_ok=True)


def memory_status():
    if os.name == "nt":
        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total_phys", "avail_phys", "total_page", "avail_page",
                    "total_virtual", "avail_virtual", "avail_extended")]
        obj = Status()
        obj.length = ctypes.sizeof(obj)
        api = ctypes.windll.kernel32.GlobalMemoryStatusEx
        api.argtypes, api.restype = [ctypes.POINTER(Status)], ctypes.c_int
        if api(ctypes.byref(obj)):
            return {"status": "OBSERVED", "total_bytes": obj.total_phys,
                    "available_bytes": obj.avail_phys, "load_percent": obj.load}
    elif Path("/proc/meminfo").exists():
        values = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            name, rest = line.split(":", 1)
            values[name] = int(rest.split()[0]) * 1024
        total, available = values["MemTotal"], values.get("MemAvailable", values["MemFree"])
        return {"status": "OBSERVED", "total_bytes": total,
                "available_bytes": available, "load_percent": round(100 * (1 - available / total), 1)}
    return {"status": "UNAVAILABLE"}


def top_processes():
    if os.name == "nt":
        result = command(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 8 "
            "Id,ProcessName,WorkingSet64 | ConvertTo-Json -Compress"], timeout=10)
        if result["ok"]:
            try:
                rows = json.loads(result["stdout"])
                return {"status": "OBSERVED", "items": rows if isinstance(rows, list) else [rows]}
            except ValueError:
                pass
    return {"status": "UNAVAILABLE", "note": "No se cierran procesos ni se vacía RAM a la fuerza"}


def disk_status(roots):
    rows = []
    for root in roots:
        try:
            d = shutil.disk_usage(root)
            rows.append({"path": root, "status": "OBSERVED", "total_bytes": d.total,
                         "free_bytes": d.free, "used_bytes": d.used})
        except OSError:
            rows.append({"path": root, "status": "UNAVAILABLE"})
    return rows


def health_probe(url):
    parsed = urllib.parse.urlparse(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password):
        return {"url": url, "status": "REFUSED_NON_LOCAL_ENDPOINT"}
    try:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(url, timeout=2) as response:
            # Read bounded data; a health 200 is not product acceptance.
            response.read(65536)
            return {"url": url, "status": "HTTP_OBSERVED", "http_status": response.status,
                    "product_certified": False}
    except Exception as exc:
        return {"url": url, "status": "UNAVAILABLE", "error": type(exc).__name__}


def evidence_adapter(path, max_age_hours=6):
    if not path:
        return {"status": "NOT_CONFIGURED"}
    try:
        data = read_json(path)
        timestamp = data.get("generated_at") or data.get("created_at") or data.get("scanned_at")
        if not timestamp:
            return {"status": "UNKNOWN_FRESHNESS", "path": path, "evidence": data}
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return {"status": "UNKNOWN_FRESHNESS", "path": path}
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return {"status": "REPORTED_FRESH" if 0 <= age <= max_age_hours else "STALE",
                "path": path, "age_hours": round(age, 2), "evidence": data}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return {"status": "UNAVAILABLE", "error": type(exc).__name__, "path": path}


def github_project(project, cache, owner, ttl=3600):
    repo = project["repository"]
    path = cache / ("gh-" + digest(repo)[:20] + ".json")
    try:
        old = read_json(path)
        if (old.get("app") == APP and old.get("owner") == owner and
                0 <= time.time() - old["created_epoch"] < ttl):
            return dict(old["data"], transport="CACHE", observed_at=old["observed_at"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if not shutil.which("gh"):
        return {"repository": repo, "status": "UNAVAILABLE", "reason": "GitHub CLI gh no disponible"}

    def get(endpoint):
        response = command(["gh", "api", endpoint], timeout=20)
        if not response["ok"]:
            raise ValueError(response.get("error", "gh_error"))
        return json.loads(response["stdout"])

    try:
        main = get("repos/" + repo + "/branches/main")
        opened = get("repos/" + repo + "/issues?state=open&per_page=30&sort=updated&direction=desc")
        prs = get("repos/" + repo + "/pulls?state=open&per_page=20&sort=updated&direction=desc")
        carriers = []
        for number in project.get("carriers", [])[:5]:
            issue = get("repos/" + repo + "/issues/" + str(int(number)))
            carriers.append({k: issue.get(k) for k in ("number", "title", "state", "html_url", "updated_at")})
        snapshot = {"repository": repo, "status": "GITHUB_OBSERVED",
                    "main_sha": main["commit"]["sha"], "observed_at": now_iso(),
                    "issues": [{k: r.get(k) for k in ("number", "title", "state", "html_url", "updated_at")}
                               for r in opened if "pull_request" not in r],
                    "pull_requests": [{"number": r["number"], "title": r["title"], "draft": r["draft"],
                                       "head_sha": r["head"]["sha"], "base_sha": r["base"]["sha"],
                                       "url": r["html_url"]} for r in prs],
                    "carriers": carriers, "coverage": "Hasta 30 issues/20 PR recientes; no es censo exhaustivo"}
        write_json(path, {"app": APP, "owner": owner, "created_epoch": time.time(),
                          "observed_at": snapshot["observed_at"], "data": snapshot})
        return snapshot
    except (ValueError, KeyError, TypeError) as exc:
        return {"repository": repo, "status": "UNAVAILABLE", "reason": str(exc)[:100]}


def local_git_status(path):
    if not path or not Path(path).is_dir():
        return {"status": "UNAVAILABLE"}
    head = command(["git", "-C", path, "rev-parse", "HEAD"])
    dirty = command(["git", "-C", path, "status", "--porcelain", "-z"])
    branch = command(["git", "-C", path, "branch", "--show-current"])
    if not all(r["ok"] for r in (head, dirty, branch)):
        return {"status": "UNAVAILABLE"}
    return {"status": "GIT_OBSERVED", "head_sha": head["stdout"].strip(),
            "branch": branch["stdout"].strip(), "dirty": bool(dirty["stdout"]),
            "writes_performed": False}


def audit_python_file(text, path):
    """Static triage, not profiling. Every finding asks for a measurement."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [{"path": path, "kind": "PARSE_UNAVAILABLE", "status": "REVIEW"}]
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        span = (node.end_lineno or node.lineno) - node.lineno + 1
        decisions = sum(isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While,
                                      ast.Try, ast.IfExp, ast.BoolOp)) for n in ast.walk(node))
        base = {"path": path, "function": node.name, "line": node.lineno,
                "file_sha256": digest(text), "status": "MEASURE_FIRST"}
        if span >= 100 or decisions >= 20:
            findings.append(dict(base, kind="COMPLEX_FUNCTION", lines=span, decisions=decisions,
                next_step="Medir y cubrir invariantes antes de dividir/refactorizar; no se afirma mejora de velocidad"))
        repeated_calls = []
        for loop in ast.walk(node):
            if not isinstance(loop, (ast.For, ast.AsyncFor, ast.While)):
                continue
            for n in ast.walk(loop):
                if not isinstance(n, ast.Call):
                    continue
                name = n.func.attr if isinstance(n.func, ast.Attribute) else (
                    n.func.id if isinstance(n.func, ast.Name) else "")
                if name in {"read_text", "read_bytes", "execute", "fetchall", "run", "check_output"}:
                    repeated_calls.append({"name": name, "line": n.lineno})
        if repeated_calls:
            findings.append(dict(base, kind="IO_IN_LOOP", calls=repeated_calls[:12],
                next_step="Medir frecuencia/costo; evaluar batching o caché por identidad sin cambiar semántica"))
    return findings


def audit_repository(project, max_files=250):
    root_text = project.get("local_path", "")
    status = local_git_status(root_text)
    if status["status"] != "GIT_OBSERVED":
        return {"status": "UNAVAILABLE", "repository": project["repository"], "findings": []}
    root = Path(root_text)
    tracked = command(["git", "-C", str(root), "ls-files", "-z", "--", "*.py"])
    if not tracked["ok"]:
        return {"status": "UNAVAILABLE", "findings": []}
    candidates = [p for p in tracked["stdout"].split("\0") if p][:max_files]
    findings, scanned = [], 0
    for relative in candidates:
        p = root / relative
        try:
            reject_symlinks(p)
            if not under(p, root) or not p.is_file() or p.stat().st_size > 512 * 1024:
                continue
            if any(part in {".git", ".venv", "venv", "node_modules", "vendor", "secrets"} for part in p.parts):
                continue
            text = p.read_text(encoding="utf-8")
            findings.extend(audit_python_file(text, relative))
            scanned += 1
        except (OSError, UnicodeError, ValueError):
            continue
    return {"status": "STATIC_ANALYSIS", "repository": project["repository"],
            "local_git": status, "files_scanned": scanned, "findings": findings[:40],
            "coverage": "Python tracked, acotado; JS/SQL/mediciones requieren revisión adicional",
            "speedup_measured": False}


def clean_cache(root, owner, *, apply=False, now=None, retention_days=7, max_bytes=128 * 1024 * 1024):
    root = Path(root)
    reject_symlinks(root / "cache")
    marker = read_json(root / MARKER)
    if marker.get("app") != APP or marker.get("owner") != owner:
        raise ValueError("Identidad de caché incorrecta")
    now = time.time() if now is None else now
    candidates, preserved, total = [], [], 0
    for p in sorted((root / "cache").iterdir()):
        if p.is_symlink() or not p.is_file() or not re.fullmatch(r"(?:gh|probe|ast)-[a-f0-9]{8,64}\.json", p.name):
            preserved.append(p.name)
            continue
        try:
            record = read_json(p)
            created = float(record["created_epoch"])
            if not math.isfinite(created):
                preserved.append(p.name)
                continue
            age = now - created
            size = p.stat().st_size
            if (record.get("app") != APP or record.get("owner") != owner or
                    age < retention_days * 86400 or age < 0 or total + size > max_bytes):
                preserved.append(p.name)
                continue
        except (OSError, ValueError, TypeError, KeyError):
            preserved.append(p.name)
            continue
        candidates.append({"name": p.name, "bytes": size})
        total += size
        if apply:
            p.unlink()
    return {"scope": "OWN_MARKED_DISPOSABLE_CACHE_ONLY", "applied": apply,
            "candidate_bytes": total, "removed_bytes": total if apply else 0,
            "candidates": candidates, "preserved": preserved,
            "system_cleanup_authority": "Housekeeper #56"}


def managed_note(path, text, hashes):
    """Do not overwrite even generated notes when the user edited them."""
    key = str(Path(path).absolute())
    reject_symlinks(path)
    if Path(path).exists():
        previous = Path(path).read_text(encoding="utf-8")
        if hashes.get(key) != digest(previous):
            return {"status": "PRESERVED_USER_EDIT", "path": key}
    atomic_write(path, text)
    hashes[key] = digest(text)
    return {"status": "WRITTEN", "path": key}


def compact_context(report):
    return {"app": APP, "owner": report["owner"], "generated_at": report["generated_at"],
            "purpose": "Contexto compacto; no autoridad para borrar ni proof de ejecución",
            "projects": [{"repository": p["repository"], "status": p["github"]["status"],
                          "main_sha": p["github"].get("main_sha"),
                          "pending": p["github"].get("issues", [])[:8],
                          "pull_requests": p["github"].get("pull_requests", [])[:8]}
                         for p in report["projects"]],
            "external_cleanup": report["housekeeper"]["status"]}


def markdown_report(report):
    gib = lambda n: round(n / 1024**3, 1)
    lines = ["---", "app: TraficLab Care", "owner: " + report["owner"],
             "generated_at: '" + report["generated_at"] + "'", "status: observed_with_explicit_gaps", "---", "",
             "# Resumen de mantenimiento", "",
             "Observaciones locales y metadatos GitHub; comentarios y código existente no certifican producto final.", ""]
    for project in report["projects"]:
        gh = project["github"]
        lines.extend(["## " + project["repository"], "", "GitHub: **" + gh["status"] + "**."])
        if gh.get("main_sha"):
            lines.append("Main observado: `" + gh["main_sha"] + "`; fuente: " + gh["observed_at"] + ".")
        for i in gh.get("carriers", []):
            lines.append(f"- [{i['title']}]({i['html_url']}) — {i['state']}.")
        for p in gh.get("pull_requests", [])[:6]:
            lines.append(f"- [PR #{p['number']}]({p['url']}) — " + ("draft" if p["draft"] else "open") + f"; head `{p['head_sha'][:12]}`; CI/review no certificados aquí.")
        audit = project["audit"]
        lines.append("Análisis estático: " + audit["status"] + "; candidatos requieren medición.")
        for finding in audit.get("findings", [])[:4]:
            lines.append(f"- `{finding['path']}`: {finding['kind']} en {finding.get('function', '?')}; {finding.get('next_step', 'revisar')}.")
        lines.append("")
    lines.extend(["## Equipo y mantenimiento", ""])
    for d in report["disks"]:
        lines.append(f"- Disco `{d['path']}`: " + (f"{gib(d['free_bytes'])} GiB libres." if d["status"] == "OBSERVED" else "no observable."))
    memory = report["memory"]
    lines.append("- RAM: " + (f"{memory['load_percent']}% usada; {gib(memory['available_bytes'])} GiB disponibles." if memory["status"] == "OBSERVED" else "no observable."))
    lines.append(f"- Caché propia eliminada: {report['cleanup']['removed_bytes']} bytes.")
    for name in ("storage_guardian", "housekeeper", "sessions"):
        lines.append(f"- {name}: **{report[name]['status']}**. No se infiere ejecución ni limpieza desde un plan.")
    lines.append("- Obsidian: **" + report.get("obsidian", {}).get("status", "WRITE_NOT_YET_CHECKED") + "**.")
    lines.extend(["", "La limpieza de disco del sistema la controla Housekeeper. Se conservan fuentes, notas editadas, sesiones activas y UNKNOWN.",
                  "Los datos de RAM se observan; no se vacía memoria ni se cierran procesos a la fuerza."])
    return "\n".join(lines) + "\n"


def html_report(markdown, report):
    # Standalone and escaped. No executable contents from GitHub or adapters.
    return "<!doctype html><html lang='es'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>" + \
        "<title>TraficLab Care</title><style>body{font:16px system-ui;max-width:1050px;margin:40px auto;padding:0 24px;background:#101827;color:#e4edf7}h1{color:#72ddc5}pre{white-space:pre-wrap;line-height:1.55;background:#182337;padding:24px;border-radius:12px}a{color:#72ddc5}</style>" + \
        "<h1>TraficLab Care</h1><p>" + html.escape(report["generated_at"]) + \
        "</p><pre>" + html.escape(markdown) + "</pre></html>"


def run_cycle(cfg, *, offline=False, due_only=False):
    validate_config(cfg)
    root = init_state(cfg)
    with RunLock(root):
        state_path = root / "state.json"
        previous = read_json(state_path) if state_path.exists() else {}
        interval = max(3600, int(cfg.get("interval_seconds", 3600)))
        if due_only and 0 <= time.time() - previous.get("last_run_epoch", 0) < interval:
            return {"status": "NOT_DUE"}
        projects = []
        for project in cfg.get("projects", []):
            gh = ({"repository": project["repository"], "status": "OFFLINE"} if offline else
                  github_project(project, root / "cache", cfg["owner"], ttl=interval))
            projects.append({"repository": project["repository"], "github": gh,
                             "local_git": local_git_status(project.get("local_path", "")),
                             "audit": audit_repository(project, max_files=int(cfg.get("audit_max_files", 250)))})
        report = {"app": APP, "version": VERSION, "owner": cfg["owner"], "generated_at": now_iso(),
                  "host_name": socket.gethostname(), "execution_scope": "USER_PROFILE",
                  "projects": projects, "disks": disk_status(cfg.get("disk_roots", [])),
                  "memory": memory_status(), "top_processes": top_processes(),
                  "health": [health_probe(url) for url in cfg.get("health_urls", [])],
                  "storage_guardian": evidence_adapter(cfg.get("storage_guardian_report", "")),
                  "housekeeper": evidence_adapter(cfg.get("housekeeper_manifest", "")),
                  "sessions": evidence_adapter(cfg.get("session_registry", "")),
                  "cleanup": clean_cache(root, cfg["owner"], apply=bool(cfg.get("clean_own_cache", True))),
                  "source_observation": "Local host observed; GitHub metadata optional; external adapters reported only"}
        md = markdown_report(report)
        date = datetime.now().strftime("%Y-%m-%d")
        write_json(root / "reports" / (date + ".json"), report)
        atomic_write(root / "reports" / (date + ".md"), md)
        atomic_write(root / "LATEST.html", html_report(md, report))
        write_json(root / "context.json", compact_context(report))
        hashes = previous.get("managed_note_hashes", {})
        vault = cfg.get("vault_path", "")
        if vault:
            if not Path(vault).is_dir() or Path(vault).name != cfg.get("vault_expected_name", "DAVID_OS"):
                report["obsidian"] = {"status": "VAULT_NOT_VERIFIED"}
            else:
                namespace = Path(vault) / "99_SYSTEM" / "traficlab_care" / cfg["owner"]
                try:
                    report["obsidian"] = managed_note(namespace / (date + ".md"), md, hashes)
                    report["obsidian_index"] = managed_note(namespace / "LATEST.md",
                        "---\nowner: " + cfg["owner"] + "\napp: TraficLab Care\n---\n\n[[99_SYSTEM/traficlab_care/" + cfg["owner"] + "/" + date + "]]\n", hashes)
                except (OSError, ValueError) as exc:
                    report["obsidian"] = {"status": "PRESERVED_OR_UNAVAILABLE", "error": type(exc).__name__}
        else:
            report["obsidian"] = {"status": "NOT_CONFIGURED"}
        md = markdown_report(report)
        atomic_write(root / "reports" / (date + ".md"), md)
        atomic_write(root / "LATEST.html", html_report(md, report))
        write_json(root / "reports" / (date + ".json"), report)
        write_json(state_path, {"app": APP, "owner": cfg["owner"], "last_run_epoch": time.time(),
                               "generated_at": report["generated_at"], "managed_note_hashes": hashes,
                               "last_report": str(root / "reports" / (date + ".json"))})
        return {"status": "COMPLETED_WITH_EXPLICIT_GAPS", "report": str(root / "LATEST.html"),
                "obsidian": report["obsidian"], "removed_cache_bytes": report["cleanup"]["removed_bytes"]}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["run", "doctor", "cleanup-cache", "audit"])
    p.add_argument("--config", required=True)
    p.add_argument("--offline", action="store_true", help="No consultar GitHub")
    p.add_argument("--due-only", action="store_true", help="Worker invocado por poller; como máximo una vez/hora")
    p.add_argument("--apply", action="store_true", help="Solo limpieza de caché propia; jamás Housekeeper delete")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        cfg = validate_config(read_json(args.config))
        if args.action == "run":
            result = run_cycle(cfg, offline=args.offline, due_only=args.due_only)
        elif args.action == "doctor":
            result = {"status": "CONFIG_VALID", "python": sys.version.split()[0],
                      "git_available": bool(shutil.which("git")), "gh_available": bool(shutil.which("gh")),
                      "vault_exists": bool(cfg.get("vault_path") and Path(cfg["vault_path"]).is_dir()),
                      "scheduling": "Existing scheduler hook; standalone Windows task is optional",
                      "system_cleanup": "External Housekeeper required; not executed by Care"}
        elif args.action == "audit":
            result = [audit_repository(p) for p in cfg.get("projects", [])]
        else:
            root = init_state(cfg)
            with RunLock(root):
                result = clean_cache(root, cfg["owner"], apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "REFUSED_OR_UNAVAILABLE", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
