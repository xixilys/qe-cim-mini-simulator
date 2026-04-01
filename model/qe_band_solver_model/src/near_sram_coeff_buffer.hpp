#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class NearSRAMCoeffBuffer : public sc_core::sc_module {
 public:
  explicit NearSRAMCoeffBuffer(sc_core::sc_module_name name);
  ProjectCoeffPacket store_and_transform(const EpisodeConfig& config,
                                         const ResidentContextDesc& context,
                                         const ProjectCoeffPacket& coeff) const;
};

}  // namespace qebs
