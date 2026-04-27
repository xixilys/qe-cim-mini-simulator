#ifndef GEM5_BRIDGE_HPP
#define GEM5_BRIDGE_HPP

#include <systemc>
#include "gem5_tlm_target.hpp"

namespace qebs {
  class DFTHybridSystemGem5;
}

class Gem5Bridge : public sc_core::sc_module {
 public:
  SC_HAS_PROCESS(Gem5Bridge);

  Gem5Bridge(sc_core::sc_module_name name, qebs::DFTHybridSystemGem5* dft_sys);
  ~Gem5Bridge();

  Gem5TLMTarget* get_tlm_target() { return tlm_target_; }

  struct CBandsRequest {
    uint32_t n, m, k;
    uint64_t h_matrix_addr;
    uint64_t s_matrix_addr;
    uint64_t result_addr;
  };

  void execute_c_bands(const CBandsRequest& req);

 private:
  Gem5TLMTarget* tlm_target_;
  qebs::DFTHybridSystemGem5* dft_system_;

  void monitor_compute_requests();
};

#endif
