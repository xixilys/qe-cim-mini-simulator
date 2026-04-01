#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class HistoryIntegrator : public sc_core::sc_module {
 public:
  explicit HistoryIntegrator(sc_core::sc_module_name name);
  Body10HistoryStats integrate(const Body10StageRequest& request,
                               const Body10OrthoSummary& ortho) const;
};

}  // namespace qebs
