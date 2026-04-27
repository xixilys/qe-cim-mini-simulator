#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class ProjectorStateUpdater : public sc_core::sc_module {
 public:
  explicit ProjectorStateUpdater(sc_core::sc_module_name name);
  ProjectorStateStats update(const Body04StageRequest& request,
                             const DensitySummary& density) const;
};

}  // namespace qebs
