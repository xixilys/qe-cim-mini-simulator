#pragma once

#include "cim_eligible_operator_subchain.hpp"
#include "fft_companion.hpp"
#include "near_memory_domain.hpp"

namespace qebs {

class ClusterAOperatorSweep : public sc_core::sc_module {
 public:
  explicit ClusterAOperatorSweep(sc_core::sc_module_name name);

  ClusterAOutput run(const ClusterAInput& input) const;

 private:
  NearMemoryDomain near_memory_domain_;
  CIMEligibleOperatorSubchain cim_subchain_;
  FFTCompanion fft_companion_;
};

}  // namespace qebs
