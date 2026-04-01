#include "wave_candidate_commit.hpp"

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

WaveCandidateCommit::WaveCandidateCommit(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

Body10PrecondSummary WaveCandidateCommit::commit(
    const Body10StageRequest& request, const Body10PrecondStats& stats) const {
  sc_core::wait(3.0, sc_core::SC_NS);

  const int iter = request.incoming_state.scf_iteration;
  Body10PrecondSummary summary;
  summary.wave_candidate_object.object_handle =
      body10_prefix(request.software_family, request.flow_family) +
      "_wave_body10_candidate_iter_" + std::to_string(iter);
  summary.wave_candidate_object.version = iter;
  summary.wave_candidate_object.resident_buffer_tag = 520 + iter;
  summary.wave_candidate_object.producer_body = "BODY_10A";
  summary.wave_candidate_object.validity_scope = "stage-window";
  summary.block_update_norm = stats.block_update_norm;
  summary.data_movement_kib = stats.data_movement_kib;
  summary.active_blocks = stats.active_blocks;

  log_line(name(), request.stage_kind + " committed wave candidate => " +
                       summary.brief());
  return summary;
}

}  // namespace qebs
