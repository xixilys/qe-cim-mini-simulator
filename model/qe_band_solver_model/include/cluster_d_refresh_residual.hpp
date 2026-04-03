#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class ClusterDRefreshResidual : public sc_core::sc_module {
 public:
  explicit ClusterDRefreshResidual(sc_core::sc_module_name name);

  ClusterDOutput run(const ClusterDInput& input) const;
};

}  // namespace qebs
