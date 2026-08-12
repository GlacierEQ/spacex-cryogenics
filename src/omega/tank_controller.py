"""Deterministic cryogenic tank-controller simulation.

The controller is a digital-twin state machine.  Valve state is simulated only;
no hardware I/O or operational launch-vehicle authority is provided.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

from alpha.thermodynamics import (
    HeatTransfer,
    PROPELLANTS,
    Propellant,
    TankState,
    boil_off_rate,
    saturation_pressure,
    subcooling_margin,
)


class TankMode(Enum):
    FILLING = auto()
    IDLE = auto()
    PRESSURIZING = auto()
    DEPRESSURIZING = auto()
    DRAINING = auto()
    THERMAL_CONDITIONING = auto()
    EMERGENCY = auto()


@dataclass
class ValveState:
    name: str
    open: bool = False
    flow_rate: float = 0.0
    last_change: float = 0.0


@dataclass
class TankCommand:
    tank_id: str
    mode: TankMode
    target_pressure: float = 0.0
    target_fill: float = 0.0
    timestamp: float = 0.0


class TankController:
    """Review-grade state machine with deterministic safety interlocks."""

    def __init__(self, *, max_pressure_pa: float = 800_000.0, drain_rate_kg_s: float = 100.0, pressurant_rate_kg_s: float = 0.25):
        if max_pressure_pa <= 0 or drain_rate_kg_s <= 0 or pressurant_rate_kg_s <= 0:
            raise ValueError("controller limits must be > 0")
        self.max_pressure_pa = float(max_pressure_pa)
        self.drain_rate_kg_s = float(drain_rate_kg_s)
        self.pressurant_rate_kg_s = float(pressurant_rate_kg_s)
        self._tanks: dict[str, TankState] = {}
        self._modes: dict[str, TankMode] = {}
        self._valves: dict[str, dict[str, ValveState]] = {}
        self._pressurization_targets: dict[str, float] = {}
        self._event_log: list[dict] = []
        self._alert_callbacks: list[Callable] = []
        self._thermal_loads: dict[str, HeatTransfer] = {}

    def register_tank(self, tank_id: str, state: TankState):
        if not tank_id.strip() or tank_id in self._tanks:
            raise ValueError("tank_id must be unique and non-empty")
        state.validate()
        self._tanks[tank_id] = state
        self._modes[tank_id] = TankMode.IDLE
        self._valves[tank_id] = {name: ValveState(name) for name in ("fill", "drain", "pressurize", "vent")}
        self._log(tank_id, "registered")

    def set_thermal_load(self, tank_id: str, heat: HeatTransfer):
        self._require_tank(tank_id)
        self._thermal_loads[tank_id] = heat

    def set_mode(self, tank_id: str, mode: TankMode) -> bool:
        if tank_id not in self._tanks:
            return False
        if not isinstance(mode, TankMode):
            raise TypeError("mode must be TankMode")
        old = self._modes[tank_id]
        if old is TankMode.EMERGENCY and mode is not TankMode.IDLE:
            return False
        self._modes[tank_id] = mode
        self._apply_mode_valves(tank_id, mode)
        self._log(tank_id, f"mode:{old.name}->{mode.name}")
        return True

    def _apply_mode_valves(self, tank_id: str, mode: TankMode) -> None:
        valves = self._valves[tank_id]
        desired = {
            TankMode.FILLING: {"fill"},
            TankMode.PRESSURIZING: {"pressurize"},
            TankMode.DEPRESSURIZING: {"vent"},
            TankMode.DRAINING: {"drain"},
            TankMode.EMERGENCY: {"vent"},
        }.get(mode, set())
        now = time.time()
        for name, valve in valves.items():
            new_state = name in desired
            if valve.open != new_state:
                valve.open = new_state
                valve.last_change = now

    def set_valve(self, tank_id: str, valve_name: str, open: bool) -> bool:
        if tank_id not in self._valves or valve_name not in self._valves[tank_id]:
            return False
        if open and valve_name == "fill" and self._valves[tank_id]["drain"].open:
            return False
        if open and valve_name == "drain" and self._valves[tank_id]["fill"].open:
            return False
        valve = self._valves[tank_id][valve_name]
        valve.open = bool(open)
        valve.last_change = time.time()
        self._log(tank_id, f"valve:{valve_name}={'open' if open else 'closed'}")
        return True

    def set_pressurization_target(self, tank_id: str, target_pa: float):
        self._require_tank(tank_id)
        target_pa = float(target_pa)
        if not math.isfinite(target_pa) or target_pa <= 0 or target_pa > self.max_pressure_pa:
            raise ValueError("target pressure outside simulation envelope")
        self._pressurization_targets[tank_id] = target_pa

    def update(self, dt: float = 1.0) -> list[dict]:
        dt = float(dt)
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError("dt must be finite and > 0")
        updates = []
        for tank_id in list(self._tanks):
            self._apply_physics(tank_id, dt)
            self._check_alerts(tank_id)
            tank = self._tanks[tank_id]
            updates.append({
                "tank": tank_id,
                "mode": self._modes[tank_id].name,
                "pressure_pa": tank.pressure_pa,
                "fill_percent": tank.fill_percent,
                "temperature_k": tank.temperature_k,
                "operational_authority": False,
            })
        return updates

    def _apply_physics(self, tank_id: str, dt: float) -> None:
        tank = self._tanks[tank_id]
        mode = self._modes[tank_id]
        props = PROPELLANTS[tank.propellant]

        heat = self._thermal_loads.get(tank_id)
        if heat is not None:
            q = max(0.0, heat.net_heat_into_tank_w)
            loss = min(tank.liquid_mass, boil_off_rate(tank, q) * dt)
            if loss > 0:
                tank.liquid_volume_m3 = max(0.0, tank.liquid_volume_m3 - loss / props.density_liquid_kg_m3)
                tank.ullage_volume_m3 = max(0.0, tank.total_volume_m3 - tank.liquid_volume_m3)
                tank.fill_percent = tank.liquid_volume_m3 / tank.total_volume_m3
                if tank.liquid_mass > 0:
                    tank.temperature_k += 0.02 * q * dt / (tank.liquid_mass * props.cp_liquid_j_kg_k)

        if mode is TankMode.PRESSURIZING:
            target = self._pressurization_targets.get(tank_id, tank.pressure_pa)
            if tank.pressure_pa < target and tank.ullage_volume_m3 > 0:
                added_mass = self.pressurant_rate_kg_s * dt
                delta_p = added_mass * props.specific_gas_constant_j_kg_k * tank.temperature_k / tank.ullage_volume_m3
                tank.pressure_pa = min(target, tank.pressure_pa + delta_p)
        elif mode in (TankMode.DEPRESSURIZING, TankMode.EMERGENCY):
            tank.pressure_pa = max(P_MIN_PA, tank.pressure_pa * math.exp(-0.08 * dt))
        elif mode is TankMode.DRAINING:
            mass_loss = min(tank.liquid_mass, self.drain_rate_kg_s * dt)
            tank.liquid_volume_m3 = max(0.0, tank.liquid_volume_m3 - mass_loss / props.density_liquid_kg_m3)
            tank.ullage_volume_m3 = tank.total_volume_m3 - tank.liquid_volume_m3
            tank.fill_percent = tank.liquid_volume_m3 / tank.total_volume_m3

        if tank.liquid_volume_m3 > 0:
            tank.pressure_pa = max(tank.pressure_pa, min(self.max_pressure_pa, saturation_pressure(props, tank.temperature_k)))

    def _check_alerts(self, tank_id: str):
        tank = self._tanks[tank_id]
        alerts = []
        margin = subcooling_margin(tank.temperature_k, tank.propellant, tank.pressure_pa)
        if margin < 1.0:
            alerts.append({"tank": tank_id, "alert": "LOW_SUBCOOLING", "margin_k": margin})
        if tank.pressure_pa >= self.max_pressure_pa:
            alerts.append({"tank": tank_id, "alert": "OVER_PRESSURE", "pressure_pa": tank.pressure_pa})
            self._modes[tank_id] = TankMode.EMERGENCY
            self._apply_mode_valves(tank_id, TankMode.EMERGENCY)
        if tank.fill_percent <= 0.01:
            alerts.append({"tank": tank_id, "alert": "NEAR_EMPTY", "fill_percent": tank.fill_percent})
        for alert in alerts:
            alert["operational_authority"] = False
            self._log(tank_id, f"alert:{alert['alert']}")
            for callback in self._alert_callbacks:
                callback(alert)

    def on_alert(self, callback: Callable):
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._alert_callbacks.append(callback)

    def _require_tank(self, tank_id: str) -> TankState:
        try:
            return self._tanks[tank_id]
        except KeyError as exc:
            raise KeyError(f"unknown tank: {tank_id}") from exc

    def _log(self, tank_id: str, event: str):
        self._event_log.append({"time": time.time(), "tank": tank_id, "event": event})

    def get_tank_status(self, tank_id: str) -> Optional[dict]:
        tank = self._tanks.get(tank_id)
        if tank is None:
            return None
        props = PROPELLANTS[tank.propellant]
        return {
            "tank_id": tank_id,
            "propellant": props.name,
            "mode": self._modes[tank_id].name,
            "fill_percent": round(tank.fill_percent * 100.0, 3),
            "pressure_kpa": round(tank.pressure_pa / 1000.0, 3),
            "temperature_k": round(tank.temperature_k, 3),
            "liquid_mass_kg": round(tank.liquid_mass, 3),
            "subcooling_k": round(subcooling_margin(tank.temperature_k, tank.propellant, tank.pressure_pa), 3),
            "valves": {name: valve.open for name, valve in self._valves[tank_id].items()},
            "operational_authority": False,
        }

    @property
    def all_tanks_status(self) -> dict:
        return {tank_id: self.get_tank_status(tank_id) for tank_id in self._tanks}


P_MIN_PA = 1_000.0
