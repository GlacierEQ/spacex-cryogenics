"""Deterministic cryogenic thermodynamics for a local tank digital twin.

The model is deliberately review-grade rather than flight-certified. It uses a
Clausius-Clapeyron approximation anchored at the normal boiling point, simple
heat-leak balances, ideal-gas ullage calculations, and explicit SI units.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto

R_UNIVERSAL_J_MOL_K = 8.31446261815324
P_ATM_PA = 101_325.0
STEFAN_BOLTZMANN = 5.670374419e-8


class Propellant(Enum):
    LOX = auto()
    LCH4 = auto()
    LH2 = auto()


@dataclass(frozen=True)
class FluidProperties:
    name: str
    boiling_point_k: float
    critical_temp_k: float
    critical_pressure_pa: float
    latent_heat_jkg: float
    density_liquid_kg_m3: float
    cp_liquid_j_kg_k: float
    molar_mass_kg_mol: float

    def __post_init__(self) -> None:
        for field_name in (
            "boiling_point_k", "critical_temp_k", "critical_pressure_pa",
            "latent_heat_jkg", "density_liquid_kg_m3", "cp_liquid_j_kg_k",
            "molar_mass_kg_mol",
        ):
            value = float(getattr(self, field_name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{field_name} must be finite and > 0")

    @property
    def molecular_weight(self) -> float:
        """Compatibility alias: kg/mol, not g/mol."""
        return self.molar_mass_kg_mol

    @property
    def density_liquid(self) -> float:
        return self.density_liquid_kg_m3

    @property
    def cp_liquid(self) -> float:
        return self.cp_liquid_j_kg_k

    @property
    def specific_gas_constant_j_kg_k(self) -> float:
        return R_UNIVERSAL_J_MOL_K / self.molar_mass_kg_mol

    @property
    def latent_heat_j_mol(self) -> float:
        return self.latent_heat_jkg * self.molar_mass_kg_mol


PROPELLANTS = {
    Propellant.LOX: FluidProperties(
        "LOX", 90.19, 154.58, 5.043e6, 213_100.0, 1141.0, 1700.0, 0.031_998,
    ),
    Propellant.LCH4: FluidProperties(
        "LCH4", 111.65, 190.56, 4.599e6, 510_000.0, 422.6, 3480.0, 0.016_043,
    ),
    Propellant.LH2: FluidProperties(
        "LH2", 20.28, 32.94, 1.286e6, 446_000.0, 70.8, 9690.0, 0.002_016,
    ),
}


@dataclass
class TankState:
    propellant: Propellant
    fill_percent: float
    temperature_k: float
    pressure_pa: float
    ullage_volume_m3: float
    liquid_volume_m3: float
    total_volume_m3: float

    def validate(self) -> None:
        if self.propellant not in PROPELLANTS:
            raise ValueError("unsupported propellant")
        for name in ("fill_percent", "temperature_k", "pressure_pa", "ullage_volume_m3", "liquid_volume_m3", "total_volume_m3"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not 0.0 <= self.fill_percent <= 1.0:
            raise ValueError("fill_percent must be in [0, 1]")
        if self.temperature_k <= 0.0 or self.pressure_pa <= 0.0 or self.total_volume_m3 <= 0.0:
            raise ValueError("temperature, pressure and total volume must be > 0")
        if self.ullage_volume_m3 < 0.0 or self.liquid_volume_m3 < 0.0:
            raise ValueError("tank volumes cannot be negative")
        if self.ullage_volume_m3 + self.liquid_volume_m3 > self.total_volume_m3 * 1.000001:
            raise ValueError("liquid + ullage exceeds total tank volume")

    @property
    def liquid_mass(self) -> float:
        self.validate()
        return self.liquid_volume_m3 * PROPELLANTS[self.propellant].density_liquid_kg_m3

    @property
    def gas_mass(self) -> float:
        self.validate()
        props = PROPELLANTS[self.propellant]
        if self.ullage_volume_m3 == 0.0:
            return 0.0
        return self.pressure_pa * self.ullage_volume_m3 / (
            props.specific_gas_constant_j_kg_k * self.temperature_k
        )

    @property
    def quality(self) -> float:
        liquid, gas = self.liquid_mass, self.gas_mass
        return gas / (liquid + gas) if liquid + gas > 0.0 else 0.0


@dataclass(frozen=True)
class HeatTransfer:
    area_m2: float
    conduction_w_m2k: float
    external_temp_k: float
    internal_temp_k: float
    radiation_emissivity: float = 0.05

    def __post_init__(self) -> None:
        if self.area_m2 <= 0 or self.conduction_w_m2k < 0:
            raise ValueError("invalid heat-transfer geometry")
        if self.external_temp_k <= 0 or self.internal_temp_k <= 0:
            raise ValueError("temperatures must be > 0 K")
        if not 0.0 <= self.radiation_emissivity <= 1.0:
            raise ValueError("radiation_emissivity must be in [0, 1]")

    @property
    def conduction_watts(self) -> float:
        return self.area_m2 * self.conduction_w_m2k * (self.external_temp_k - self.internal_temp_k)

    @property
    def radiation_watts(self) -> float:
        return self.radiation_emissivity * STEFAN_BOLTZMANN * self.area_m2 * (
            self.external_temp_k**4 - self.internal_temp_k**4
        )

    @property
    def net_heat_into_tank_w(self) -> float:
        return self.conduction_watts + self.radiation_watts


def clausius_clapeyron_slope(props: FluidProperties) -> float:
    """Compatibility helper returning L_molar/R in kelvin."""
    return props.latent_heat_j_mol / R_UNIVERSAL_J_MOL_K


def saturation_pressure(props: FluidProperties, temp_k: float) -> float:
    """Approximate saturation pressure in Pa, anchored at the normal boiling point."""
    temp_k = float(temp_k)
    if not math.isfinite(temp_k) or temp_k <= 0.0:
        raise ValueError("temp_k must be finite and > 0")
    if temp_k >= props.critical_temp_k:
        return props.critical_pressure_pa
    exponent = clausius_clapeyron_slope(props) * (
        1.0 / props.boiling_point_k - 1.0 / temp_k
    )
    return min(props.critical_pressure_pa, P_ATM_PA * math.exp(exponent))


def saturation_temperature(props: FluidProperties, pressure_pa: float) -> float:
    pressure_pa = float(pressure_pa)
    if not math.isfinite(pressure_pa) or pressure_pa <= 0.0:
        raise ValueError("pressure_pa must be finite and > 0")
    if pressure_pa >= props.critical_pressure_pa:
        return props.critical_temp_k
    inv_t = 1.0 / props.boiling_point_k - (
        R_UNIVERSAL_J_MOL_K / props.latent_heat_j_mol
    ) * math.log(pressure_pa / P_ATM_PA)
    if inv_t <= 0.0:
        raise ValueError("pressure outside approximation domain")
    return 1.0 / inv_t


def boil_off_rate(tank: TankState, heat_input_watts: float) -> float:
    tank.validate()
    heat_input_watts = float(heat_input_watts)
    if not math.isfinite(heat_input_watts):
        raise ValueError("heat_input_watts must be finite")
    return max(0.0, heat_input_watts) / PROPELLANTS[tank.propellant].latent_heat_jkg


def pressurization_rate(tank: TankState, heat_input_watts: float) -> float:
    """Idealized dP/dt from vapor generated by a heat leak, Pa/s."""
    tank.validate()
    if tank.ullage_volume_m3 <= 0.0:
        return 0.0
    props = PROPELLANTS[tank.propellant]
    vapor_rate_kg_s = boil_off_rate(tank, heat_input_watts)
    return vapor_rate_kg_s * props.specific_gas_constant_j_kg_k * tank.temperature_k / tank.ullage_volume_m3


def ullage_pressurization(tank: TankState, target_pressure_pa: float) -> float:
    """Additional ideal-gas mass in kg required to reach target pressure."""
    tank.validate()
    target_pressure_pa = float(target_pressure_pa)
    if not math.isfinite(target_pressure_pa) or target_pressure_pa <= 0.0:
        raise ValueError("target_pressure_pa must be finite and > 0")
    if target_pressure_pa <= tank.pressure_pa or tank.ullage_volume_m3 <= 0.0:
        return 0.0
    props = PROPELLANTS[tank.propellant]
    return (
        (target_pressure_pa - tank.pressure_pa)
        * tank.ullage_volume_m3
        / (props.specific_gas_constant_j_kg_k * tank.temperature_k)
    )


def thermal_time_constant(mass_kg: float, cp: float, area_m2: float, u_w_m2k: float) -> float:
    if mass_kg < 0 or cp <= 0:
        raise ValueError("mass must be >= 0 and cp > 0")
    if area_m2 <= 0 or u_w_m2k <= 0:
        return float("inf")
    return mass_kg * cp / (area_m2 * u_w_m2k)


def tank_drain_time(fill_percent: float, total_volume_m3: float, flow_rate_kgs: float, propellant: Propellant) -> float:
    if not 0.0 <= fill_percent <= 1.0 or total_volume_m3 <= 0:
        raise ValueError("invalid fill fraction or volume")
    if flow_rate_kgs <= 0:
        return float("inf")
    mass = fill_percent * total_volume_m3 * PROPELLANTS[propellant].density_liquid_kg_m3
    return mass / flow_rate_kgs


def subcooling_margin(temperature_k: float, propellant: Propellant, pressure_pa: float = P_ATM_PA) -> float:
    return saturation_temperature(PROPELLANTS[propellant], pressure_pa) - float(temperature_k)
