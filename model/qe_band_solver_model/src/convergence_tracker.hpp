#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class ConvergenceTracker : public sc_core::sc_module {
 public:
  explicit ConvergenceTracker(sc_core::sc_module_name name);
  ConvergenceDecision decide(const Body04StageRequest& request,
                             const DensitySummary& density,
                             const PotentialSummary& potential,
                             const DensityMixStats& mix_stats) const;
};

}  // namespace qebs
