#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class NearSRAMRowBuffer : public sc_core::sc_module {
 public:
  explicit NearSRAMRowBuffer(sc_core::sc_module_name name);
  PartialHS commit_partial(const EpisodeConfig& config,
                           const ResidentContextDesc& context,
                           const PartialHS& partial) const;
};

}  // namespace qebs
