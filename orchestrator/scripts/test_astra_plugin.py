#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent / "plugins" / "astra-consult" / "__init__.py"

def _load():
    spec = importlib.util.spec_from_file_location("astra_consult_plugin", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module

class FakeCtx:
    def __init__(self):
        self.tool = None
        self.section = None
    def register_tool(self, **kwargs):
        self.tool = kwargs
    def register_system_prompt_section(self, *args, **kwargs):
        self.section = (args, kwargs)

def test_plugin_registers_tool_and_zero_handoff_policy():
    mod = _load()
    ctx = FakeCtx()
    mod.register(ctx)
    assert ctx.tool["name"] == "ask_astra"
    assert "technical question" in ctx.tool["schema"]["description"].lower()
    assert ctx.section[0][0] == "astra-consult.zero-handoff-policy"
    assert "Before asking David" in ctx.section[0][1]

def test_plugin_fails_closed_when_bridge_missing(monkeypatch, tmp_path):
    mod = _load()
    monkeypatch.setenv("ASTRA_CONSULT_SCRIPT", str(tmp_path / "missing.py"))
    out = json.loads(mod.handle_ask_astra({
        "project_id": "IA-VISION",
        "goal_id": "G",
        "current_gate": "F1",
        "repository": "neokyhurtado-cmd/IA-VISION",
        "question": "What now?",
    }))
    assert out["decision"] == "BLOCKED_EXTERNAL"
    assert out["schema_version"] == "ASTRA_CONSULT_DECISION_V1"

def test_plugin_invokes_bridge(monkeypatch, tmp_path):
    mod = _load()
    fake = tmp_path / "fake_astra.py"
    fake.write_text(
        "import json,sys\n"
        "data=json.load(sys.stdin)\n"
        "print(json.dumps({'schema_version':'ASTRA_CONSULT_DECISION_V1','decision':'AUTO_GO','decision_text':'go','why':'ok','allowed_actions':[],'forbidden_actions':[],'tests_required':[],'next_gate':'F2','confidence':'HIGH'}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ASTRA_CONSULT_SCRIPT", str(fake))
    out = json.loads(mod.handle_ask_astra({
        "project_id": "IA-VISION",
        "goal_id": "G",
        "current_gate": "F1",
        "repository": "neokyhurtado-cmd/IA-VISION",
        "question": "What now?",
    }))
    assert out["decision"] == "AUTO_GO"
