#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class ReductionClosureEngine : public sc_core::sc_module {
 public:
  explicit ReductionClosureEngine(sc_core::sc_module_name name);
  ReducedMatrices close(const EpisodeConfig& config, const FullHS& full) const;
};

}  // namespace qebs
