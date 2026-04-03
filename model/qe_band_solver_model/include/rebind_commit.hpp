#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class RebindCommit : public sc_core::sc_module {
 public:
  explicit RebindCommit(sc_core::sc_module_name name);
  Body10OrthoSummary commit(const Body10StageRequest& request,
                            const Body10OrthoStats& stats) const;
};

}  // namespace qebs
