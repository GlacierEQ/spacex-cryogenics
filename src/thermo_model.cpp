// Deterministic cryogenic thermodynamic reference model.
// Review-grade simulation only; no hardware I/O or flight authority.

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <stdexcept>

namespace cryo {
constexpr double R_UNIVERSAL = 8.31446261815324; // J/(mol K)
constexpr double STEFAN_BOLTZMANN = 5.670374419e-8;
constexpr double P_ATM_PA = 101325.0;
constexpr double PI = 3.14159265358979323846;

struct CryogenicFluid {
    const char* name;
    double molar_mass_kg_mol;
    double boiling_point_k;
    double heat_of_vaporization_j_mol;
    double liquid_density_kg_m3;
    double specific_heat_j_kg_k;
    double critical_temp_k;
    double critical_pressure_pa;
};

constexpr CryogenicFluid LOX{
    "LOX", 0.031998, 90.19, 213100.0 * 0.031998, 1141.0, 1700.0, 154.58, 5.043e6};
constexpr CryogenicFluid LCH4{
    "LCH4", 0.016043, 111.65, 510000.0 * 0.016043, 422.6, 3480.0, 190.56, 4.599e6};

struct TankState {
    double temperature_k;
    double pressure_pa;
    double liquid_level_fraction;
    double liquid_mass_kg;
    double boiloff_rate_kg_s;
    double subcooling_k;
};

class CryoThermoModel {
  public:
    CryoThermoModel(CryogenicFluid fluid, double volume_m3,
                    double insulation_thickness_m = 0.05,
                    double insulation_conductivity_w_m_k = 0.02,
                    double ambient_temp_k = 300.0)
        : fluid_(fluid), volume_m3_(volume_m3),
          insulation_thickness_m_(insulation_thickness_m),
          insulation_conductivity_(insulation_conductivity_w_m_k),
          ambient_temp_k_(ambient_temp_k) {
        if (volume_m3_ <= 0.0 || insulation_thickness_m_ <= 0.0 ||
            insulation_conductivity_ < 0.0 || ambient_temp_k_ <= 0.0) {
            throw std::invalid_argument("invalid cryogenic model geometry");
        }
        const double radius = std::cbrt(3.0 * volume_m3_ / (4.0 * PI));
        surface_area_m2_ = 4.0 * PI * radius * radius;
    }

    double saturation_pressure_pa(double temp_k) const {
        if (!(temp_k > 0.0) || !std::isfinite(temp_k)) {
            throw std::invalid_argument("temperature must be finite and > 0 K");
        }
        if (temp_k >= fluid_.critical_temp_k) {
            return fluid_.critical_pressure_pa;
        }
        const double exponent = (fluid_.heat_of_vaporization_j_mol / R_UNIVERSAL) *
            (1.0 / fluid_.boiling_point_k - 1.0 / temp_k);
        return std::min(fluid_.critical_pressure_pa, P_ATM_PA * std::exp(exponent));
    }

    double saturation_temperature_k(double pressure_pa) const {
        if (!(pressure_pa > 0.0) || !std::isfinite(pressure_pa)) {
            throw std::invalid_argument("pressure must be finite and > 0 Pa");
        }
        if (pressure_pa >= fluid_.critical_pressure_pa) {
            return fluid_.critical_temp_k;
        }
        const double inverse_t = 1.0 / fluid_.boiling_point_k -
            (R_UNIVERSAL / fluid_.heat_of_vaporization_j_mol) *
            std::log(pressure_pa / P_ATM_PA);
        if (!(inverse_t > 0.0)) {
            throw std::domain_error("pressure outside approximation domain");
        }
        return 1.0 / inverse_t;
    }

    double heat_leak_watts(double liquid_temp_k) const {
        if (!(liquid_temp_k > 0.0)) {
            throw std::invalid_argument("liquid temperature must be > 0 K");
        }
        const double delta_t = std::max(0.0, ambient_temp_k_ - liquid_temp_k);
        const double conductive = insulation_conductivity_ * surface_area_m2_ *
            delta_t / insulation_thickness_m_;
        constexpr double emissivity = 0.05;
        const double radiative = emissivity * STEFAN_BOLTZMANN * surface_area_m2_ *
            std::max(0.0, std::pow(ambient_temp_k_, 4) - std::pow(liquid_temp_k, 4));
        return conductive + radiative;
    }

