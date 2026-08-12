#!/usr/bin/env python3
"""Executable cryogenic tank digital twin.

This is a deterministic simulation and review surface.  It emits proposed state
transitions and risk observations; it has no hardware I/O and no operational
launch-vehicle authority.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from alpha.thermodynamics import HeatTransfer, P_ATM_PA, PROPELLANTS, Propellant, TankState
from omega.predictive_boiloff import CryoTank, PredictiveBoiloffManager
from omega.tank_controller import TankController, TankMode


@dataclass(frozen=True)
class SensorFrame:
    temperature_k: float
    pressure_pa: float
    fill_fraction: float

    def __post_init__(self) -> None:
        values = (self.temperature_k, self.pressure_pa, self.fill_fraction)
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) for value in values):
            raise ValueError("sensor frame values must be finite numbers")
        if self.temperature_k <= 0 or self.pressure_pa <= 0 or not 0.0 <= self.fill_fraction <= 1.0:
            raise ValueError("sensor frame outside physical bounds")


class CryogenicDigitalTwin:
    def __init__(self, *, max_pressure_pa: float = 800_000.0) -> None:
        self.controller = TankController(max_pressure_pa=max_pressure_pa)
        self.predictor = PredictiveBoiloffManager()
        self.alerts: list[dict] = []
        self.controller.on_alert(self.alerts.append)

    def add_tank(
        self,
        tank_id: str,
        propellant: Propellant,
        *,
        total_volume_m3: float,
        fill_fraction: float,
        temperature_k: float,
        pressure_pa: float = P_ATM_PA,
        ambient_temp_k: float = 300.0,
        insulation_u_w_m2k: float = 0.01,
    ) -> None:
        if total_volume_m3 <= 0 or not 0 <= fill_fraction <= 1:
            raise ValueError("invalid tank volume or fill fraction")
        liquid = total_volume_m3 * fill_fraction
        state = TankState(
            propellant,
            fill_fraction,
            temperature_k,
            pressure_pa,
            total_volume_m3 - liquid,
            liquid,
            total_volume_m3,
        )
        state.validate()
        self.controller.register_tank(tank_id, state)
        radius = (3.0 * total_volume_m3 / (4.0 * math.pi)) ** (1.0 / 3.0)
        area = 4.0 * math.pi * radius**2
        self.controller.set_thermal_load(
            tank_id,
            HeatTransfer(area, insulation_u_w_m2k, ambient_temp_k, temperature_k, 0.05),
        )

    def ingest_sensor_frame(self, tank_id: str, frame: SensorFrame, *, tolerance_fraction: float = 0.10) -> dict:
        """Validate a sensor frame against simulated state without silently mutating it."""
        state = self.controller._require_tank(tank_id)
        comparisons = {
            "temperature_k": (frame.temperature_k, state.temperature_k, 5.0),
            "pressure_pa": (frame.pressure_pa, state.pressure_pa, max(10_000.0, state.pressure_pa * tolerance_fraction)),
            "fill_fraction": (frame.fill_fraction, state.fill_percent, max(0.02, tolerance_fraction)),
        }
        residuals = {name: observed - expected for name, (observed, expected, _) in comparisons.items()}
        inconsistent = [name for name, (observed, expected, tolerance) in comparisons.items() if abs(observed - expected) > tolerance]
        return {
            "tank_id": tank_id,
            "accepted_for_review": not inconsistent,
            "inconsistent_channels": inconsistent,
            "residuals": residuals,
            "operational_authority": False,
        }

    def step(self, seconds: float) -> dict:
        updates = self.controller.update(seconds)
        tanks = []
        for tank_id, state in self.controller._tanks.items():
            tanks.append(
                CryoTank(
                    tank_id,
                    PROPELLANTS[state.propellant].name,
                    state.total_volume_m3,
                    state.fill_percent,
                    state.temperature_k,
                    state.pressure_pa,
                )
            )
        prediction = self.predictor.analyze_tanks(tanks)
        return {
            "schema": "glaciereq.cryogenic-digital-twin.v1",
            "updates": updates,
            "alerts": list(self.alerts),
            "prediction": prediction,
            "operational_authority": False,
        }

    def status(self) -> dict:
        return {
            "schema": "glaciereq.cryogenic-status.v1",
            "tanks": self.controller.all_tanks_status,
            "alerts": list(self.alerts),
            "operational_authority": False,
        }


def build_demo() -> CryogenicDigitalTwin:
    twin = CryogenicDigitalTwin()
    twin.add_tank("lox_demo", Propellant.LOX, total_volume_m3=30.0, fill_fraction=0.90, temperature_k=88.0)
    twin.add_tank("ch4_demo", Propellant.LCH4, total_volume_m3=15.0, fill_fraction=0.86, temperature_k=109.0)
    twin.controller.set_pressurization_target("lox_demo", 180_000.0)
    twin.controller.set_mode("lox_demo", TankMode.PRESSURIZING)
    return twin


def evaluate_payload(payload: Mapping[str, object]) -> dict:
    tanks = payload.get("tanks")
    if not isinstance(tanks, list) or not tanks:
        raise ValueError("payload.tanks must be a non-empty array")
    twin = CryogenicDigitalTwin(max_pressure_pa=float(payload.get("max_pressure_pa", 800_000.0)))
    aliases = {"LOX": Propellant.LOX, "LCH4": Propellant.LCH4, "CH4": Propellant.LCH4, "LH2": Propellant.LH2}
    for raw in tanks:
        if not isinstance(raw, Mapping):
            raise ValueError("each tank must be an object")
        propellant_name = str(raw["propellant"]).upper()
        if propellant_name not in aliases:
            raise ValueError(f"unsupported propellant: {propellant_name}")
        twin.add_tank(
            str(raw["tank_id"]), aliases[propellant_name],
            total_volume_m3=float(raw["total_volume_m3"]),
            fill_fraction=float(raw["fill_fraction"]),
            temperature_k=float(raw["temperature_k"]),
            pressure_pa=float(raw.get("pressure_pa", P_ATM_PA)),
            ambient_temp_k=float(raw.get("ambient_temp_k", 300.0)),
            insulation_u_w_m2k=float(raw.get("insulation_u_w_m2k", 0.01)),
        )
    return twin.step(float(payload.get("step_seconds", 60.0)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local cryogenic tank digital twin")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("demo")
    simulate = sub.add_parser("simulate")
    simulate.add_argument("input")
    args = parser.parse_args(argv)
    if args.command in (None, "demo"):
        result = build_demo().step(60.0)
    else:
        import sys
        payload = json.load(sys.stdin) if args.input == "-" else json.loads(Path(args.input).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("input must be a JSON object")
        result = evaluate_payload(payload)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
