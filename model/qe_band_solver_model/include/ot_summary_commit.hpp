#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class OTSummaryCommit : public sc_core::sc_module {
 public:
  explicit OTSummaryCommit(sc_core::sc_module_name name);
  Body10HistorySummary export_summary(const Body10StageRequest& request,
                                      const Body10HistoryStats& stats) const;
};

}  // namespace qebs