    double boiloff_rate_kg_s(double liquid_temp_k) const {
        const double latent_j_kg = fluid_.heat_of_vaporization_j_mol / fluid_.molar_mass_kg_mol;
        return heat_leak_watts(liquid_temp_k) / latent_j_kg;
    }

    double subcooling_margin_k(double liquid_temp_k, double pressure_pa) const {
        return saturation_temperature_k(pressure_pa) - liquid_temp_k;
    }

    TankState compute_state(double temp_k, double fill_fraction,
                            double ullage_pressure_pa = P_ATM_PA) const {
        if (fill_fraction < 0.0 || fill_fraction > 1.0) {
            throw std::invalid_argument("fill fraction must be in [0, 1]");
        }
        return TankState{
            temp_k,
            saturation_pressure_pa(temp_k),
            fill_fraction,
            fill_fraction * volume_m3_ * fluid_.liquid_density_kg_m3,
            boiloff_rate_kg_s(temp_k),
            subcooling_margin_k(temp_k, ullage_pressure_pa),
        };
    }

    double simulate_boiloff_kg(double temp_k, double initial_mass_kg,
                               double duration_s, double dt_s = 1.0) const {
        if (initial_mass_kg < 0.0 || duration_s < 0.0 || dt_s <= 0.0) {
            throw std::invalid_argument("invalid simulation interval or mass");
        }
        double remaining = initial_mass_kg;
        double lost = 0.0;
        for (double elapsed = 0.0; elapsed < duration_s && remaining > 0.0;) {
            const double step = std::min(dt_s, duration_s - elapsed);
            const double mass = std::min(remaining, boiloff_rate_kg_s(temp_k) * step);
            lost += mass;
            remaining -= mass;
            elapsed += step;
        }
        return lost;
    }

  private:
    CryogenicFluid fluid_;
    double volume_m3_;
    double insulation_thickness_m_;
    double insulation_conductivity_;
    double ambient_temp_k_;
    double surface_area_m2_{};
};

bool approximately(double actual, double expected, double relative_tolerance) {
    return std::abs(actual - expected) <= std::abs(expected) * relative_tolerance;
}

int self_test() {
    CryoThermoModel lox(LOX, 300.0);
    CryoThermoModel methane(LCH4, 120.0);
    if (!approximately(lox.saturation_pressure_pa(LOX.boiling_point_k), P_ATM_PA, 1e-10)) return 10;
    if (!approximately(methane.saturation_pressure_pa(LCH4.boiling_point_k), P_ATM_PA, 1e-10)) return 11;
    if (!(lox.saturation_pressure_pa(95.0) > lox.saturation_pressure_pa(90.0))) return 12;
    if (!(lox.boiloff_rate_kg_s(90.0) > 0.0)) return 13;
    const auto state = lox.compute_state(88.0, 0.90);
    if (!(state.liquid_mass_kg > 0.0 && state.subcooling_k > 0.0)) return 14;
    if (!(lox.simulate_boiloff_kg(90.0, 1000.0, 3600.0) > 0.0)) return 15;
    return 0;
}
} // namespace cryo

int main() {
    const int result = cryo::self_test();
    if (result != 0) {
        std::cerr << "self-test failed: " << result << '\n';
        return result;
    }
    cryo::CryoThermoModel lox(cryo::LOX, 300.0);
    const auto state = lox.compute_state(88.0, 0.90);
    std::cout << std::fixed << std::setprecision(6)
              << "model=two-phase-approximation\n"
              << "normal_bp_pressure_pa=" << lox.saturation_pressure_pa(cryo::LOX.boiling_point_k) << '\n'
              << "liquid_mass_kg=" << state.liquid_mass_kg << '\n'
              << "boiloff_rate_kg_s=" << state.boiloff_rate_kg_s << '\n'
              << "operational_authority=false\n";
    return 0;
}
