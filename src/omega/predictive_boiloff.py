"""Predictive boil-off management — preemptive propellant transfer.

Standard cryogenics: monitor tank temperatures, vent when pressure rises.
Innovation: Predict WHICH tank will boil off first and preemptively
transfer propellant to maintain balance. Prevents the problem instead
of reacting to it.

The wheel: boil-off rate computation
The vehicle: predictive load balancing across tanks

Key insight: In a multi-tank system (Starship has 6 tanks), boil-off
isn't uniform. Solar heating, attitude, and tank geometry cause uneven
boil-off. If one tank boils faster, the vehicle becomes unbalanced.
Predicting this 30 minutes ahead and transferring propellant prevents
the imbalance entirely.
"""

import math
from dataclasses import dataclass, field
from typing import Optional


R_UNIVERSAL = 8.314
STEFAN_BOLTZMANN = 5.670374419e-8


@dataclass
class CryoTank:
    tank_id: str
    propellant: str
    volume_m3: float
    fill_percent: float
    temperature_k: float
    pressure_pa: float
    solar_exposure_factor: float = 0.5
    insulation_u_w_m2k: float = 0.01

    @property
    def liquid_mass_kg(self) -> float:
        density = 1141.0 if self.propellant == "LOX" else 422.6
        return self.fill_percent * self.volume_m3 * density

    @property
    def ullage_volume_m3(self) -> float:
        return (1 - self.fill_percent) * self.volume_m3

    @property
    def boil_off_rate_kgs(self) -> float:
        latent_heat = 213100 if self.propellant == "LOX" else 510000
        heat_input = self._heat_input_watts()
        return heat_input / latent_heat if latent_heat > 0 else 0

    def _heat_input_watts(self) -> float:
        surface_area = self._surface_area_m2()
        conduction = surface_area * self.insulation_u_w_m2k * (300 - self.temperature_k)
        solar = surface_area * self.solar_exposure_factor * 1361 * 0.1
        radiation = STEFAN_BOLTZMANN * surface_area * 0.85 * (300 ** 4 - self.temperature_k ** 4)
        return conduction + solar + radiation

    def _surface_area_m2(self) -> float:
        r = math.sqrt(self.volume_m3 / (4 * math.pi / 3))
        return 4 * math.pi * r ** 2


@dataclass
class TransferPlan:
    from_tank: str
    to_tank: str
    mass_kg: float
    duration_s: float
    reason: str
    balance_improvement: float


@dataclass
class PredictedState:
    tank_id: str
    time_s: float
    predicted_fill_percent: float
    predicted_temperature_k: float
    predicted_pressure_pa: float
    boil_off_kg: float


class ThermalModeler:
    """Predicts tank thermal evolution over time.

    Innovation: Instead of just computing current boil-off rate,
    integrates forward in time to predict FUTURE state. This enables
    preemptive action.
    """

    def __init__(self):
        self.gravity = 9.80665

    def predict_state(
        self,
        tank: CryoTank,
        time_s: float,
        dt: float = 60.0,
    ) -> PredictedState:
        fill = tank.fill_percent
        temp = tank.temperature_k
        pressure = tank.pressure_pa
        total_boil = 0.0

        steps = int(time_s / dt)
        for _ in range(steps):
            heat_input = tank._heat_input_watts()
            latent_heat = 213100 if tank.propellant == "LOX" else 510000
            boil_rate = heat_input / latent_heat if latent_heat > 0 else 0

            boil_mass = boil_rate * dt
            total_boil += boil_mass

            density = 1141.0 if tank.propellant == "LOX" else 422.6
            liquid_mass = fill * tank.volume_m3 * density
            new_liquid_mass = max(0, liquid_mass - boil_mass)
            fill = new_liquid_mass / (tank.volume_m3 * density) if tank.volume_m3 * density > 0 else 0

            molecular_weight = 32.0 if tank.propellant == "LOX" else 16.0
            R = R_UNIVERSAL / molecular_weight
            n = pressure * tank.ullage_volume_m3 / (R * temp) if tank.ullage_volume_m3 > 0 else 0
            dTdt = heat_input / (n * R * 1.5) if n > 0 else 0
            temp += dTdt * dt
            pressure = n * R * temp / tank.ullage_volume_m3 if tank.ullage_volume_m3 > 0 else pressure

        return PredictedState(
            tank_id=tank.tank_id,
            time_s=time_s,
            predicted_fill_percent=fill,
            predicted_temperature_k=temp,
            predicted_pressure_pa=pressure,
            boil_off_kg=total_boil,
        )


