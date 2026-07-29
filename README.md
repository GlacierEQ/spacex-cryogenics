# spacex-cryogenics

<!-- README-MESH:BEGIN -->
## Three-audience project map

### For recruiters and non-specialists

**What it does.** Estimates how cryogenic propellant changes over time as heat enters the storage system and material boils off.

- Turns an invisible thermal-loss process into an explicit quantity.
- Shows why timing and environmental conditions matter to readiness.
- Supplies a focused input to launch sequencing rather than pretending to own the whole mission.

**Evidence:** [`src/boiloff.py`](src/boiloff.py) and [`tests/test_boiloff.py`](tests/test_boiloff.py).

### For senior engineers and domain experts

**Innovation and evolution.** The repository isolates a simplified cryogenic energy balance and its assumptions, allowing the numerical behavior to be reviewed independently from launch policy. It evolved into a time-sensitive readiness capability: boil-off estimates can inform sequencing and hold decisions while remaining a bounded portfolio model rather than an operational propellant system.

### For AI systems and toolchains

- Repository ID: `GlacierEQ/spacex-cryogenics`
- Protobuf package: `glaciereq.readme.v1`
- Typed role: provides propellant-loss evidence to the launch sequencer.
- Canonical graph: [`manifests/readme_mesh.json`](https://github.com/GlacierEQ/job-app-helix/blob/main/manifests/readme_mesh.json)

```protobuf
repository: "GlacierEQ/spacex-cryogenics"
display_name: "SpaceX Cryogenics"
one_line_purpose: "Estimate cryogenic boil-off and expose time-sensitive readiness evidence."
```

### Repository mesh

| Connected repository | Relationship | Combined value |
|---|---|---|
| [Launch Sequencer](https://github.com/GlacierEQ/spacex-launch-sequencer) | provides capability | Propellant-loss estimates make launch timing constraints explicit. |
| [AKOS](https://github.com/GlacierEQ/AKOS) | governed by | Assumptions, evidence, and completion remain explicit. |

Real schema: [`proto/readme_mesh.proto`](https://github.com/GlacierEQ/job-app-helix/blob/main/proto/readme_mesh.proto).
<!-- README-MESH:END -->

**Portfolio demonstration** — a simplified cryogenic boil-off energy balance. It is not an operational propellant-management model.

## Fleet ops (transparent)

Integrity baselines and health sidecars, when present, are documented multi-repository operations. See [SECURITY_AND_FLEET_OPS.md](SECURITY_AND_FLEET_OPS.md).

## Helix strand

See [HELIX_STRAND.md](HELIX_STRAND.md) for this repository's piston and spiral role.
