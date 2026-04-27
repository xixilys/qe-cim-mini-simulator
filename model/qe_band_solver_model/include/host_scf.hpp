#pragma once

#include "fpga_orchestrator.hpp"

namespace qebs {

class HostSCF : public sc_core::sc_module {
 public:
  HostSCF(sc_core::sc_module_name name, Interconnect& fabric, FPGAOrchestrator& fpga);
  SCFState run_demo(const SystemRunConfig& run_config = SystemRunConfig()) const;
  SCFRunReport run_full_flow(const SystemRunConfig& run_config = SystemRunConfig()) const;

 private:
  SCFState initialize_state(const SystemRunConfig& run_config) const;
  ResidentSetDesc make_resident_set_desc(const SCFState& state,
                                         const SystemRunConfig& run_config,
                                         int episode_id) const;
  BandBatchDesc make_band_batch_desc(const SCFState& state,
                                     const SystemRunConfig& run_config,
                                     int episode_id) const;
  DiagPolicy make_diag_policy(const SystemRunConfig& run_config,
                              const BandBatchDesc& batch) const;
  ScfIterationRequest make_iteration_request(const SCFState& state,
                                             const SystemRunConfig& run_config,
                                             int episode_id) const;
  SCFIterationClusteredReport finalize_iteration(const ScfIterationRequest& request,
                                                 const CompletionSummary& completion,
                                                 SCFState& state) const;

  Interconnect& fabric_;
  FPGAOrchestrator& fpga_;
};

}  // namespace qebs
