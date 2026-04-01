#pragma once

#include "cim_eligible_operator_subchain.hpp"
#include "fft_companion.hpp"
#include "near_memory_domain.hpp"
#include "reduction_closure_engine.hpp"
#include "vector_diag_companion.hpp"

namespace qebs {

class ChipTop : public sc_core::sc_module {
 public:
  explicit ChipTop(sc_core::sc_module_name name);
  EpisodeSummary run_episode(const EpisodeConfig& config) const;
  EpisodeSummary run_replay_bundle(const ReplayBundleDescriptor& descriptor) const;

 private:
  EpisodeSummary execute_phase_b_sequence(const EpisodeConfig& config) const;

  CIMEligibleOperatorSubchain cim_subchain_;
  NearMemoryDomain near_memory_domain_;
  ReductionClosureEngine reduction_closure_engine_;
  VectorDiagCompanion vector_diag_companion_;
  FFTCompanion fft_companion_;
};

}  // namespace qebs
