#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class DensityCommitUnit : public sc_core::sc_module {
 public:
  explicit DensityCommitUnit(sc_core::sc_module_name name);
  DensitySummary commit(const Body04StageRequest& request,
                        const DensityAccumStats& stats) const;
};

}  // namespace qebs
