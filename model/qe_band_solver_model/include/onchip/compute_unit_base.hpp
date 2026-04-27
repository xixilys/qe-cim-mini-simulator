#pragma once

#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class ComputeUnitBase : public sc_core::sc_module {
 public:
  explicit ComputeUnitBase(sc_core::sc_module_name name)
      : sc_core::sc_module(name) {}
  
  virtual ~ComputeUnitBase() = default;
  
  virtual ProjectCoeffPacket project(const EpisodeConfig& config,
                                     const ResidentContextDesc& context,
                                     const RowBlockWindowDesc& window,
                                     const DigitStreamSlice& slice) const = 0;
  
  virtual PartialHS backproject(const EpisodeConfig& config,
                                const ResidentContextDesc& context,
                                const RowBlockWindowDesc& window,
                                const ProjectCoeffPacket& coeff) const = 0;
};

}  // namespace qebs
