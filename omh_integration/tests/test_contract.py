from omh_integration.contract import (
    CANONICAL_AUTHORITIES,
    OMH_REF,
    CanaryObservation,
    OmhUnitObservation,
    authority_violations,
    evaluate_canary,
    map_omh_state,
)


def test_running_requires_fresh_evidence():
    assert map_omh_state(OmhUnitObservation("running", fresh_evidence=True)) == "RUNNING_CONFIRMED"
    assert map_omh_state(OmhUnitObservation("running", fresh_evidence=False)) == "PROGRESS_STALLED"


def test_verified_requires_validated_result_record():
    assert map_omh_state(
        OmhUnitObservation(
            "verified",
            result_record_present=True,
            validated_result=True,
        )
    ) == "PASS"
    assert map_omh_state(OmhUnitObservation("verified")) == "NOT_PROVEN"


def test_failure_and_blocker_states_are_never_promoted_to_pass():
    assert map_omh_state(OmhUnitObservation("failed")) == "FAIL"
    assert map_omh_state(OmhUnitObservation("account_limit")) == "BLOCKED_EXTERNAL"
    assert map_omh_state(OmhUnitObservation("permission_blocked")) == "BLOCKED"
    assert map_omh_state(OmhUnitObservation("progress_stalled")) == "PROGRESS_STALLED"


def test_omh_cannot_take_canonical_authorities():
    candidate = dict(CANONICAL_AUTHORITIES)
    candidate["worktree_owner"] = "OMH"
    candidate["knowledge_authority"] = "OMH_MEMORY"
    candidate["directive_wake_owner"] = "OMH_SCHEDULER"
    violations = authority_violations(candidate)
    assert len(violations) == 3
    assert any("worktree_owner" in v for v in violations)
    assert any("knowledge_authority" in v for v in violations)
    assert any("directive_wake_owner" in v for v in violations)


def test_clean_isolated_canary_passes():
    result = evaluate_canary(
        CanaryObservation(
            omh_ref=OMH_REF,
            doctor_ok=True,
            hermes_smoke_ok=True,
            global_hermes_config_unchanged=True,
            worker_states=[
                OmhUnitObservation(
                    "verified",
                    fresh_evidence=True,
                    result_record_present=True,
                    validated_result=True,
                )
            ],
        )
    )
    assert result["verdict"] == "PASS"
    assert result["findings"] == []


def test_canary_fails_closed_on_boundary_collision():
    result = evaluate_canary(
        CanaryObservation(
            omh_ref="wrong",
            doctor_ok=False,
            hermes_smoke_ok=False,
            global_hermes_config_unchanged=False,
            new_scheduler=True,
            new_listener=True,
            transport_owner_mutated=True,
            canonical_db_writes=1,
            source_media_writes=1,
            worktree_owner="OMH",
            knowledge_authority="OMH_MEMORY",
            directive_wake_owner="OMH",
            independent_critic="OMH_SELF_REVIEW",
            rollback_ready=False,
        )
    )
    assert result["verdict"] == "FAIL"
    required = {
        "OMH_REF_MISMATCH",
        "OMH_DOCTOR_FAIL",
        "HERMES_SMOKE_FAIL",
        "GLOBAL_HERMES_CONFIG_MUTATED",
        "SECOND_SCHEDULER_FORBIDDEN",
        "NEW_LISTENER_FORBIDDEN",
        "TRANSPORT_OWNER_MUTATED",
        "CANONICAL_DB_WRITE_FORBIDDEN",
        "SOURCE_MEDIA_WRITE_FORBIDDEN",
        "WORKTREE_OWNER_COLLISION",
        "MEMORY_AUTHORITY_COLLISION",
        "DIRECTIVE_WAKE_COLLISION",
        "JUPITER_INDEPENDENCE_LOST",
        "ROLLBACK_NOT_READY",
    }
    assert required.issubset(set(result["findings"]))
