#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class CoefficientAccumulator : public sc_core::sc_module {
 public:
  explicit CoefficientAccumulator(sc_core::sc_module_name name);
  ProjectCoeffPacket accumulate(const EpisodeConfig& config,
                                const RowBlockWindowDesc& window,
                                const ProjectCoeffPacket& coeff) const;
};

}  // namespace qebs
