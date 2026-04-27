#include "reduction_closure_engine.hpp"

namespace qebs {

ReductionClosureEngine::ReductionClosureEngine(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

ReducedMatrices ReductionClosureEngine::close(const EpisodeConfig& config,
                                              const FullHS& full) const {
  sc_core::wait(10.0, sc_core::SC_NS);

  ReducedMatrices reduced;
  reduced.reduced_dim = config.band_count < 8 ? config.band_count : 8;
  reduced.h_small = full.h_total / (1.0 + full.aggregated_panels);
  reduced.s_small = full.s_total / (1.0 + full.aggregated_panels);
  reduced.closure_score = 0.5 * full.locality_score +
                          0.5 * (reduced.h_small / (1.0 + reduced.s_small));

  log_line(name(), "Reduction/closure companion formed reduced-space matrices");
  return reduced;
}

}  // namespace qebs
