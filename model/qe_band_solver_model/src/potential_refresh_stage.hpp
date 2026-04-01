#pragma once

#include "potential_field_unit.hpp"
#include "projector_state_updater.hpp"

namespace qebs {

class PotentialRefreshStage : public sc_core::sc_module {
 public:
  explicit PotentialRefreshStage(sc_core::sc_module_name name);
  PotentialSummary refresh(const Body04StageRequest& request,
                           const DensitySummary& density) const;

 private:
  PotentialFieldUnit potential_field_unit_;
  ProjectorStateUpdater projector_state_updater_;
};

}  // namespace qebs
