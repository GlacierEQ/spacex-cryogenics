#!/usr/bin/env python3
"""Cryogenic tank boil-off model — portfolio (simplified energy balance).

Q_dot = UA * dT; boil rate from latent heat. Not flight propellant management.
"""
from __future__ import annotations
from dataclasses import dataclass

# approximate LOX latent heat J/kg (order of magnitude demo constant)
LH_LOX = 2.13e5
LH_CH4 = 5.11e5

@dataclass
class Tank:
    fluid: str  # LOX | CH4
    ua_w_per_k: float
    mass_kg: float
    t_fluid_k: float
    t_amb_k: float

def boiloff_rate_kg_s(t: Tank) -> dict:
    lh = LH_LOX if t.fluid.upper()=="LOX" else LH_CH4
    q = t.ua_w_per_k * max(0.0, t.t_amb_k - t.t_fluid_k)
    mdot = q / lh if lh else 0.0
    hours_to_1pct = (0.01 * t.mass_kg / mdot / 3600) if mdot > 0 else float("inf")
    return {
        "q_w": round(q, 2),
        "mdot_kg_s": round(mdot, 6),
        "hours_to_1pct_mass": round(hours_to_1pct, 2) if hours_to_1pct != float("inf") else None
        }

if __name__ == "__main__":
    print(boiloff_rate_kg_s(Tank("LOX", 12.0, 50000, 90, 300)))
