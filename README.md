# SpaceX Cryogenics — Propellant Management & LOX/CH4 Systems 🧊

> **Real-time cryogenic propellant monitoring, boil-off prediction, and autonomous loading sequence control.**

[![Python](https://img.shields.io/badge/Python-3.9+-blue)]()
[![C++](https://img.shields.io/badge/C++-17-00599C)]()
[![Domain](https://img.shields.io/badge/Domain-Propulsion%20Systems-red)]()

---

## 🎯 For Recruiters & Hiring Managers

This repository implements a **cryogenic propellant management system** — the software that monitors liquid oxygen (LOX) and methane (CH4) at -183°C and -162°C, predicting boil-off rates and controlling autonomous loading sequences. It demonstrates:

- **Thermodynamic modeling** of two-phase cryogenic fluid behavior
- **Real-time sensor fusion** across temperature, pressure, level, and flow sensors
- **Autonomous loading sequences** with safety interlocks and abort capabilities
- **Predictive analytics** for boil-off rate estimation and tanking timeline optimization

**Why this matters**: Cryogenic systems engineering requires the same precision, safety discipline, and real-time control found in semiconductor manufacturing, medical devices, and industrial automation — with zero margin for error.

---

## 🔬 For Engineers & Technical Reviewers

### Architecture

```
LOX/CH4 Sensors ──→ Thermodynamic Model ──→ Boil-off Predictor
       │                    │                       │
  PT/TT/LT/FT      Clausius-Clapeyron        Mass Balance
       │                    │                       │
  Raw Telemetry ──→ State Estimation ──→ Loading Sequence FSM
```

### Core Components

| Component | Language | Purpose |
|---|---|---|
| `src/cryo_engine.py` | Python | Loading sequence FSM, sensor fusion, safety interlocks |
| `src/thermo_model.cpp` | C++ | High-precision Clausius-Clapeyron phase equilibrium solver |
| `tests/` | Python | Tanking scenario simulation with fault injection |

### Key Thermodynamics

- **Clausius-Clapeyron equation**: `dP/dT = L / (T * ΔV)` for phase boundary tracking
- **Boil-off model**: Stefan-Boltzmann radiative + conductive heat leak integration
- **Subcooling margin**: ΔT below saturation temperature for densified propellant

---

## 🤖 ML/AI & Programmatic Mesh Integration

### Agent Mesh Connectivity

- **MCP Tool**: `cryo_status(tank_id)` — real-time propellant state queryable by orchestrator agents
- **Mastermind Sidecar**: Publishes thermal alerts to APEX Highway mesh
- **SHA-256 Integrity**: `.integrity/file_hashes.json` tamper detection

### AI/ML Extension Points

- **Boil-off Prediction**: LSTM time-series model trained on historical tanking telemetry
- **Anomaly Detection**: Autoencoder on multi-sensor streams for leak detection
- **Loading Optimization**: Bayesian optimization for minimum-boiloff loading profiles

```python
# Agent mesh query
status = await mcp_client.call_tool("spacex-cryogenics", "cryo_status", {"tank": "LOX_S1"})
# Returns: {"temp_k": 90.2, "pressure_psi": 45.3, "level_pct": 87.5, "boiloff_kg_hr": 12.4}
```

---

## ⚡ Quick Start

```bash
python3 src/cryo_engine.py
python3 tests/test_cryogenics.py
```
