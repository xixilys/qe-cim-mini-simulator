#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class PotentialFieldUnit : public sc_core::sc_module {
 public:
  explicit PotentialFieldUnit(sc_core::sc_module_name name);
  PotentialFieldStats build(const Body04StageRequest& request,
                            const DensitySummary& density) const;
};

}  // namespace qebs
