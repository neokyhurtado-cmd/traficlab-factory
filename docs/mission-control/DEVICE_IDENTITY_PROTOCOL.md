# Device & Agent Identity Protocol

Mission Control must distinguish the physical/logical origin of every durable action.

## Principle

Do not identify a computer by hostname alone, OneDrive path, MAC address, disk serial, or a human nickname. Those can change, collide, or expose unnecessary hardware data.

Each physical host receives one immutable random `DEVICE_ID` at enrollment. Each logical worker/profile receives one stable `AGENT_ID`. Every execution receives a transient `SESSION_ID`.

Canonical model:

```text
DEVICE_ID  = physical machine identity
AGENT_ID   = logical worker/profile identity
SESSION_ID = one runtime/execution session
```

Recommended identifiers:

```text
DEVICE_ID  = PANO-DEV-<UUIDv4>
AGENT_ID   = PANO-AGENT-<role>-<short-id>
SESSION_ID = PANO-SES-<UUIDv4>
```

The UUID is generated once and persisted; it is not derived from MAC, CPU serial, Windows product ID, user account, or other personal/device secret.

## Local device card

Each enrolled computer keeps a local machine card containing at least:

```yaml
device_id: PANO-DEV-...
device_alias: human-friendly-name
os_family: windows|linux|macos
mission_control_role: workstation|server|runner|backup
first_registered_at: ISO-8601
active_agent_ids: []
vault_role: primary-editor|secondary-editor|runner|read-only
```

Machine-specific paths, local usernames and secrets stay local unless there is a specific operational need to store them in the private Mission Control repository.

## Private registry

The private `panorama-mission-control` repository must contain a registry under:

```text
99_SYSTEM/registry/devices/
99_SYSTEM/registry/agents/
```

One record per device and per agent. Public repositories may document this protocol but must not expose private inventory or machine-local paths.

## Durable provenance

Every material inventory, migration, synchronization test, conflict canary or generated evidence must record:

```text
DEVICE_ID
AGENT_ID
SESSION_ID
TIMESTAMP
SOURCE_SCOPE
TARGET_SCOPE
GIT_HEAD_BEFORE
GIT_HEAD_AFTER
RESULT
```

Git commits created by automation should use trailers when practical:

```text
MC-Device-ID: PANO-DEV-...
MC-Agent-ID: PANO-AGENT-...
MC-Session-ID: PANO-SES-...
```

## Enrollment gate

Before PC-A, PC-B, a server, or a new Hermes profile participates in the shared vault workflow:

1. Generate or recover its immutable DEVICE_ID.
2. Register the device in the private registry.
3. Register active AGENT_IDs.
4. Verify no duplicate DEVICE_ID exists.
5. Verify the current host reports the same identity after restart.
6. Only then run inventory, sync or migration gates.

A cloned disk/image must not silently inherit the same identity. If two simultaneously active machines present one DEVICE_ID, stop and re-enroll one of them with a new ID.

## Acceptance

```text
DEVICE_IDENTITY_PROTOCOL = PASS
ALL_ACTIVE_HOSTS_REGISTERED = YES
DUPLICATE_DEVICE_ID = 0
ALL_ACTIVE_AGENTS_REGISTERED = YES
PROVENANCE_FIELDS_PRESENT = YES
RESTART_IDENTITY_STABLE = PASS
```
