#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class PreconditionedUpdateVector : public sc_core::sc_module {
 public:
  explicit PreconditionedUpdateVector(sc_core::sc_module_name name);
  Body10PrecondStats apply(const Body10StageRequest& request) const;
};

}  // namespace qebs