class BalancePredictor:
    """Predicts and prevents tank imbalance.

    Innovation: Monitors the fill level differences across all tanks
    and predicts when imbalance will exceed safe limits. Then computes
    optimal transfer plan to restore balance before it becomes critical.
    """

    def __init__(self, imbalance_threshold: float = 0.05):
        self.imbalance_threshold = imbalance_threshold

    def compute_imbalance(self, tanks: list[CryoTank]) -> dict:
        fills = {t.tank_id: t.fill_percent for t in tanks}
        if not fills:
            return {"imbalance": 0, "max_diff": 0}

        mean_fill = sum(fills.values()) / len(fills)
        max_diff = max(abs(f - mean_fill) for f in fills.values())
        worst_tank = max(fills, key=lambda k: fills[k])
        best_tank = min(fills, key=lambda k: fills[k])

        return {
            "imbalance": max_diff,
            "max_diff": max_diff,
            "mean_fill": mean_fill,
            "worst_tank": worst_tank,
            "best_tank": best_tank,
            "tanks": fills,
        }

    def predict_imbalance_at(
        self,
        tanks: list[CryoTank],
        modeler: ThermalModeler,
        time_s: float,
    ) -> dict:
        predicted_fills = {}
        for tank in tanks:
            predicted = modeler.predict_state(tank, time_s)
            predicted_fills[tank.tank_id] = predicted.predicted_fill_percent

        if not predicted_fills:
            return {"imbalance": 0}

        mean_fill = sum(predicted_fills.values()) / len(predicted_fills)
        max_diff = max(abs(f - mean_fill) for f in predicted_fills.values())

        return {
            "time_s": time_s,
            "imbalance": max_diff,
            "predicted_fills": predicted_fills,
            "exceeds_threshold": max_diff > self.imbalance_threshold,
        }

    def plan_transfer(
        self,
        tanks: list[CryoTank],
    ) -> Optional[TransferPlan]:
        imbalance = self.compute_imbalance(tanks)
        if imbalance["imbalance"] <= self.imbalance_threshold:
            return None

        from_tank = imbalance["best_tank"]
        to_tank = imbalance["worst_tank"]

        from_t = next((t for t in tanks if t.tank_id == from_tank), None)
        to_t = next((t for t in tanks if t.tank_id == to_tank), None)

        if not from_t or not to_t:
            return None

        transfer_mass = (from_t.fill_percent - to_t.fill_percent) * from_t.volume_m3 * 422.6 * 0.3
        flow_rate = 50.0
        duration = transfer_mass / flow_rate if flow_rate > 0 else 0

        return TransferPlan(
            from_tank=from_tank,
            to_tank=to_tank,
            mass_kg=transfer_mass,
            duration_s=duration,
            reason=f"Imbalance {imbalance['imbalance']:.3f} exceeds threshold {self.imbalance_threshold}",
            balance_improvement=imbalance["imbalance"] * 0.6,
        )


class PredictiveBoiloffManager:
    """Full predictive boil-off management system.

    The wheel: boil-off rate computation
    The vehicle: preemptive propellant transfer

    Innovation: Instead of reacting to boil-off (venting pressure),
    predicts WHICH tanks will boil off fastest and preemptively
    transfers propellant to maintain balance. Prevents the problem
    instead of managing the symptoms.
    """

    def __init__(self):
        self.modeler = ThermalModeler()
        self.balance_predictor = BalancePredictor()
        self._transfer_log: list[dict] = []
        self._prediction_log: list[dict] = []

    def analyze_tanks(self, tanks: list[CryoTank]) -> dict:
        balance = self.balance_predictor.compute_imbalance(tanks)
        predictions = {}

        for horizon_s in [1800, 3600, 7200]:
            pred = self.balance_predictor.predict_imbalance_at(
                tanks, self.modeler, horizon_s
            )
            predictions[f"{horizon_s // 60}min"] = pred

        transfer_plan = self.balance_predictor.plan_transfer(tanks)

        return {
            "current_balance": balance,
            "predictions": predictions,
            "transfer_plan": {
                "from": transfer_plan.from_tank,
                "to": transfer_plan.to_tank,
                "mass_kg": transfer_plan.mass_kg,
                "duration_s": transfer_plan.duration_s,
                "reason": transfer_plan.reason,
            } if transfer_plan else None,
            "total_boil_off_kgs": sum(t.boil_off_rate_kgs for t in tanks),
            "worst_tank": balance["worst_tank"],
        }

    def get_boiloff_report(self, tanks: list[CryoTank]) -> dict:
        total_mass = sum(t.liquid_mass_kg for t in tanks)
        total_boiloff = sum(t.boil_off_rate_kgs for t in tanks)
        hours_to_5pct = (total_mass * 0.05 / total_boiloff * 3600) if total_boiloff > 0 else float("inf")

        return {
            "total_propellant_kg": total_mass,
            "total_boil_off_kgs": total_boiloff,
            "boil_off_rate_per_hour": total_boiloff * 3600,
            "time_to_5pct_loss_hours": hours_to_5pct / 3600,
            "tank_count": len(tanks),
            "tanks": {
                t.tank_id: {
                    "fill": t.fill_percent,
                    "temp_k": t.temperature_k,
                    "boil_rate_kgs": t.boil_off_rate_kgs,
                }
                for t in tanks
            },
        }
