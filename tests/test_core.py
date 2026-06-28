"""Tests for spacex-cryogenics — the cold that holds the fire.

3 tests. Because propellant doesn't wait.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import math
from alpha.thermodynamics import (
    TankState, Propellant, PROPELLANTS, boil_off_rate,
    saturation_pressure, clausius_clapeyron_slope
)
from omega.predictive_boiloff import CryoTank, ThermalModeler, BalancePredictor


def test_lox_properties():
    lox = PROPELLANTS[Propellant.LOX]
    assert lox.boiling_point_k == 90.19

def test_boil_off_positive():
    tank = TankState(
        propellant=Propellant.LOX, fill_percent=0.5,
        temperature_k=90.19, pressure_pa=101325,
        ullage_volume_m3=1.0, liquid_volume_m3=1.0, total_volume_m3=2.0
    )
    rate = boil_off_rate(tank, 100.0)
    assert rate > 0

def test_thermal_modeler_prediction():
    tank = CryoTank(tank_id="t1", propellant="LOX", volume_m3=100,
                    fill_percent=0.8, temperature_k=90.19, pressure_pa=101325)
    modeler = ThermalModeler()
    predicted = modeler.predict_state(tank, 3600)
    assert predicted.predicted_fill_percent <= 0.8


# LOX boils at 90.19 K.
# LCH4 boils at 111.65 K.
# The difference is the margin between success and failure.
CRYO_MARGIN = 111.65 - 90.19
assert abs(CRYO_MARGIN - 21.46) < 0.01, "The margin is precise"
