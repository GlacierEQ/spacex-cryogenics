"""Predictive boil-off and multi-tank balance simulation.

This module predicts local digital-twin states and emits review plans.  It does
not actuate valves or claim operational launch-vehicle authority.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from alpha.thermodynamics import PROPELLANTS, Propellant

STEFAN_BOLTZMANN = 5.670374419e-8


def _propellant(name: str) -> Propellant:
    normalized = name.strip().upper()
    aliases = {"LOX": Propellant.LOX, "LCH4": Propellant.LCH4, "CH4": Propellant.LCH4, "LH2": Propellant.LH2}
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported propellant: {name}") from exc


@dataclass(frozen=True)
class CryoTank:
    tank_id: str
    propellant: str
    volume_m3: float
    fill_percent: float
    temperature_k: float
    pressure_pa: float
    solar_exposure_factor: float = 0.5
    insulation_u_w_m2k: float = 0.01

    def __post_init__(self) -> None:
        if not self.tank_id.strip():
            raise ValueError("tank_id is required")
        _propellant(self.propellant)
        if not math.isfinite(self.volume_m3) or self.volume_m3 <= 0:
            raise ValueError("volume_m3 must be finite and > 0")
        if not 0.0 <= self.fill_percent <= 1.0:
            raise ValueError("fill_percent must be in [0, 1]")
        if self.temperature_k <= 0 or self.pressure_pa <= 0:
            raise ValueError("temperature and pressure must be > 0")
        if not 0.0 <= self.solar_exposure_factor <= 1.0:
            raise ValueError("solar_exposure_factor must be in [0, 1]")
        if self.insulation_u_w_m2k < 0:
            raise ValueError("insulation_u_w_m2k must be >= 0")

    @property
    def properties(self):
        return PROPELLANTS[_propellant(self.propellant)]

    @property
    def liquid_mass_kg(self) -> float:
        return self.fill_percent * self.volume_m3 * self.properties.density_liquid_kg_m3

    @property
    def ullage_volume_m3(self) -> float:
        return (1.0 - self.fill_percent) * self.volume_m3

    @property
    def boil_off_rate_kgs(self) -> float:
        return max(0.0, self._heat_input_watts()) / self.properties.latent_heat_jkg

    def _heat_input_watts(self) -> float:
        area = self._surface_area_m2()
        conduction = area * self.insulation_u_w_m2k * max(0.0, 300.0 - self.temperature_k)
        solar = area * self.solar_exposure_factor * 1361.0 * 0.10
        radiation = STEFAN_BOLTZMANN * area * 0.05 * max(0.0, 300.0**4 - self.temperature_k**4)
        return conduction + solar + radiation

    def _surface_area_m2(self) -> float:
        radius = (3.0 * self.volume_m3 / (4.0 * math.pi)) ** (1.0 / 3.0)
        return 4.0 * math.pi * radius**2


@dataclass(frozen=True)
class TransferPlan:
    from_tank: str
    to_tank: str
    mass_kg: float
    duration_s: float
    reason: str
    balance_improvement: float
    operational_authority: bool = False


@dataclass(frozen=True)
class PredictedState:
    tank_id: str
    time_s: float
    predicted_fill_percent: float
    predicted_temperature_k: float
    predicted_pressure_pa: float
    boil_off_kg: float


class ThermalModeler:
    """Forward-integrates heat leak, liquid loss, and ideal-gas ullage pressure."""

    def predict_state(self, tank: CryoTank, time_s: float, dt: float = 60.0) -> PredictedState:
        if time_s < 0 or dt <= 0 or not math.isfinite(time_s) or not math.isfinite(dt):
            raise ValueError("time_s must be >= 0 and dt must be > 0")
        props = tank.properties
        fill = tank.fill_percent
        temp = tank.temperature_k
        pressure = tank.pressure_pa
        total_boil = 0.0
        elapsed = 0.0

        while elapsed < time_s and fill > 0.0:
            step = min(dt, time_s - elapsed)
            area = tank._surface_area_m2()
            heat = (
                area * tank.insulation_u_w_m2k * max(0.0, 300.0 - temp)
                + area * tank.solar_exposure_factor * 1361.0 * 0.10
                + STEFAN_BOLTZMANN * area * 0.05 * max(0.0, 300.0**4 - temp**4)
            )
            boil_mass = heat / props.latent_heat_jkg * step
            liquid_mass = fill * tank.volume_m3 * props.density_liquid_kg_m3
            actual_boil = min(liquid_mass, boil_mass)
            total_boil += actual_boil
            liquid_mass -= actual_boil
            fill = liquid_mass / (tank.volume_m3 * props.density_liquid_kg_m3)
            ullage = max((1.0 - fill) * tank.volume_m3, 1e-9)

            # Sensible heating is limited to the remaining liquid; phase change
            # already consumes the dominant latent-heat term.
            sensible_fraction = 0.02
            if liquid_mass > 0:
                temp += sensible_fraction * heat * step / (liquid_mass * props.cp_liquid_j_kg_k)

            vapor_mass = max(0.0, pressure * tank.ullage_volume_m3 / (props.specific_gas_constant_j_kg_k * tank.temperature_k)) + total_boil
            pressure = vapor_mass * props.specific_gas_constant_j_kg_k * temp / ullage
            elapsed += step

        return PredictedState(tank.tank_id, time_s, fill, temp, pressure, total_boil)


class BalancePredictor:
    def __init__(self, imbalance_threshold: float = 0.05, transfer_flow_kg_s: float = 50.0):
        if not 0.0 < imbalance_threshold < 1.0 or transfer_flow_kg_s <= 0:
            raise ValueError("invalid predictor thresholds")
        self.imbalance_threshold = imbalance_threshold
        self.transfer_flow_kg_s = transfer_flow_kg_s

    def compute_imbalance(self, tanks: list[CryoTank]) -> dict:
        if not tanks:
            return {"imbalance": 0.0, "max_diff": 0.0, "tanks": {}}
        fills = {tank.tank_id: tank.fill_percent for tank in tanks}
        mean_fill = sum(fills.values()) / len(fills)
        fullest = max(fills, key=fills.get)
        emptiest = min(fills, key=fills.get)
        spread = fills[fullest] - fills[emptiest]
        return {
            "imbalance": spread,
            "max_diff": spread,
            "mean_fill": mean_fill,
            "fullest_tank": fullest,
            "emptiest_tank": emptiest,
            # Compatibility names retained, now with unambiguous semantics.
            "worst_tank": fullest,
            "best_tank": emptiest,
            "tanks": fills,
        }

    def predict_imbalance_at(self, tanks: list[CryoTank], modeler: ThermalModeler, time_s: float) -> dict:
        predicted = {tank.tank_id: modeler.predict_state(tank, time_s).predicted_fill_percent for tank in tanks}
        if not predicted:
            return {"time_s": time_s, "imbalance": 0.0, "predicted_fills": {}, "exceeds_threshold": False}
        spread = max(predicted.values()) - min(predicted.values())
        return {"time_s": time_s, "imbalance": spread, "predicted_fills": predicted, "exceeds_threshold": spread > self.imbalance_threshold}

    def plan_transfer(self, tanks: list[CryoTank]) -> Optional[TransferPlan]:
        state = self.compute_imbalance(tanks)
        if state["imbalance"] <= self.imbalance_threshold:
            return None
        source_id, destination_id = state["fullest_tank"], state["emptiest_tank"]
        source = next(t for t in tanks if t.tank_id == source_id)
        destination = next(t for t in tanks if t.tank_id == destination_id)
        if _propellant(source.propellant) is not _propellant(destination.propellant):
            return None

        props = source.properties
        source_excess_fraction = max(0.0, (source.fill_percent - destination.fill_percent) / 2.0)
        source_excess_mass = source_excess_fraction * source.volume_m3 * props.density_liquid_kg_m3
        destination_capacity_mass = (1.0 - destination.fill_percent) * destination.volume_m3 * props.density_liquid_kg_m3
        transfer_mass = min(source_excess_mass, destination_capacity_mass)
        if transfer_mass <= 0.0:
            return None
        duration = transfer_mass / self.transfer_flow_kg_s
        return TransferPlan(
            source_id,
            destination_id,
            transfer_mass,
            duration,
            f"fill spread {state['imbalance']:.4f} exceeds threshold {self.imbalance_threshold:.4f}",
            min(state["imbalance"], 2.0 * transfer_mass / (source.volume_m3 * props.density_liquid_kg_m3)),
        )


class PredictiveBoiloffManager:
    def __init__(self):
        self.modeler = ThermalModeler()
        self.balance_predictor = BalancePredictor()

    def analyze_tanks(self, tanks: list[CryoTank]) -> dict:
        balance = self.balance_predictor.compute_imbalance(tanks)
        predictions = {
            f"{horizon // 60}min": self.balance_predictor.predict_imbalance_at(tanks, self.modeler, horizon)
            for horizon in (1800, 3600, 7200)
        }
        plan = self.balance_predictor.plan_transfer(tanks)
        return {
            "current_balance": balance,
            "predictions": predictions,
            "transfer_plan": None if plan is None else {
                "from": plan.from_tank,
                "to": plan.to_tank,
                "mass_kg": plan.mass_kg,
                "duration_s": plan.duration_s,
                "reason": plan.reason,
                "operational_authority": False,
            },
            "total_boil_off_kgs": sum(t.boil_off_rate_kgs for t in tanks),
            "operational_authority": False,
        }

    def get_boiloff_report(self, tanks: list[CryoTank]) -> dict:
        total_mass = sum(t.liquid_mass_kg for t in tanks)
        total_rate = sum(t.boil_off_rate_kgs for t in tanks)
        hours_to_5pct = (total_mass * 0.05 / total_rate / 3600.0) if total_rate > 0 else None
        return {
            "total_propellant_kg": total_mass,
            "total_boil_off_kgs": total_rate,
            "boil_off_rate_per_hour": total_rate * 3600.0,
            "time_to_5pct_loss_hours": hours_to_5pct,
            "tank_count": len(tanks),
            "tanks": {t.tank_id: {"fill": t.fill_percent, "temp_k": t.temperature_k, "boil_rate_kgs": t.boil_off_rate_kgs} for t in tanks},
            "operational_authority": False,
        }
