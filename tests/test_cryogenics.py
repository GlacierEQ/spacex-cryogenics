"""Cryogenics tests."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from alpha.thermodynamics import (
    Propellant, PROPELLANTS, TankState, HeatTransfer,
    saturation_pressure, boil_off_rate, pressurization_rate,
    ullage_pressurization, subcooling_margin, tank_drain_time,
)
from omega.tank_controller import TankController, TankMode, TankState


def test_fluid_properties():
    lox = PROPELLANTS[Propellant.LOX]
    assert lox.boiling_point_k == 90.19
    assert lox.density_liquid > 1000


def test_saturation_pressure():
    lox = PROPELLANTS[Propellant.LOX]
    p = saturation_pressure(lox, 90.19)
    assert p > 0
    assert p < 1e7


def test_boil_off():
    tank = TankState(Propellant.LOX, 0.9, 90.19, 101325, 1.0, 9.0, 10.0)
    rate = boil_off_rate(tank, 1000.0)
    assert rate > 0
    assert rate < 10


def test_pressurization():
    tank = TankState(Propellant.LCH4, 0.9, 111.65, 200000, 1.0, 9.0, 10.0)
    rate = pressurization_rate(tank, 500.0)
    assert isinstance(rate, float)


def test_ullage_pressurization():
    tank = TankState(Propellant.LOX, 0.5, 90.19, 101325, 5.0, 5.0, 10.0)
    mass = ullage_pressurization(tank, 200000)
    assert mass > 0


def test_subcooling():
    margin = subcooling_margin(85.0, Propellant.LOX)
    assert margin > 0


def test_drain_time():
    time_s = tank_drain_time(0.9, 10.0, 100.0, Propellant.LOX)
    assert time_s > 0


def test_tank_controller_register():
    tc = TankController()
    tank = TankState(Propellant.LOX, 0.9, 90.19, 101325, 1.0, 9.0, 10.0)
    tc.register_tank("lox_main", tank)
    assert "lox_main" in tc._tanks


def test_tank_controller_mode():
    tc = TankController()
    tc.register_tank("lox", TankState(Propellant.LOX, 0.9, 90.19, 101325, 1.0, 9.0, 10.0))
    tc.set_mode("lox", TankMode.PRESSURIZING)
    assert tc._modes["lox"] == TankMode.PRESSURIZING


def test_tank_controller_valve():
    tc = TankController()
    tc.register_tank("lox", TankState(Propellant.LOX, 0.9, 90.19, 101325, 1.0, 9.0, 10.0))
    tc.set_valve("lox", "fill", True)
    assert tc._valves["lox"]["fill"].open


def test_tank_controller_update():
    tc = TankController()
    tc.register_tank("lox", TankState(Propellant.LOX, 0.9, 90.19, 101325, 1.0, 9.0, 10.0))
    updates = tc.update(1.0)
    assert len(updates) == 1
    assert updates[0]["tank"] == "lox"


def test_tank_controller_status():
    tc = TankController()
    tc.register_tank("lox", TankState(Propellant.LOX, 0.9, 90.19, 101325, 1.0, 9.0, 10.0))
    status = tc.get_tank_status("lox")
    assert status is not None
    assert status["propellant"] == "LOX"


def test_tank_controller_alert():
    tc = TankController()
    alerts = []
    tc.on_alert(lambda a: alerts.append(a))
    tc.register_tank("lox", TankState(Propellant.LOX, 0.9, 90.0, 101325, 1.0, 9.0, 10.0))
    tc.update(1.0)
    assert len(alerts) > 0


def test_heat_transfer():
    ht = HeatTransfer(10.0, 0.01, 300.0, 90.0)
    assert ht.conduction_watts > 0
    assert ht.radiation_watts > 0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
