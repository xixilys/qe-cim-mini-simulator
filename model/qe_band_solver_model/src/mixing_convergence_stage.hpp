#pragma once

#include "convergence_tracker.hpp"
#include "density_mixer_unit.hpp"

namespace qebs {

class MixingConvergenceStage : public sc_core::sc_module {
 public:
  explicit MixingConvergenceStage(sc_core::sc_module_name name);
  MixingSummary mix(const Body04StageRequest& request,
                    const DensitySummary& density,
                    const PotentialSummary& potential) const;

 private:
  DensityMixerUnit density_mixer_unit_;
  ConvergenceTracker convergence_tracker_;
};

}  // namespace qebs
