#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class DensityAccumulatorUnit : public sc_core::sc_module {
 public:
  explicit DensityAccumulatorUnit(sc_core::sc_module_name name);
  DensityAccumStats reduce(const Body04StageRequest& request) const;
};

}  // namespace qebs
