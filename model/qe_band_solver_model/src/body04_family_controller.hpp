#pragma once

#include "outer_update_runtime_domain.hpp"

namespace qebs {

class Body04FamilyController : public sc_core::sc_module {
 public:
  explicit Body04FamilyController(sc_core::sc_module_name name);
  Body04BundleSummary execute(const Body04BundleRequest& request) const;

 private:
  OuterUpdateRuntimeDomain outer_update_runtime_domain_;
};

}  // namespace qebs
