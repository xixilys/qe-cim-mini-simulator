#include <algorithm>

#include "projector_state_updater.hpp"

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

ProjectorStateUpdater::ProjectorStateUpdater(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

ProjectorStateStats ProjectorStateUpdater::update(const Body04StageRequest& request,
                                                  const DensitySummary& density) const {
  sc_core::wait(5.0, sc_core::SC_NS);

  const auto& state = request.incoming_state;
  const auto& summary = request.phase_b_summary;
  const bool is_cp2k = summary.config.software_family == "CP2K";
  const bool is_ot = summary.config.flow_family == "QS_OT";
  const bool is_vasp = summary.config.software_family == "VASP";
  const std::string prefix =
      potential_prefix(summary.config.software_family, summary.config.flow_family);

  ProjectorStateStats stats;
  if (is_ot && !state.projector_object.object_handle.empty()) {
    stats.projector_object = state.projector_object;
    stats.projector_object.validity_scope = "episode-window";
  } else {
    stats.projector_object.object_handle =
        (is_vasp ? prefix + "_paw_ctx_iter_" : prefix + "_proj_state_iter_") +
        std::to_string(summary.config.scf_iteration);
    stats.projector_object.version = summary.config.scf_iteration;
    stats.projector_object.resident_buffer_tag = 320 + summary.config.scf_iteration;
    stats.projector_object.producer_body = "BODY_04B";
    stats.projector_object.validity_scope = "episode-window";
  }
  stats.projector_refresh_score = std::min(
      0.99, 0.42 + 0.08 * static_cast<double>(summary.config.panel_count) +
                0.03 * static_cast<double>(summary.config.scf_iteration) +
                (is_ot ? 0.06 : (is_cp2k ? 0.03 : (is_vasp ? 0.05 : 0.0))));

  log_line(name(), request.stage_kind + " updated projector state => " + stats.brief());
  return stats;
}

}  // namespace qebs
