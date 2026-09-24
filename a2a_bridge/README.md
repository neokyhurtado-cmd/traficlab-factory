# TrafficLab Factory A2A bridge

A2A is a transport/interoperability layer only. It does **not** replace Hermes,
Factory orchestration, OWNER-GATE, GitHub durability, JEV policy, or the existing
LoopEngine.

## Safety contract

- Protocol target: A2A v1.0.
- Default: `TRAFICLAB_A2A_MODE=off`.
- Only rollout mode: `shadow`.
- There is intentionally **no A2A enforce mode**.
- The bridge has no shell/git/action callback and cannot mutate a product repo.
- JEV decisions keep `may_control_execution=false`.
- Unknown inbound fields are discarded by `TaskSnapshot`.
- Server binds to loopback by default. Non-loopback binding is refused unless
  `TRAFICLAB_A2A_ALLOW_REMOTE=1` is explicitly set.

## Install the optional transport

```bash
pip install -e ".[a2a]"
```

## Start locally in shadow

```bash
set TRAFICLAB_A2A_MODE=shadow
python -m a2a_bridge
```

Defaults:

- bind: `127.0.0.1`
- port: `8787`
- JSON-RPC endpoint: `/a2a`
- Agent Card: standard A2A well-known route produced by the official SDK

A plain text request becomes a bounded `goal`. A JSON request may use the
existing `TaskSnapshot` fields. The response is JSON evidence only.
