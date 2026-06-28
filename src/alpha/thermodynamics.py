"""Cryogenic propellant thermodynamics — LOX/LCH4 phase behavior, heat transfer.

Models tank thermal states, boil-off rates, and pressurization requirements.
Uses ideal gas and Clausius-Clapeyron for vapor-liquid equilibrium.
Pure math, zero external dependencies.

LOX boils at 90.19 K (-182.96 °C). That's colder than Pluto's surface sometimes.
LCH4 boils at 111.65 K (-161.50 °C). That's colder than Titan's lakes.

The margin between them is 21.46 K.
That margin is the difference between a rocket that works and a rocket that doesn't.
We measure it to the hundredth of a degree.
"""

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class Propellant(Enum):
    LOX = auto()
    LCH4 = auto()
    LH2 = auto()
    RP1 = auto()


@dataclass
class FluidProperties:
    name: str
    boiling_point_k: float
    critical_temp_k: float
    critical_pressure_pa: float
    latent_heat_jkg: float
    density_liquid: float
    density_gas: float
    cp_liquid: float
    molecular_weight: float

    @property
    def acentric_factor(self) -> float:
        return 0.0


PROPELLANTS = {
    Propellant.LOX: FluidProperties(
        name="LOX", boiling_point_k=90.19, critical_temp_k=154.58,
        critical_pressure_pa=5.043e6, latent_heat_jkg=213100,
        density_liquid=1141.0, density_gas=4.0, cp_liquid=1700.0,
        molecular_weight=32.0,
    ),
    Propellant.LCH4: FluidProperties(
        name="LCH4", boiling_point_k=111.65, critical_temp_k=190.56,
        critical_pressure_pa=4.599e6, latent_heat_jkg=510000,
        density_liquid=422.6, density_gas=0.657, cp_liquid=3480.0,
        molecular_weight=16.0,
    ),
    Propellant.LH2: FluidProperties(
        name="LH2", boiling_point_k=20.28, critical_temp_k=32.94,
        critical_pressure_pa=1.286e6, latent_heat_jkg=446000,
        density_liquid=70.8, density_gas=0.089, cp_liquid=9690.0,
        molecular_weight=2.0,
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

    @property
    def liquid_mass(self) -> float:
        props = PROPELLANTS[self.propellant]
        return self.liquid_volume_m3 * props.density_liquid

    @property
    def gas_mass(self) -> float:
        props = PROPELLANTS[self.propellant]
        R = 8.314 / props.molecular_weight
        return self.pressure_pa * self.ullage_volume_m3 / (R * self.temperature_k)

    @property
    def quality(self) -> float:
        """Mass fraction that is vapor."""
        lm = self.liquid_mass
        gm = self.gas_mass
        if lm + gm <= 0:
            return 0.0
        return gm / (lm + gm)


@dataclass
class HeatTransfer:
    area_m2: float
    conduction_w_m2k: float
    external_temp_k: float
    internal_temp_k: float
    radiation_emissivity: float = 0.85

    @property
    def conduction_watts(self) -> float:
        return self.area_m2 * self.conduction_w_m2k * (self.external_temp_k - self.internal_temp_k)

    @property
    def radiation_watts(self) -> float:
        sigma = 5.670374419e-8
        return (self.radiation_emissivity * sigma * self.area_m2 *
                (self.external_temp_k ** 4 - self.internal_temp_k ** 4))


def clausius_clapeyron_slope(props: FluidProperties) -> float:
    R = 8.314
    return props.latent_heat_jkg * props.molecular_weight / R


def saturation_pressure(props: FluidProperties, temp_k: float) -> float:
    """Antoine-like vapor pressure estimation."""
    T_boil = props.boiling_point_k
    T_crit = props.critical_temp_k
    P_crit = props.critical_pressure_pa

    if temp_k >= T_crit:
        return P_crit

    slope = clausius_clapeyron_slope(props)
    ln_ratio = slope * (1.0 / T_boil - 1.0 / temp_k)
    return P_crit * math.exp(ln_ratio) * 0.5


def boil_off_rate(
    tank: TankState,
    heat_input_watts: float,
) -> float:
    """Mass boil-off rate in kg/s."""
    props = PROPELLANTS[tank.propellant]
    if heat_input_watts <= 0:
        return 0.0
    return heat_input_watts / props.latent_heat_jkg


def pressurization_rate(
    tank: TankState,
    heat_input_watts: float,
) -> float:
    """Pressure rise rate in Pa/s from heat leak."""
    props = PROPELLANTS[tank.propellant]
    R = 8.314 / props.molecular_weight

    if tank.ullage_volume_m3 <= 0:
        return 0.0

    n = tank.pressure_pa * tank.ullage_volume_m3 / (R * tank.temperature_k)
    dTdt = heat_input_watts / (n * R * 1.5)
    dPdt = n * R * dTdt / tank.ullage_volume_m3

    return dPdt


def ullage_pressurization(
    tank: TankState,
    target_pressure_pa: float,
) -> float:
    """Gas mass needed to reach target pressure."""
    props = PROPELLANTS[tank.propellant]
    R = 8.314 / props.molecular_weight

    if tank.ullage_volume_m3 <= 0:
        return 0.0

    n_current = tank.pressure_pa * tank.ullage_volume_m3 / (R * tank.temperature_k)
    n_target = target_pressure_pa * tank.ullage_volume_m3 / (R * tank.temperature_k)

    delta_n = n_target - n_current
    return delta_n * props.molecular_weight


def thermal_time_constant(
    mass_kg: float,
    cp: float,
    area_m2: float,
    u_w_m2k: float,
) -> float:
    """Thermal time constant for tank equilibration."""
    if area_m2 <= 0 or u_w_m2k <= 0:
        return float("inf")
    return mass_kg * cp / (area_m2 * u_w_m2k)


def tank_drain_time(
    fill_percent: float,
    total_volume_m3: float,
    flow_rate_kgs: float,
    propellant: Propellant,
) -> float:
    """Time to drain tank to empty."""
    props = PROPELLANTS[propellant]
    mass = fill_percent * total_volume_m3 * props.density_liquid
    if flow_rate_kgs <= 0:
        return float("inf")
    return mass / flow_rate_kgs


def subcooling_margin(temperature_k: float, propellant: Propellant) -> float:
    """Degrees of subcooling below boiling point."""
    props = PROPELLANTS[propellant]
    return props.boiling_point_k - temperature_k
