#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class OrthogonalizeUnit : public sc_core::sc_module {
 public:
  explicit OrthogonalizeUnit(sc_core::sc_module_name name);
  Body10OrthoStats project(const Body10StageRequest& request,
                           const Body10PrecondSummary& precond) const;
};

}  // namespace qebs
