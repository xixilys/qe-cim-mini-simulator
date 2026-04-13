#pragma once

#include "chip_top.hpp"
#include "interconnect.hpp"

namespace qebs {

class FPGAOrchestrator : public sc_core::sc_module {
 public:
  FPGAOrchestrator(sc_core::sc_module_name name, Interconnect& fabric, ChipTop& chip);

  CompletionSummary execute_iteration(const ScfIterationRequest& request) const;

 private:
  EpisodeDescriptor make_episode_descriptor(const ScfIterationRequest& request) const;
  CompletionSummary make_completion_summary(const ScfIterationRequest& request,
                                            const EpisodeResult& result,
                                            bool resident_reused,
                                            int dma_ref_cycles,
                                            int host_assist_ref_cycles,
                                            double dma_read_kib,
                                            double dma_write_kib) const;
  int simulate_host_diag_service(EpisodeResult& result,
                                 const ScfIterationRequest& request) const;

  Interconnect& fabric_;
  ChipTop& chip_;
  mutable std::string resident_set_id_;
  mutable int resident_set_generation_ = -1;
};

}  // namespace qebs
