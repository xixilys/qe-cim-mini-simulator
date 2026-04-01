#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class DensityMixerUnit : public sc_core::sc_module {
 public:
  explicit DensityMixerUnit(sc_core::sc_module_name name);
  DensityMixStats mix_density(const Body04StageRequest& request,
                              const DensitySummary& density,
                              const PotentialSummary& potential) const;
};

}  // namespace qebs
