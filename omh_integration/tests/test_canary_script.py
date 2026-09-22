from pathlib import Path
import importlib.util

MODULE = Path(__file__).resolve().parents[2] / "scripts" / "omh_canary.py"
spec = importlib.util.spec_from_file_location("omh_canary_under_test", MODULE)
canary = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(canary)


def test_smoke_command_uses_absolute_recursive_omh_command(tmp_path):
    omh = tmp_path / "venv" / "Scripts" / "omh.exe"
    omh_home = tmp_path / "omh-home"
    hermes_home = tmp_path / "hermes-home"

    cmd = canary.build_hermes_smoke_command(omh, omh_home, hermes_home)

    assert cmd[0] == str(omh)
    idx = cmd.index("--omh-command")
    assert cmd[idx + 1] == str(omh)
    assert "--hermes-home" in cmd
    assert str(hermes_home) in cmd


def test_windows_localappdata_is_in_ambient_hermes_candidates(monkeypatch, tmp_path):
    local = tmp_path / "LocalAppData"
    explicit = tmp_path / "ExplicitHermes"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("HERMES_HOME", str(explicit))

    candidates = {
        str(path.resolve(strict=False)).lower()
        for path in canary.hermes_home_candidates()
    }

    assert str(explicit.resolve(strict=False)).lower() in candidates
    assert str((local / "hermes").resolve(strict=False)).lower() in candidates
    assert str((Path.home() / ".hermes").resolve(strict=False)).lower() in candidates
