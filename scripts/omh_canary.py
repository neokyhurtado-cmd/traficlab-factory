"""Isolated Oh My Hermes compatibility canary for the TraficLab Control Room.

This script intentionally does NOT run the upstream installer and does NOT touch
the ambient Hermes profile. It downloads the pinned release wheel, verifies its
published SHA256, installs it into a temporary venv, and runs OMH setup/doctor
against explicit temporary OMH_HOME and HERMES_HOME directories.

The live Control Room activation is a separate gate after this canary passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import venv

OMH_VERSION = "2.0.3"
OMH_REF = "47ab4e27682337c031e08b73ae6c1a42eb69b7f7"
WHEEL_SHA256 = "8b0eccddb0cfe38364881b0f5b3e61f8eb13cc0d761519b73958e356e87f754f"
WHEEL_URL = (
    "https://github.com/rlaope/oh-my-hermes/releases/download/"
    "v2.0.3/oh_my_hermes-2.0.3-py3-none-any.whl"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> dict:
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        check=False,
    )
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "output": proc.stdout[-20000:],
    }


def hermes_config_snapshot() -> dict[str, str | None]:
    home = Path.home() / ".hermes"
    targets = [home / "config.yaml"]
    profiles = home / "profiles"
    if profiles.is_dir():
        targets.extend(sorted(profiles.glob("*/config.yaml")))
    snapshot: dict[str, str | None] = {}
    for path in targets:
        key = str(path)
        snapshot[key] = sha256_file(path) if path.is_file() else None
    return snapshot


def resolve_tag() -> str | None:
    git = shutil.which("git")
    if not git:
        return None
    result = run(
        [
            git,
            "ls-remote",
            "https://github.com/rlaope/oh-my-hermes.git",
            "refs/tags/v2.0.3",
        ]
    )
    if result["returncode"] != 0 or not result["output"].strip():
        return None
    return result["output"].split()[0]


def omh_command(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "omh.exe"
    return venv_dir / "bin" / "omh"


def python_command(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence",
        default="evidence/omh_canary/omh_canary_latest.json",
        help="JSON report path",
    )
    parser.add_argument("--keep-sandbox", action="store_true")
    args = parser.parse_args()

    evidence = Path(args.evidence).resolve()
    evidence.parent.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "schema": "traficlab_omh_canary/v1",
        "omh_version": OMH_VERSION,
        "expected_omh_ref": OMH_REF,
        "expected_wheel_sha256": WHEEL_SHA256,
        "db_write": False,
        "source_media_write": False,
        "scheduler_created": False,
        "listener_created": False,
        "transport_owner_changed_by_script": False,
        "model_alias_change_requested": False,
        "mcp_enabled": False,
        "ambient_hermes_config_before": hermes_config_snapshot(),
    }

    tag_ref = resolve_tag()
    report["observed_tag_ref"] = tag_ref
    report["tag_ref_match"] = tag_ref == OMH_REF

    sandbox = Path(tempfile.mkdtemp(prefix="traficlab-omh-canary-"))
    report["sandbox"] = str(sandbox)

    try:
        wheel = sandbox / "oh_my_hermes-2.0.3-py3-none-any.whl"
        urllib.request.urlretrieve(WHEEL_URL, wheel)
        observed_digest = sha256_file(wheel)
        report["observed_wheel_sha256"] = observed_digest
        report["wheel_sha256_match"] = observed_digest == WHEEL_SHA256
        if observed_digest != WHEEL_SHA256:
            report["verdict"] = "FAIL"
            report["failure"] = "WHEEL_SHA256_MISMATCH"
            return_code = 2
        elif tag_ref != OMH_REF:
            report["verdict"] = "FAIL"
            report["failure"] = "TAG_REF_MISMATCH"
            return_code = 3
        else:
            venv_dir = sandbox / "venv"
            omh_home = sandbox / "omh-home"
            hermes_home = sandbox / "hermes-home"
            venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)

            py = python_command(venv_dir)
            install = run(
                [
                    str(py),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-cache-dir",
                    str(wheel),
                ]
            )
            report["install"] = install

            omh = omh_command(venv_dir)
            if install["returncode"] != 0 or not omh.is_file():
                report["verdict"] = "FAIL"
                report["failure"] = "ISOLATED_INSTALL_FAILED"
                return_code = 4
            else:
                env = os.environ.copy()
                env["OMH_HOME"] = str(omh_home)
                env["HERMES_HOME"] = str(hermes_home)

                dry_run = run(
                    [
                        str(omh),
                        "--omh-home",
                        str(omh_home),
                        "--hermes-home",
                        str(hermes_home),
                        "setup",
                        "--dry-run",
                        "--channel",
                        "stable",
                        "--version",
                        OMH_VERSION,
                    ],
                    env=env,
                )
                report["setup_dry_run"] = dry_run

                setup = run(
                    [
                        str(omh),
                        "--omh-home",
                        str(omh_home),
                        "--hermes-home",
                        str(hermes_home),
                        "setup",
                        "--channel",
                        "stable",
                        "--version",
                        OMH_VERSION,
                    ],
                    env=env,
                )
                report["setup_isolated"] = setup

                doctor = run(
                    [
                        str(omh),
                        "--omh-home",
                        str(omh_home),
                        "--hermes-home",
                        str(hermes_home),
                        "doctor",
                    ],
                    env=env,
                )
                report["doctor"] = doctor

                hermes = shutil.which("hermes")
                report["hermes_command"] = hermes
                if hermes:
                    smoke = run(
                        [
                            str(omh),
                            "--omh-home",
                            str(omh_home),
                            "--hermes-home",
                            str(hermes_home),
                            "release",
                            "hermes-smoke",
                            "--live",
                            "--install-path",
                            "setup",
                        ],
                        env=env,
                    )
                else:
                    smoke = {
                        "cmd": [],
                        "returncode": 127,
                        "output": "Hermes CLI not found on PATH",
                    }
                report["hermes_smoke"] = smoke

                report["doctor_ok"] = doctor["returncode"] == 0
                report["hermes_smoke_ok"] = smoke["returncode"] == 0
                report["verdict"] = (
                    "PASS"
                    if dry_run["returncode"] == 0
                    and setup["returncode"] == 0
                    and doctor["returncode"] == 0
                    and smoke["returncode"] == 0
                    else "FAIL"
                )
                return_code = 0 if report["verdict"] == "PASS" else 5
    except Exception as exc:
        report["verdict"] = "FAIL"
        report["failure"] = f"{type(exc).__name__}: {exc}"
        return_code = 10
    finally:
        report["ambient_hermes_config_after"] = hermes_config_snapshot()
        report["ambient_hermes_config_unchanged"] = (
            report["ambient_hermes_config_before"]
            == report["ambient_hermes_config_after"]
        )
        if not report["ambient_hermes_config_unchanged"]:
            report["verdict"] = "FAIL"
            report["failure"] = "AMBIENT_HERMES_CONFIG_CHANGED"
            return_code = 11

        evidence.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if not args.keep_sandbox:
            shutil.rmtree(sandbox, ignore_errors=True)

    print(json.dumps({
        "verdict": report.get("verdict"),
        "evidence": str(evidence),
        "omh_ref": report.get("observed_tag_ref"),
        "doctor_ok": report.get("doctor_ok"),
        "hermes_smoke_ok": report.get("hermes_smoke_ok"),
        "ambient_hermes_config_unchanged": report.get(
            "ambient_hermes_config_unchanged"
        ),
    }, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
