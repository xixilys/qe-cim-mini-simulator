#pragma once

#include "near_memory_domain.hpp"
#include "reduction_closure_engine.hpp"

namespace qebs {

class ClusterBReducedBuild : public sc_core::sc_module {
 public:
  explicit ClusterBReducedBuild(sc_core::sc_module_name name);

  ClusterBOutput run(const ClusterBInput& input) const;

 private:
  NearMemoryDomain near_memory_domain_;
  ReductionClosureEngine reduction_closure_engine_;
};

}  // namespace qebs
