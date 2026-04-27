#pragma once

#include <vector>

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class CommandScheduler : public sc_core::sc_module {
 public:
  explicit CommandScheduler(sc_core::sc_module_name name);
  std::vector<LCWCommand> issue_projector_chain(const EpisodeConfig& config,
                                                const ResidentContextDesc& context,
                                                int inner_step) const;
};

}  // namespace qebs
