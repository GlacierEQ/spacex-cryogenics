"""Tank controller — manages tank pressurization, draining, and thermal control.

Monitors LOX/LCH4 tank states, controls pressurization valves,
manages thermal conditioning, and coordinates propellant loading.
"""

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

from alpha.thermodynamics import (
    Propellant, TankState, HeatTransfer, PROPELLANTS,
    saturation_pressure, boil_off_rate, pressurization_rate,
    ullage_pressurization, subcooling_margin,
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
    def __init__(self):
        self._tanks: dict[str, TankState] = {}
        self._modes: dict[str, TankMode] = {}
        self._valves: dict[str, dict[str, ValveState]] = {}
        self._pressurization_targets: dict[str, float] = {}
        self._event_log: list[dict] = []
        self._alert_callbacks: list[Callable] = []
        self._thermal_loads: dict[str, HeatTransfer] = {}

    def register_tank(self, tank_id: str, state: TankState):
        self._tanks[tank_id] = state
        self._modes[tank_id] = TankMode.IDLE
        self._valves[tank_id] = {
            "fill": ValveState("fill"),
            "drain": ValveState("drain"),
            "pressurize": ValveState("pressurize"),
            "vent": ValveState("vent"),
        }

    def set_thermal_load(self, tank_id: str, heat: HeatTransfer):
        self._thermal_loads[tank_id] = heat

    def set_mode(self, tank_id: str, mode: TankMode) -> bool:
        if tank_id not in self._tanks:
            return False
        old = self._modes[tank_id]
        self._modes[tank_id] = mode
        self._log(tank_id, f"mode: {old.name} -> {mode.name}")
        return True

    def set_valve(self, tank_id: str, valve_name: str, open: bool) -> bool:
        if tank_id not in self._valves:
            return False
        if valve_name not in self._valves[tank_id]:
            return False

        self._valves[tank_id][valve_name].open = open
        self._valves[tank_id][valve_name].last_change = time.time()
        return True

    def set_pressurization_target(self, tank_id: str, target_pa: float):
        self._pressurization_targets[tank_id] = target_pa

    def update(self, dt: float = 1.0) -> list[dict]:
        updates = []
        for tank_id, tank in self._tanks.items():
            mode = self._modes[tank_id]

            if mode == TankMode.THERMAL_CONDITIONING:
                self._apply_thermal(tank_id, dt)

            if mode == TankMode.PRESSURIZING:
                self._apply_pressurization(tank_id, dt)

            if mode == TankMode.DRAINING:
                self._apply_drain(tank_id, dt)

            self._update_state(tank_id, dt)
            self._check_alerts(tank_id)

            updates.append({
                "tank": tank_id,
                "mode": mode.name,
                "pressure_pa": tank.pressure_pa,
                "fill_percent": tank.fill_percent,
                "temperature_k": tank.temperature_k,
            })

        return updates

    def _apply_thermal(self, tank_id: str, dt: float):
        tank = self._tanks[tank_id]
        heat = self._thermal_loads.get(tank_id)
        if not heat:
            return

        props = PROPELLANTS[tank.propellant]
        total_heat = heat.conduction_watts + heat.radiation_watts
        boil = boil_off_rate(tank, total_heat)
        mass_loss = boil * dt

        if mass_loss > 0 and tank.liquid_volume_m3 > 0:
            vol_loss = mass_loss / props.density_liquid
            tank.liquid_volume_m3 = max(0, tank.liquid_volume_m3 - vol_loss)
            tank.ullage_volume_m3 = tank.total_volume_m3 - tank.liquid_volume_m3
            tank.fill_percent = tank.liquid_volume_m3 / tank.total_volume_m3

        tank.pressure_pa = saturation_pressure(props, tank.temperature_k)

    def _apply_pressurization(self, tank_id: str, dt: float):
        tank = self._tanks[tank_id]
        target = self._pressurization_targets.get(tank_id, tank.pressure_pa)

        if tank.pressure_pa < target:
            props = PROPELLANTS[tank.propellant]
            gas_mass = ullage_pressurization(tank, target)
            R = 8.314 / props.molecular_weight
            n = target * tank.ullage_volume_m3 / (R * tank.temperature_k)
            tank.pressure_pa = n * R * tank.temperature_k / tank.ullage_volume_m3

    def _apply_drain(self, tank_id: str, dt: float):
        tank = self._tanks[tank_id]
        props = PROPELLANTS[tank.propellant]

        drain_rate = 100.0
        mass_loss = drain_rate * dt
        vol_loss = mass_loss / props.density_liquid

        if vol_loss > tank.liquid_volume_m3:
            vol_loss = tank.liquid_volume_m3

        tank.liquid_volume_m3 -= vol_loss
        tank.ullage_volume_m3 = tank.total_volume_m3 - tank.liquid_volume_m3
        tank.fill_percent = tank.liquid_volume_m3 / tank.total_volume_m3

    def _update_state(self, tank_id: str, dt: float):
        tank = self._tanks[tank_id]
        props = PROPELLANTS[tank.propellant]

        if tank.pressure_pa < saturation_pressure(props, tank.temperature_k) * 0.9:
            tank.pressure_pa = saturation_pressure(props, tank.temperature_k)

    def _check_alerts(self, tank_id: str):
        tank = self._tanks[tank_id]
        props = PROPELLANTS[tank.propellant]

        margin = subcooling_margin(tank.temperature_k, tank.propellant)
        if margin < 1.0:
            for cb in self._alert_callbacks:
                cb({"tank": tank_id, "alert": "LOW_SUBCOOLING", "margin_k": margin})

        target = self._pressurization_targets.get(tank_id)
        if target and tank.pressure_pa > target * 1.1:
            for cb in self._alert_callbacks:
                cb({"tank": tank_id, "alert": "OVER_PRESSURE", "pressure": tank.pressure_pa})

    def on_alert(self, callback: Callable):
        self._alert_callbacks.append(callback)

    def _log(self, tank_id: str, event: str):
        self._event_log.append({"time": time.time(), "tank": tank_id, "event": event})

    def get_tank_status(self, tank_id: str) -> Optional[dict]:
        tank = self._tanks.get(tank_id)
        if not tank:
            return None

        props = PROPELLANTS[tank.propellant]
        return {
            "tank_id": tank_id,
            "propellant": props.name,
            "mode": self._modes[tank_id].name,
            "fill_percent": round(tank.fill_percent * 100, 1),
            "pressure_kpa": round(tank.pressure_pa / 1000, 1),
            "temperature_k": round(tank.temperature_k, 2),
            "liquid_mass_kg": round(tank.liquid_mass, 1),
            "subcooling_k": round(subcooling_margin(tank.temperature_k, tank.propellant), 2),
            "valves": {
                name: v.open for name, v in self._valves.get(tank_id, {}).items()
            },
        }

    @property
    def all_tanks_status(self) -> dict:
        return {tid: self.get_tank_status(tid) for tid in self._tanks}
