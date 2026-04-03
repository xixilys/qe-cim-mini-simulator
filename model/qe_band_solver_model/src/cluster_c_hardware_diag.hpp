#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class ClusterCHardwareDiag : public sc_core::sc_module {
 public:
  explicit ClusterCHardwareDiag(sc_core::sc_module_name name);

  ClusterCOutput run(const ClusterCInput& input) const;
};

}  // namespace qebs
