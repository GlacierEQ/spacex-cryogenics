from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alpha.thermodynamics import (
    P_ATM_PA,
    PROPELLANTS,
    Propellant,
    TankState,
    saturation_pressure,
    saturation_temperature,
    ullage_pressurization,
)
from cryo_engine import CryogenicDigitalTwin, SensorFrame, evaluate_payload
from omega.predictive_boiloff import BalancePredictor, CryoTank, PredictiveBoiloffManager, ThermalModeler
from omega.tank_controller import TankMode


def test_normal_boiling_points_are_anchored_to_one_atmosphere():
    for propellant in (Propellant.LOX, Propellant.LCH4, Propellant.LH2):
        props = PROPELLANTS[propellant]
        assert saturation_pressure(props, props.boiling_point_k) == pytest.approx(P_ATM_PA, rel=1e-12)
        assert saturation_temperature(props, P_ATM_PA) == pytest.approx(props.boiling_point_k, rel=1e-12)


def test_specific_gas_constants_are_si_scale():
    assert PROPELLANTS[Propellant.LOX].specific_gas_constant_j_kg_k == pytest.approx(259.84, rel=0.01)
    assert PROPELLANTS[Propellant.LCH4].specific_gas_constant_j_kg_k == pytest.approx(518.3, rel=0.01)


def test_saturation_pressure_is_monotonic_below_critical_point():
    lox = PROPELLANTS[Propellant.LOX]
    assert saturation_pressure(lox, 85.0) < saturation_pressure(lox, 90.19) < saturation_pressure(lox, 100.0)


def test_ullage_pressurant_mass_has_physical_order_of_magnitude():
    tank = TankState(Propellant.LOX, 0.5, 90.19, P_ATM_PA, 5.0, 5.0, 10.0)
    added = ullage_pressurization(tank, 200_000.0)
    assert 1.0 < added < 100.0


def test_transfer_moves_from_fuller_to_emptier_same_fluid():
    tanks = [
        CryoTank("full", "LOX", 10.0, 0.90, 88.0, P_ATM_PA),
        CryoTank("empty", "LOX", 10.0, 0.60, 88.0, P_ATM_PA),
    ]
    plan = BalancePredictor(imbalance_threshold=0.05).plan_transfer(tanks)
    assert plan is not None
    assert plan.from_tank == "full"
    assert plan.to_tank == "empty"
    assert plan.mass_kg > 0
    assert plan.operational_authority is False


def test_transfer_refuses_cross_propellant_plan():
    tanks = [
        CryoTank("lox", "LOX", 10.0, 0.90, 88.0, P_ATM_PA),
        CryoTank("methane", "LCH4", 10.0, 0.60, 109.0, P_ATM_PA),
    ]
    assert BalancePredictor(imbalance_threshold=0.05).plan_transfer(tanks) is None


def test_predictive_time_to_loss_is_reported_in_hours_not_seconds():
    tank = CryoTank("lox", "LOX", 10.0, 0.8, 88.0, P_ATM_PA)
    report = PredictiveBoiloffManager().get_boiloff_report([tank])
    expected = report["total_propellant_kg"] * 0.05 / report["total_boil_off_kgs"] / 3600.0
    assert report["time_to_5pct_loss_hours"] == pytest.approx(expected)


def test_forward_model_depletes_without_increasing_fill():
    tank = CryoTank("lox", "LOX", 10.0, 0.8, 88.0, P_ATM_PA)
    predicted = ThermalModeler().predict_state(tank, 3600.0)
    assert 0.0 <= predicted.predicted_fill_percent <= tank.fill_percent
    assert predicted.boil_off_kg > 0.0
    assert math.isfinite(predicted.predicted_pressure_pa)


def test_sensor_validation_detects_inconsistent_channel_without_state_mutation():
    twin = CryogenicDigitalTwin()
    twin.add_tank("lox", Propellant.LOX, total_volume_m3=10.0, fill_fraction=0.8, temperature_k=88.0)
    before = twin.status()["tanks"]["lox"]
    result = twin.ingest_sensor_frame("lox", SensorFrame(120.0, P_ATM_PA, 0.8))
    after = twin.status()["tanks"]["lox"]
    assert not result["accepted_for_review"]
    assert "temperature_k" in result["inconsistent_channels"]
    assert before == after


def test_controller_interlocks_fill_and_drain():
    twin = CryogenicDigitalTwin()
    twin.add_tank("lox", Propellant.LOX, total_volume_m3=10.0, fill_fraction=0.8, temperature_k=88.0)
    assert twin.controller.set_valve("lox", "fill", True)
    assert not twin.controller.set_valve("lox", "drain", True)


def test_payload_and_cli_expose_non_operational_truth_boundary():
    payload = {
        "tanks": [
            {"tank_id": "lox", "propellant": "LOX", "total_volume_m3": 10, "fill_fraction": 0.8, "temperature_k": 88.0}
        ],
        "step_seconds": 1,
    }
    result = evaluate_payload(payload)
    assert result["schema"] == "glaciereq.cryogenic-digital-twin.v1"
    assert result["operational_authority"] is False

    proc = subprocess.run([sys.executable, str(ROOT / "src" / "cryo_engine.py"), "demo"], check=True, capture_output=True, text=True)
    cli = json.loads(proc.stdout)
    assert cli["operational_authority"] is False


def test_controller_pressure_target_is_bounded():
    twin = CryogenicDigitalTwin(max_pressure_pa=500_000)
    twin.add_tank("lox", Propellant.LOX, total_volume_m3=10.0, fill_fraction=0.8, temperature_k=88.0)
    with pytest.raises(ValueError):
        twin.controller.set_pressurization_target("lox", 600_000)
    assert twin.controller.set_mode("lox", TankMode.PRESSURIZING)
