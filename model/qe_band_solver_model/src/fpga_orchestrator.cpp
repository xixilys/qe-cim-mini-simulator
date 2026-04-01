#include "fpga_orchestrator.hpp"

namespace qebs {

namespace {

ReplayBundleDescriptor make_phase_b_descriptor(const EpisodeConfig& config) {
  ReplayBundleDescriptor descriptor;
  descriptor.bundle_id = config.episode_id;
  descriptor.bundle_kind = "BODY_01_03_REPLAY";
  descriptor.owner_domain = "FPGA_RUNTIME";
  descriptor.execution_domain = "CHIP_TOP";
  descriptor.software_family = config.software_family;
  descriptor.flow_family = config.flow_family;
  descriptor.scf_iteration = config.scf_iteration;
  descriptor.phase_b_config = config;
  descriptor.has_phase_b_config = true;
  return descriptor;
}

ReplayBundleDescriptor make_body10_descriptor(const Body10BundleRequest& request) {
  ReplayBundleDescriptor descriptor;
  descriptor.bundle_id = request.bundle_id;
  descriptor.bundle_kind = request.phase_family;
  descriptor.owner_domain = "FPGA_RUNTIME";
  descriptor.execution_domain = "FPGA_RUNTIME";
  descriptor.software_family = request.software_family;
  descriptor.flow_family = request.flow_family;
  descriptor.scf_iteration = request.incoming_state.scf_iteration;
  descriptor.body10_request = request;
  descriptor.has_body10_request = true;
  return descriptor;
}

ReplayBundleDescriptor make_body04_descriptor(const Body04BundleRequest& request) {
  ReplayBundleDescriptor descriptor;
  descriptor.bundle_id = request.bundle_id;
  descriptor.bundle_kind = request.phase_family;
  descriptor.owner_domain = "FPGA_RUNTIME";
  descriptor.execution_domain = "FPGA_RUNTIME";
  descriptor.software_family = request.software_family;
  descriptor.flow_family = request.flow_family;
  descriptor.scf_iteration = request.incoming_state.scf_iteration;
  descriptor.body04_request = request;
  descriptor.has_body04_request = true;
  return descriptor;
}

}  // namespace

FPGAOrchestrator::FPGAOrchestrator(sc_core::sc_module_name name, Interconnect& fabric,
                                   ChipTop& chip)
    : sc_core::sc_module(name),
      fabric_(fabric),
      chip_(chip),
      replay_bundle_executor_(sc_core::sc_module_name("replay_bundle_executor"),
                              fabric_, chip_) {}

ReplayBundleCompletion FPGAOrchestrator::execute_replay_bundle(
    const ReplayBundleDescriptor& descriptor) const {
  log_line(name(), "FPGA runtime forwards replay bundle: " + descriptor.brief());
  auto completion = replay_bundle_executor_.execute(descriptor);
  log_line(name(), "FPGA runtime collected replay completion: " + completion.brief());
  return completion;
}

EpisodeSummary FPGAOrchestrator::execute_episode(const EpisodeConfig& config) const {
  return execute_phase_b_episode(config);
}

EpisodeSummary FPGAOrchestrator::execute_phase_b_episode(
    const EpisodeConfig& config) const {
  const auto completion = execute_replay_bundle(make_phase_b_descriptor(config));
  return completion.phase_b;
}

Body10BundleSummary FPGAOrchestrator::execute_body10_family(
    const Body10BundleRequest& request) const {
  const auto completion = execute_replay_bundle(make_body10_descriptor(request));
  return completion.body10;
}

Body04BundleSummary FPGAOrchestrator::execute_body04_family(
    const Body04BundleRequest& request) const {
  const auto completion = execute_replay_bundle(make_body04_descriptor(request));
  return completion.body04;
}

}  // namespace qebs
