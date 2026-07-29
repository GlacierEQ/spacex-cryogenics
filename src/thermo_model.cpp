/**
 * Cryogenic Thermodynamic Model — C++ High-Precision Phase Equilibrium Solver
 * Implements Clausius-Clapeyron phase boundary tracking, boil-off rate integration,
 * and subcooling margin computation for LOX/CH4 propellant systems.
 */

#include <iostream>
#include <cmath>
#include <vector>
#include <string>
#include <algorithm>

// Physical constants
constexpr double R_UNIVERSAL = 8.314472;     // J/(mol·K)
constexpr double STEFAN_BOLTZMANN = 5.670374419e-8; // W/(m²·K⁴)

struct CryogenicFluid {
    std::string name;
    double molar_mass_kg;        // kg/mol
    double boiling_point_k;      // K at 1 atm
    double heat_of_vaporization_j;// J/mol
    double liquid_density_kg_m3; // kg/m³ at boiling point
    double specific_heat_j_kg_k; // J/(kg·K)
    double critical_temp_k;
    double critical_pressure_pa;
};

// LOX: Liquid Oxygen
constexpr CryogenicFluid LOX = {
    "LOX", 0.032, 90.188, 6820.0, 1141.0, 918.0, 154.59, 5043000.0
};

// LCH4: Liquid Methane
constexpr CryogenicFluid LCH4 = {
    "LCH4", 0.01604, 111.65, 8190.0, 422.6, 2220.0, 190.56, 4599000.0
};

struct TankState {
    double temperature_k;
    double pressure_pa;
    double liquid_level_pct;     // 0-100%
    double liquid_mass_kg;
    double ullage_pressure_pa;   // Gas pressure above liquid
    double boiloff_rate_kg_s;
    double subcooling_k;         // Below saturation temperature
};

class CryoThermoModel {
    CryogenicFluid fluid;
    double tank_volume_m3;
    double insulation_thickness_m;
    double insulation_conductivity; // W/(m·K)
    double tank_surface_area_m2;
    double ambient_temp_k;

public:
    CryoThermoModel(
        CryogenicFluid f, double vol_m3, double insul_m = 0.05,
        double cond = 0.02, double ambient = 300.0)
        : fluid(f), tank_volume_m3(vol_m3),
          insulation_thickness_m(insul_m),
          insulation_conductivity(cond),
          ambient_temp_k(ambient)
    {
        // Approximate tank as sphere for surface area
        double r = std::pow(3.0 * vol_m3 / (4.0 * M_PI), 1.0/3.0);
        tank_surface_area_m2 = 4.0 * M_PI * r * r;
    }

    /**
     * Clausius-Clapeyron: saturation pressure at temperature T
     * ln(P2/P1) = (L/R) * (1/T1 - 1/T2)
     */
    double saturation_pressure_pa(double temp_k) const {
        double p_ref = 101325.0; // 1 atm at boiling point
        double exponent = (fluid.heat_of_vaporization_j / R_UNIVERSAL)
                         * (1.0 / fluid.boiling_point_k - 1.0 / temp_k);
        return p_ref * std::exp(exponent);
    }

    /**
     * Saturation temperature at given pressure (inverse Clausius-Clapeyron)
     */
    double saturation_temperature_k(double pressure_pa) const {
        double p_ref = 101325.0;
        double t_ref = fluid.boiling_point_k;
        double lhs = std::log(pressure_pa / p_ref);
        return 1.0 / (1.0 / t_ref - lhs * R_UNIVERSAL / fluid.heat_of_vaporization_j);
    }

    /**
     * Compute total heat leak into tank (conductive + radiative)
     */
    double heat_leak_watts(double liquid_temp_k) const {
        // Conductive heat leak through insulation
        double q_cond = insulation_conductivity * tank_surface_area_m2
                       * (ambient_temp_k - liquid_temp_k) / insulation_thickness_m;

        // Radiative heat leak (simplified — outer surface to inner)
        double emissivity = 0.05; // MLI blankets
        double q_rad = emissivity * STEFAN_BOLTZMANN * tank_surface_area_m2
                      * (std::pow(ambient_temp_k, 4) - std::pow(liquid_temp_k, 4));

        return std::max(q_cond + q_rad, 0.0);
    }

