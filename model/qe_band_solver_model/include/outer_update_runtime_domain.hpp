#pragma once

#include "density_accumulation_stage.hpp"
#include "mixing_convergence_stage.hpp"
#include "potential_refresh_stage.hpp"

namespace qebs {

class OuterUpdateRuntimeDomain : public sc_core::sc_module {
 public:
  explicit OuterUpdateRuntimeDomain(sc_core::sc_module_name name);
  Body04BundleSummary execute(const Body04BundleRequest& request) const;

 private:
  Body04StageRequest make_density_request(const Body04BundleRequest& request) const;
  Body04StageRequest make_potential_request(const Body04BundleRequest& request,
                                            const DensitySummary& density) const;
  Body04StageRequest make_mixing_request(const Body04BundleRequest& request,
                                         const DensitySummary& density,
                                         const PotentialSummary& potential) const;
  Body04StageDescriptor make_stage_descriptor(const Body04StageRequest& request,
                                              const std::string& expected_output_handle) const;
  Body04StageSummary make_stage_summary(const Body04StageRequest& request,
                                        const DensitySummary& density) const;
  Body04StageSummary make_stage_summary(const Body04StageRequest& request,
                                        const PotentialSummary& potential) const;
  Body04StageSummary make_stage_summary(const Body04StageRequest& request,
                                        const MixingSummary& mixing) const;
  Body04LoweringPlan make_lowering_plan(const Body04BundleRequest& request,
                                        const Body04StageRequest& density_request,
                                        const Body04StageRequest& potential_request,
                                        const Body04StageRequest& mixing_request) const;

 private:
  DensityAccumulationStage density_stage_;
  PotentialRefreshStage potential_stage_;
  MixingConvergenceStage mixing_stage_;
};

}  // namespace qebs
