#include "density_accumulation_stage.hpp"

namespace qebs {

DensityAccumulationStage::DensityAccumulationStage(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      density_accumulator_unit_(sc_core::sc_module_name("density_accumulator_unit")),
      density_commit_unit_(sc_core::sc_module_name("density_commit_unit")) {}

DensitySummary DensityAccumulationStage::accumulate(
    const Body04StageRequest& request) const {
  const auto stats = density_accumulator_unit_.reduce(request);
  return density_commit_unit_.commit(request, stats);
}

}  // namespace qebs
