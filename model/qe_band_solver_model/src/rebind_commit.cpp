#include "rebind_commit.hpp"

namespace qebs {

namespace {

std::string body10_prefix(const std::string& software_family,
                          const std::string& flow_family) {
  if (software_family == "CP2K" && flow_family == "QS_OT") {
    return "cp2k_ot";
  }
  if (software_family == "VASP") {
    return "vasp";
  }
  return "qe";
}

}  // namespace

RebindCommit::RebindCommit(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

Body10OrthoSummary RebindCommit::commit(const Body10StageRequest& request,
                                        const Body10OrthoStats& stats) const {
  sc_core::wait(3.0, sc_core::SC_NS);

  const int iter = request.incoming_state.scf_iteration;
  const std::string prefix = body10_prefix(request.software_family, request.flow_family);

  Body10OrthoSummary summary;
  summary.updated_wave_object.object_handle =
      prefix + "_wave_body10_iter_" + std::to_string(iter);
  summary.updated_wave_object.version = iter;
  summary.updated_wave_object.resident_buffer_tag = 540 + iter;
  summary.updated_wave_object.producer_body = "BODY_10B";
  summary.updated_wave_object.validity_scope = "episode-window";
  summary.updated_projector_object.object_handle =
      prefix + "_proj_body10_iter_" + std::to_string(iter);
  summary.updated_projector_object.version = iter;
  summary.updated_projector_object.resident_buffer_tag = 560 + iter;
  summary.updated_projector_object.producer_body = "BODY_10B";
  summary.updated_projector_object.validity_scope = "episode-window";
  summary.orthogonality_score = stats.orthogonality_score;
  summary.data_movement_kib = stats.data_movement_kib;
  summary.active_blocks = stats.active_blocks;

  log_line(name(), request.stage_kind + " rebound wave/projector => " +
                       summary.brief());
  return summary;
}

}  // namespace qebs
