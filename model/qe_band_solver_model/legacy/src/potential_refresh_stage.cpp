#include "potential_refresh_stage.hpp"

namespace qebs {

namespace {

std::string potential_prefix(const std::string& software_family,
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

PotentialRefreshStage::PotentialRefreshStage(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      potential_field_unit_(sc_core::sc_module_name("potential_field_unit")),
      projector_state_updater_(sc_core::sc_module_name("projector_state_updater")) {}

PotentialSummary PotentialRefreshStage::refresh(const Body04StageRequest& request,
                                                const DensitySummary& density) const {
  const auto field_stats = potential_field_unit_.build(request, density);
  const auto projector_stats = projector_state_updater_.update(request, density);

  PotentialSummary potential;
  const auto& summary = request.phase_b_summary;
  const std::string prefix =
      potential_prefix(summary.config.software_family, summary.config.flow_family);

  potential.potential_object.object_handle =
      prefix + "_veff_iter_" + std::to_string(summary.config.scf_iteration);
  potential.potential_object.version = summary.config.scf_iteration;
  potential.potential_object.resident_buffer_tag = 300 + summary.config.scf_iteration;
  potential.potential_object.producer_body = "BODY_04B";
  potential.potential_object.validity_scope = "scf-iteration";
  potential.projector_object = projector_stats.projector_object;
  potential.potential_norm = field_stats.potential_norm;
  potential.projector_refresh_score = projector_stats.projector_refresh_score;
  potential.grid_exchange_kib = field_stats.grid_exchange_kib;

  log_line(name(), request.stage_kind + " produced " + potential.brief());
  return potential;
}

}  // namespace qebs
