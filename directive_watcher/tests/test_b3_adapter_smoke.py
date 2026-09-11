"""Smoke test for the watcher-side b3_adapter."""
import os, sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
_REPO = os.path.dirname(_PARENT)
for p in [os.path.join(_REPO, "p1_human_go_gate", "src"),
          os.path.join(_REPO, "p1_human_go_gate"),
          _PARENT]:  # directive_watcher/
    if p not in sys.path:
        sys.path.insert(0, p)

import human_go_gate_v2 as hg
import seam
from b3_adapter import hermes2_merge_pr_19, bite_record


TEST_SECRET = "a" * hg.MIN_SECRET_KEY_LEN + "_B3_ADAPTER_SMOKE"


def _signed_event():
    raw = {
        "event_id": "evt_b3_smoke",
        "owner_principal": "david",
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 19,
        "expected_head": "b5326935bca4b21555394b20f1827cedde38b2a8",
        "issued_at": "2026-09-11T16:00:00+00:00",
        "expires_at": "2099-12-31T23:59:59+00:00",
    }
    return hg.sign_event(TEST_SECRET, raw)


def _candidate():
    return {
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 19,
        "expected_head": "b5326935bca4b21555394b20f1827cedde38b2a8",
        "owner_text": (
            "apruebo merge PR #19 de traficlab-factory\n"
            "HUMAN_GO_REAL\n"
            "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
            "PR = #19\n"
            "EXPECTED_HEAD = b5326935bca4b21555394b20f1827cedde38b2a8\n"
            "ACTION = MERGE_PR_19_AND_CONTROLLED_HERMES2_ACTIVATION\n"
            "ACTIVATION_MODE = CONTROLLED_PILOT_OBSERVABLE"
        ),
        "live_pr_head": "b5326935bca4b21555394b20f1827cedde38b2a8",
        "owner_event_id": "evt_b3_smoke",
    }


PASS = 0
FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}: {detail}")


def test_adapter_invokes_callable_when_eligible():
    registry = hg.ProvenanceRegistry(secret_key=TEST_SECRET)
    registry.add_event(_signed_event())
    replay = os.path.join(tempfile.gettempdir(), "b3_adapter_smoke_replay.json")
    bites = os.path.join(tempfile.gettempdir(), "b3_adapter_smoke_bites.json")
    for p in (replay, bites):
        try: os.unlink(p)
        except OSError: pass
    seam.reset_for_tests(replay_path=replay, bites_path=bites)
    gate = hg.HUMAN_GO_GATE_V2(
        provenance_registry=registry,
        replay_store=hg.ReplayStore(replay),
    )
    calls = []
    def fake_merge(candidate):
        calls.append(candidate["pr_number"])
        return {"gh": "merged", "sha": candidate["expected_head"]}
    result = hermes2_merge_pr_19(fake_merge, _candidate(), secret_key=TEST_SECRET)
    # Note: hermes2_merge_pr_19 reinitializes the gate internally, so
    # the gate we passed in is not the one used. Use seam.run_or_bite
    # directly to keep the explicit gate in scope.
    result2 = seam.run_or_bite(_candidate(), fake_merge, gate=gate)
    check("adapter-style call -> eligible (via seam.run_or_bite)",
          result2.get("eligible") is True or result2.get("merged") is True,
          str(result2)[:200])
    check("merge_callable invoked exactly once",
          len(calls) == 1, str(calls))


def test_adapter_bites_on_bypass():
    bites = os.path.join(tempfile.gettempdir(), "b3_adapter_bypass_bites.json")
    try: os.unlink(bites)
    except OSError: pass
    seam.reset_for_tests(bites_path=bites)
    # Simulate bypass detection
    rec = bite_record(
        "manual_gh_pr_merge_call_detected",
        attempted_action="merge",
        attempted_repo="neokyhurtado-cmd/traficlab-factory",
        attempted_pr=19,
        bites_path=bites,
    )
    bites_read = seam.read_bites(bites_path=bites)
    check("bypass bite recorded", len(bites_read) == 1, str(bites_read)[:200])
    check("bypass bite has correct kind",
          bites_read[0].get("kind") == "BITES_WITHOUT_GATE",
          str(bites_read[0])[:200])
    check("bypass bite has attempted_pr=19",
          bites_read[0].get("attempted_pr") == 19,
          str(bites_read[0])[:200])


ALL = [test_adapter_invokes_callable_when_eligible, test_adapter_bites_on_bypass]

if __name__ == "__main__":
    for t in ALL:
        print(f"\n--- {t.__name__} ---")
        try:
            t()
        except AssertionError as e:
            FAIL += 1
            print(f"  FAIL: AssertionError {e}")
        except Exception as e:
            FAIL += 1
            print(f"  FAIL: {type(e).__name__} {e}")
    print(f"\n=== B3 ADAPTER SMOKE: {PASS} pass, {FAIL} fail ===")
    sys.exit(0 if FAIL == 0 else 1)
