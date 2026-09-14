"""INTERNAL_CONSULT must be provider-neutral and contain no credential material."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FILES = [
    ROOT / ".hermes" / "skills" / "internal-consult" / "SKILL.md",
    ROOT / "orchestrator" / "contracts" / "internal_consult_v1.yaml",
    ROOT / "orchestrator" / "contracts" / "INTERNAL_CONSULT.md",
]


def test_contract_has_no_literal_secret_assignment():
    joined = "\n".join(p.read_text(encoding="utf-8") for p in FILES)
    forbidden = ("API_KEY=", "TOKEN=", "PASSWORD=", "SECRET=")
    assert not any(item in joined for item in forbidden)
    assert "new_api_key_required: false" in joined
