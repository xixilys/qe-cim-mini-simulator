#include "mixing_convergence_stage.hpp"

namespace qebs {

namespace {

std::string mixing_prefix(const std::string& software_family,
                          const std::string& flow_family) {
  if (software_family == "CP2K" && flow_family == "QS_OT") {
    return "cp2k_ot";
  }
  if (software_family == "CP2K") {
    return "cp2k";
  }
  if (software_family == "VASP" && flow_family == "FAST") {
    return "vasp_fast";
  }
  if (software_family == "VASP") {
    return "vasp";
  }
  return "qe";
}

}  // namespace

MixingConvergenceStage::MixingConvergenceStage(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      density_mixer_unit_(sc_core::sc_module_name("density_mixer_unit")),
      convergence_tracker_(sc_core::sc_module_name("convergence_tracker")) {}

MixingSummary MixingConvergenceStage::mix(const Body04StageRequest& request,
                                          const DensitySummary& density,
                                          const PotentialSummary& potential) const {
  const auto mix_stats = density_mixer_unit_.mix_density(request, density, potential);
  const auto decision =
      convergence_tracker_.decide(request, density, potential, mix_stats);

  MixingSummary mixing;
  const auto& summary = request.phase_b_summary;
  const std::string prefix =
      mixing_prefix(summary.config.software_family, summary.config.flow_family);

  mixing.mixed_density_object.object_handle =
      prefix + "_rho_mixed_iter_" + std::to_string(summary.config.scf_iteration);
  mixing.mixed_density_object.version = summary.config.scf_iteration;
  mixing.mixed_density_object.resident_buffer_tag = 400 + summary.config.scf_iteration;
  mixing.mixed_density_object.producer_body = "BODY_04C";
  mixing.mixed_density_object.validity_scope = "outer-scf";
  mixing.history_object = decision.history_object;
  mixing.mixed_rho_norm = mix_stats.mixed_rho_norm;
  mixing.density_delta = mix_stats.density_delta;
  mixing.energy_delta = decision.energy_delta;
  mixing.converged = decision.converged;
  mixing.history_depth = decision.history_depth;

  log_line(name(), request.stage_kind + " produced " + mixing.brief());
  return mixing;
}

}  // namespace qebs
