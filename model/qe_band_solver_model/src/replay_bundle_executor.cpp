#include "replay_bundle_executor.hpp"

namespace qebs {

ReplayBundleExecutor::ReplayBundleExecutor(sc_core::sc_module_name name,
                                           Interconnect& fabric,
                                           ChipTop& chip)
    : sc_core::sc_module(name),
      fabric_(fabric),
      chip_(chip),
      body04_family_controller_(sc_core::sc_module_name("body04_family_controller")),
      body10_family_controller_(sc_core::sc_module_name("body10_family_controller")) {}

ReplayBundleCompletion ReplayBundleExecutor::execute(
    const ReplayBundleDescriptor& descriptor) const {
  ReplayBundleCompletion completion;
  completion.bundle_id = descriptor.bundle_id;
  completion.bundle_kind = descriptor.bundle_kind;
  completion.owner_domain = descriptor.owner_domain;
  completion.execution_domain = descriptor.execution_domain;
  completion.software_family = descriptor.software_family;
  completion.flow_family = descriptor.flow_family;
  completion.accepted = true;

  log_line(name(), "Replay bundle executor accepted: " + descriptor.brief());

  if (descriptor.bundle_kind == "BODY_01_03_REPLAY" && descriptor.has_phase_b_config) {
    sc_core::wait(9.0, sc_core::SC_NS);
    fabric_.fpga_to_chip("dispatch " + descriptor.software_family + " episode " +
                         std::to_string(descriptor.phase_b_config.episode_id) +
                         " with BODY_01/BODY_02/BODY_03");
    const auto summary = chip_.run_replay_bundle(descriptor);
    fabric_.chip_to_fpga("episode complete " + summary.brief());
    completion.has_phase_b = true;
    completion.phase_b = summary;
    completion.lcw_words_issued = summary.lcw_words_issued;
    completion.row_blocks_processed = summary.row_blocks_processed;
    completion.completion_note = "phase-b-episode-complete";
    log_line(name(), "Replay bundle complete: " + completion.brief());
    return completion;
  }

  if (descriptor.bundle_kind == "BODY_10_FAMILY" && descriptor.has_body10_request) {
    sc_core::wait(5.0, sc_core::SC_NS);
    fabric_.fpga_to_chip("dispatch BODY_10 family bundle " +
                         std::to_string(descriptor.body10_request.bundle_id) +
                         " for " + descriptor.software_family + "/" +
                         descriptor.flow_family);
    const auto summary = body10_family_controller_.execute(descriptor.body10_request);
    fabric_.chip_to_fpga("BODY_10 family complete " + summary.brief());
    completion.has_body10 = true;
    completion.body10 = summary;
    completion.data_movement_kib = summary.data_movement_kib;
    completion.completion_note = "body10-family-complete";
    log_line(name(), "Replay bundle complete: " + completion.brief());
    return completion;
  }

  if (descriptor.bundle_kind == "BODY_04_FAMILY" && descriptor.has_body04_request) {
    sc_core::wait(6.0, sc_core::SC_NS);
    fabric_.fpga_to_chip("dispatch BODY_04 family bundle " +
                         std::to_string(descriptor.body04_request.bundle_id) +
                         " for " + descriptor.software_family + "/" +
                         descriptor.flow_family);
    const auto summary = body04_family_controller_.execute(descriptor.body04_request);
    fabric_.chip_to_fpga("BODY_04 family complete " + summary.brief());
    completion.has_body04 = true;
    completion.body04 = summary;
    completion.data_movement_kib = summary.bundle_data_movement_kib;
    completion.completion_note = "body04-family-complete";
    log_line(name(), "Replay bundle complete: " + completion.brief());
    return completion;
  }

  completion.accepted = false;
  completion.completion_note = "unsupported-replay-bundle";
  log_line(name(), "Replay bundle rejected: " + completion.brief());
  return completion;
}

}  // namespace qebs
