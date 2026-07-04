# Agent Configuration — spacex-cryogenics

## Active Agents

| Agent | Role | Module |
|-------|------|--------|
| Alpha Agent | Physics modeling | src/alpha/ |
| Omega Agent | Control orchestration | src/omega/ |
| Watchdog | Integrity verification | .shadow_infrastructure/ |
| Mastermind | Cross-domain coordination | mastermind_sidecar.py |

## Communication Protocol

- Alpha agents publish state snapshots
- Omega agents subscribe and apply control actions
- Mastermind sidecar aggregates health metrics
- Watchdog verifies SHA-256 file hashes every 60s

## Health Monitoring

```bash
python mastermind_sidecar.py --status
.shadow_infrastructure/watchdog_daemon.py
```
