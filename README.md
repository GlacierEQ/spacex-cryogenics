# Cryogenic Propellant Digital Twin

**Deterministic LOX/LCH4/LH2 thermodynamics, boil-off prediction, tank-state simulation, and review-level balance planning.**

This is an independent GlacierEQ portfolio system. It is not affiliated with SpaceX. It provides no flight certification, hardware control, valve actuation, loading authority, or operational launch-vehicle interface.

## What now works

- SI-consistent fluid properties and ideal-gas ullage calculations;
- Clausius-Clapeyron saturation pressure anchored at each fluid's normal boiling point;
- saturation-temperature inversion and subcooling margins;
- conductive/radiative heat-leak and latent-heat boil-off calculations;
- deterministic tank-controller simulation with mutually exclusive fill/drain valves, bounded pressure targets, alerts, vent/emergency state, draining and thermal evolution;
- sensor-frame residual validation that does not silently overwrite simulated state;
- predictive boil-off integration over multiple horizons;
- same-propellant balance review that correctly moves mass from the fuller tank toward the emptier tank;
- executable `cryo-twin` JSON CLI;
- independent C++17 thermodynamic reference executable with native self-tests.

## Run it

```bash
python -m pip install -e . pytest
pytest -q
cryo-twin demo

g++ -std=c++17 -O2 -Wall -Wextra -Werror -pedantic src/thermo_model.cpp -o /tmp/cryo-thermo
/tmp/cryo-thermo
```

## Architecture

```text
Tank geometry + fluid properties
            |
            v
   SI thermodynamics ---------> C++17 reference model
            |
            +--> heat leak --> boil-off --> forward predictor
            |
Sensor frame +--> residual validation
            |
            v
   Tank-controller digital twin
            |
            +--> bounded review states / alerts
            +--> deterministic JSON status
            +--> multi-tank balance review
```

## Core surfaces

| Surface | Function |
|---|---|
| `src/alpha/thermodynamics.py` | saturation, ullage, heat transfer, boil-off, pressurization and subcooling math |
| `src/omega/tank_controller.py` | bounded deterministic tank state machine and safety observations |
| `src/omega/predictive_boiloff.py` | forward thermal prediction and same-fluid balance review |
| `src/cryo_engine.py` | executable digital twin, sensor validation and JSON CLI |
| `src/thermo_model.cpp` | independent C++17 thermodynamic reference and self-test executable |
| `tests/test_crystallized_function.py` | physical anchors, units, prediction, transfer direction, interlocks, sensors and CLI truth boundary |

## Important corrections

The previous repository claimed functionality that the shipped code did not justify. The crystallized implementation corrects those mismatches:

- the previous Python saturation model referenced half the critical pressure at the normal boiling point; it is now anchored to **101,325 Pa**;
- molar-mass / specific-gas-constant units are now explicit SI values instead of g/mol-like values used as kg/mol;
- predictive balance no longer proposes mass transfer from the emptier tank into the fuller tank;
- time-to-loss reporting is actually converted from seconds to hours;
- the README's previously missing `src/cryo_engine.py` now exists and executes;
- the C++ source is now a buildable C++17 executable with native self-verification;
- generic `hyper-scaling` metadata is gone.

## Model limits

These are engineering simulation models, not NIST-grade property tables or a replacement for validated EOS/REFPROP/mission-certified thermodynamics. The phase model is an anchored Clausius-Clapeyron approximation, the tank controller is a local digital twin, and transfer output is a review proposal only.

There is currently **no** live MCP tool, APEX event bus, autonomous physical loading system, LSTM predictor, autoencoder leak detector, or Bayesian loading optimizer in this repository. Those claims are intentionally absent until executable evidence exists.

## Machine contract

```yaml
schema: glaciereq.readme.v1
repository: GlacierEQ/spacex-cryogenics
purpose: deterministic cryogenic propellant digital-twin simulation
state: FUNCTIONAL_CANDIDATE
languages:
  python:
    role: thermodynamics, controller simulation, prediction, sensor review, CLI
  cpp17:
    role: independent thermodynamic reference and native self-test
promotion_requires:
  - Python 3.11 functional proof
  - Python 3.12 functional proof
  - Python 3.13 functional proof
  - C++17 compile and native self-test
  - required-functional-proof
nonclaims:
  - no SpaceX affiliation
  - no flight authority
  - no hardware I/O
  - no live MCP or APEX integration
```

**Green metadata is not the product. Executable thermodynamics and observable behavior are the product.**