    /**
     * Compute boil-off rate from heat leak
     * dm/dt = Q / L (where L is latent heat per kg)
     */
    double boiloff_rate_kg_s(double liquid_temp_k) const {
        double q = heat_leak_watts(liquid_temp_k);
        double L_per_kg = fluid.heat_of_vaporization_j / fluid.molar_mass_kg;
        return q / L_per_kg;
    }

    /**
     * Compute subcooling margin (how far below saturation)
     */
    double subcooling_margin_k(double liquid_temp_k, double ullage_pressure_pa) const {
        double t_sat = saturation_temperature_k(ullage_pressure_pa);
        return t_sat - liquid_temp_k;
    }

    /**
     * Compute complete tank state from temperature and fill level
     */
    TankState compute_state(double temp_k, double fill_pct) const {
        TankState state;
        state.temperature_k = temp_k;
        state.liquid_level_pct = fill_pct;
        state.liquid_mass_kg = (fill_pct / 100.0) * tank_volume_m3 * fluid.liquid_density_kg_m3;
        state.pressure_pa = saturation_pressure_pa(temp_k);
        state.ullage_pressure_pa = state.pressure_pa * 1.05; // 5% pressurant margin
        state.boiloff_rate_kg_s = boiloff_rate_kg_s(temp_k);
        state.subcooling_k = subcooling_margin_k(temp_k, state.ullage_pressure_pa);
        return state;
    }

    /**
     * Simulate boil-off over duration_s seconds, returning mass lost
     */
    double simulate_boiloff_kg(double initial_temp_k, double duration_s, double dt_s = 1.0) const {
        double total_mass_lost = 0.0;
        double temp = initial_temp_k;
        for (double t = 0; t < duration_s; t += dt_s) {
            double rate = boiloff_rate_kg_s(temp);
            total_mass_lost += rate * dt_s;
            // Temperature slowly rises due to heat leak
            double q = heat_leak_watts(temp);
            double mass_remaining = 100000.0 - total_mass_lost; // Assume 100t tank
            if (mass_remaining > 100.0) {
                temp += (q * dt_s * 0.001) / (mass_remaining * fluid.specific_heat_j_kg_k);
            }
        }
        return total_mass_lost;
    }
};

// Standalone test
int main() {
    // LOX tank: 300 m³ (roughly S1 LOX tank volume)
    CryoThermoModel lox_model(LOX, 300.0);

    auto state = lox_model.compute_state(90.0, 95.0);
    std::cout << "=== LOX Tank State ===" << std::endl;
    std::cout << "Temperature: " << state.temperature_k << " K" << std::endl;
    std::cout << "Pressure: " << state.pressure_pa / 1000.0 << " kPa" << std::endl;
    std::cout << "Liquid mass: " << state.liquid_mass_kg / 1000.0 << " tonnes" << std::endl;
    std::cout << "Boil-off rate: " << state.boiloff_rate_kg_s << " kg/s" << std::endl;
    std::cout << "Subcooling: " << state.subcooling_k << " K" << std::endl;

    // Simulate 1 hour boil-off
    double mass_lost = lox_model.simulate_boiloff_kg(90.0, 3600.0);
    std::cout << "1-hour boil-off: " << mass_lost << " kg" << std::endl;

    // LCH4 tank
    CryoThermoModel ch4_model(LCH4, 120.0);
    auto ch4_state = ch4_model.compute_state(111.0, 90.0);
    std::cout << "\n=== LCH4 Tank State ===" << std::endl;
    std::cout << "Temperature: " << ch4_state.temperature_k << " K" << std::endl;
    std::cout << "Boil-off rate: " << ch4_state.boiloff_rate_kg_s << " kg/s" << std::endl;

    return 0;
}
