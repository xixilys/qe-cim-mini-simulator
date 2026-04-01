#pragma once

#include "history_integrator.hpp"
#include "logging.hpp"
#include "orthogonalize_unit.hpp"
#include "ot_summary_commit.hpp"
#include "preconditioned_update_vector.hpp"
#include "rebind_commit.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"
#include "wave_candidate_commit.hpp"

namespace qebs {

class Body10FamilyController : public sc_core::sc_module {
 public:
  explicit Body10FamilyController(sc_core::sc_module_name name);
  Body10BundleSummary execute(const Body10BundleRequest& request) const;

 private:
  PreconditionedUpdateVector preconditioned_update_vector_;
  WaveCandidateCommit wave_candidate_commit_;
  OrthogonalizeUnit orthogonalize_unit_;
  RebindCommit rebind_commit_;
  HistoryIntegrator history_integrator_;
  OTSummaryCommit ot_summary_commit_;
};

}  // namespace qebs
