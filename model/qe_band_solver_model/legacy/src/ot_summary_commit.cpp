#include "ot_summary_commit.hpp"

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

OTSummaryCommit::OTSummaryCommit(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

Body10HistorySummary OTSummaryCommit::export_summary(
    const Body10StageRequest& request, const Body10HistoryStats& stats) const {
  sc_core::wait(1.0, sc_core::SC_NS);

  const int iter = request.incoming_state.scf_iteration;
  const std::string prefix = body10_prefix(request.software_family, request.flow_family);

  Body10HistorySummary summary;
  summary.search_history_object.object_handle =
      prefix + "_search_hist_iter_" + std::to_string(iter);
  summary.search_history_object.version = iter;
  summary.search_history_object.resident_buffer_tag = 580 + iter;
  summary.search_history_object.producer_body = "BODY_10C";
  summary.search_history_object.validity_scope = "outer-scf";
  summary.decision_summary_object.object_handle =
      prefix + "_ot_decision_iter_" + std::to_string(iter);
  summary.decision_summary_object.version = iter;
  summary.decision_summary_object.resident_buffer_tag = 600 + iter;
  summary.decision_summary_object.producer_body = "BODY_10C";
  summary.decision_summary_object.validity_scope = "body10-query";
  summary.accepted = stats.accepted;
  summary.history_depth = stats.history_depth;

  log_line(name(), request.stage_kind + " exported history/decision => " +
                       summary.brief());
  return summary;
}

}  // namespace qebs
