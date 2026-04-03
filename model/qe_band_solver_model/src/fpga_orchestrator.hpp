#pragma once

#include "chip_top.hpp"
#include "interconnect.hpp"

namespace qebs {

class FPGAOrchestrator : public sc_core::sc_module {
 public:
  FPGAOrchestrator(sc_core::sc_module_name name, Interconnect& fabric, ChipTop& chip);

  EpisodeResult execute_episode(const EpisodeDescriptor& descriptor) const;

 private:
  Interconnect& fabric_;
  ChipTop& chip_;
};

}  // namespace qebs
