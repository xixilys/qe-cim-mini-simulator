#pragma once

#include <utility>

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class VectorDiagCompanion : public sc_core::sc_module {
 public:
  explicit VectorDiagCompanion(sc_core::sc_module_name name);
  std::pair<RitzResult, ResidualPacket> solve_and_update(
      const EpisodeConfig& config, const ReducedMatrices& reduced,
      int inner_step) const;
};

}  // namespace qebs
