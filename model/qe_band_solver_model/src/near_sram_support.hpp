#pragma once

#include <vector>

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class NearSRAMSupport : public sc_core::sc_module {
 public:
  explicit NearSRAMSupport(sc_core::sc_module_name name);

  WavePanel stage_panel(const EpisodeConfig& config, int panel_id) const;
  FullHS aggregate(const EpisodeConfig& config,
                   const std::vector<PartialHS>& partials) const;
};

}  // namespace qebs
