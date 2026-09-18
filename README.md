# TraficLab Factory

Factory for governed Hermes execution: profiles, policies, workers, worktrees, review, automation and durable evidence.

## Current Ashley status

Ashley is no longer in onboarding-only mode for SUINI.

~~~text
AGENT_ID = HERMES-ASHLEY-01
MEMBER_STATE = ACTIVE_PROJECT_MEMBER
CURRENT_PRIMARY_ASSIGNMENT = SUINI
SUINI_OWNER = ASHLEY
DEFAULT_WORK_MODE = GOAL_CHAIN
AUTO_NEXT_SAFE_GATE = YES
DAVID_COPY_PASTE_REQUIRED = NO
~~~

See ASHLEY-AGENT.md for the active contract.

The historical read-only onboarding evidence remains in GitHub history and suini#29, but must not be treated as Ashley's current operating restriction.

## Structure

~~~text
policies/          canonical operating rules
profiles/          Hermes profile templates
bootstrap/         setup/bootstrap tooling
skills-manifest/   skills and bundles
loop_engineering/  autonomous goal-loop contracts
orchestrator/      routing/control-plane primitives
~~~

## Authority

~~~text
GitHub remote > control-plane > product docs/state > PANORAMA/Obsidian > chat
~~~

Product ownership remains strict:

~~~text
if target_product != assigned_product:
    STOP — PRODUCT_OWNERSHIP_MISMATCH
~~~

Factory workers may operate inside an assigned product boundary, but factory orchestration does not itself grant cross-product write authority.
