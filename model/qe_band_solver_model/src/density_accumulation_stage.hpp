#pragma once

#include "density_accumulator_unit.hpp"
#include "density_commit_unit.hpp"

namespace qebs {

class DensityAccumulationStage : public sc_core::sc_module {
 public:
  explicit DensityAccumulationStage(sc_core::sc_module_name name);
  DensitySummary accumulate(const Body04StageRequest& request) const;

 private:
  DensityAccumulatorUnit density_accumulator_unit_;
  DensityCommitUnit density_commit_unit_;
};

}  // namespace qebs
