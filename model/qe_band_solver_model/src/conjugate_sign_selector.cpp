#include "conjugate_sign_selector.hpp"

namespace qebs {

ConjugateSignSelector::ConjugateSignSelector(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

DigitStreamSlice ConjugateSignSelector::apply_project_policy(
    const RowBlockWindowDesc& window, const DigitStreamSlice& slice) const {
  sc_core::wait(1.0, sc_core::SC_NS);

  DigitStreamSlice adjusted = slice;
  adjusted.magnitude_checksum = 0.0;
  for (std::size_t index = 0; index < adjusted.digits.size(); ++index) {
    const double sign = (window.conjugate_policy == "PROJECT_CONJ" && index % 2 == 1)
                            ? -1.0
                            : 1.0;
    adjusted.digits[index] *= sign;
    adjusted.magnitude_checksum += adjusted.digits[index];
  }

  log_line(name(), "ConjugateSignSelector applied PROJECT policy to " + adjusted.brief());
  return adjusted;
}

ProjectCoeffPacket ConjugateSignSelector::apply_backproject_policy(
    const RowBlockWindowDesc& window, const ProjectCoeffPacket& coeff) const {
  sc_core::wait(1.0, sc_core::SC_NS);

  ProjectCoeffPacket adjusted = coeff;
  if (window.conjugate_policy == "BACKPROJECT_DIRECT") {
    adjusted.coeff_condition *= 1.02;
  } else {
    adjusted.coeff_condition *= 0.99;
  }

  log_line(name(), "ConjugateSignSelector prepared BACKPROJECT coeff " +
                       adjusted.brief());
  return adjusted;
}

}  // namespace qebs
