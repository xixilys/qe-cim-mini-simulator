#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class WaveCandidateCommit : public sc_core::sc_module {
 public:
  explicit WaveCandidateCommit(sc_core::sc_module_name name);
  Body10PrecondSummary commit(const Body10StageRequest& request,
                              const Body10PrecondStats& stats) const;
};

}  // namespace qebs
