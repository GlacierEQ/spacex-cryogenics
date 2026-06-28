# SpaceX Cryogenics

LOX/LCH4 propellant management — thermodynamics, tank control, and thermal conditioning.

## Architecture

**Double Helix (Alpha + Omega)**

- **Alpha** (`src/alpha/thermodynamics.py`): Phase behavior — Clausius-Clapeyron vapor pressure, boil-off rates, heat transfer, subcooling.
- **Omega** (`src/omega/tank_controller.py`): Tank state machine — fill/drain/pressurize, valve control, thermal conditioning, alerts.

## Features

- LOX, LCH4, LH2 fluid property databases
- Saturation pressure via Clausius-Clapeyron
- Boil-off rate computation
- Tank pressurization modeling
- Subcooling margin monitoring
- Valve state management
- Thermal conditioning loops
- Zero external dependencies
