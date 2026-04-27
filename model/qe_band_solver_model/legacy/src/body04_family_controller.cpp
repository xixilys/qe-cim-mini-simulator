#include "body04_family_controller.hpp"

namespace qebs {

Body04FamilyController::Body04FamilyController(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      outer_update_runtime_domain_(sc_core::sc_module_name("outer_update_runtime_domain")) {}

Body04BundleSummary Body04FamilyController::execute(
    const Body04BundleRequest& request) const {
  log_line(name(), "BODY_04 family bundle enters runtime domain: " + request.brief());
  auto summary = outer_update_runtime_domain_.execute(request);
  log_line(name(), "BODY_04 family bundle leaves runtime domain: " + summary.brief());
  return summary;
}

}  // namespace qebs
