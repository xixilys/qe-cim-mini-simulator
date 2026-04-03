#pragma once

#include <vector>

#include "near_sram_support.hpp"

namespace qebs {

class NearMemoryDomain : public sc_core::sc_module {
 public:
  explicit NearMemoryDomain(sc_core::sc_module_name name);

  std::vector<WavePanel> stage_panels(const EpisodeConfig& config) const;
  FullHS local_aggregate(const EpisodeConfig& config,
                         const std::vector<PartialHS>& partials) const;

 private:
  NearSRAMSupport near_sram_support_;
};

}  // namespace qebs
