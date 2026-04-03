#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class ConjugateSignSelector : public sc_core::sc_module {
 public:
  explicit ConjugateSignSelector(sc_core::sc_module_name name);
  DigitStreamSlice apply_project_policy(const RowBlockWindowDesc& window,
                                        const DigitStreamSlice& slice) const;
  ProjectCoeffPacket apply_backproject_policy(const RowBlockWindowDesc& window,
                                              const ProjectCoeffPacket& coeff) const;
};

}  // namespace qebs
