#pragma once

#include "blocked_gemm_engine.hpp"
#include "coefficient_accumulator.hpp"
#include "compute_unit_base.hpp"
#include "logging.hpp"
#include "row_merge_tree.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class TraditionalFPGAGEMMCore : public ComputeUnitBase {
 public:
  explicit TraditionalFPGAGEMMCore(sc_core::sc_module_name name);

  ProjectCoeffPacket project(const EpisodeConfig& config,
                             const ResidentContextDesc& context,
                             const RowBlockWindowDesc& window,
                             const DigitStreamSlice& slice) const override;

  PartialHS backproject(const EpisodeConfig& config,
                        const ResidentContextDesc& context,
                        const RowBlockWindowDesc& window,
                        const ProjectCoeffPacket& coeff) const override;

  struct PerformanceStats {
    int64_t total_cycles;
    int64_t gemm_cycles;
    int64_t memory_cycles;
    int64_t overhead_cycles;
    int dsp_utilization_percent;
    int bram_utilization_percent;
    
    PerformanceStats() 
        : total_cycles(0), gemm_cycles(0), memory_cycles(0), 
          overhead_cycles(0), dsp_utilization_percent(0), 
          bram_utilization_percent(0) {}
  };
  
  PerformanceStats get_stats() const { return stats_; }
  void reset_stats() const { stats_ = PerformanceStats(); }

 private:
  BlockedGEMMEngine gemm_engine_;
  CoefficientAccumulator coefficient_accumulator_;
  RowMergeTree row_merge_tree_;
  mutable PerformanceStats stats_;

  void update_stats(int64_t cycles) const;
};

}  // namespace qebs
