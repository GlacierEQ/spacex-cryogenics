# HELIX Architecture — spacex-cryogenics

## Double Helix Pattern

**Alpha (What)** — Pure physics models, stateless computation
- thermodynamics

**Omega (How)** — Controllers, orchestration, stateful management  
- predictive_boiloff,tank_controller

## Design Principles

- Zero external dependencies (stdlib only)
- Stateless alpha, stateful omega
- SHA-256 file integrity verification
- Shadow watchdog daemon monitoring
- Mastermind sidecar coordination

## Data Flow

```
Alpha Models → Omega Controllers → Mastermind Sidecar → Shadow Infrastructure
```
