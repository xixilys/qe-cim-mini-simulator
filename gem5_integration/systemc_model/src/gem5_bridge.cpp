#include "gem5_bridge.hpp"
#include "dft_hybrid_system_gem5.hpp"
#include <iostream>

Gem5Bridge::Gem5Bridge(sc_core::sc_module_name name, qebs::DFTHybridSystemGem5* dft_sys)
    : sc_module(name),
      dft_system_(dft_sys)
{
  tlm_target_ = new Gem5TLMTarget("gem5_tlm_target", dft_sys);
  
  SC_THREAD(monitor_compute_requests);
  
  std::cout << "[" << sc_core::sc_time_stamp() << "] Gem5Bridge initialized" << std::endl;
}

Gem5Bridge::~Gem5Bridge() {
  delete tlm_target_;
}

void Gem5Bridge::execute_c_bands(const CBandsRequest& req) {
  std::cout << "[" << sc_core::sc_time_stamp() << "] Executing c_bands: "
            << "N=" << req.n << " M=" << req.m << " K=" << req.k << std::endl;
  
  qebs::DFTHybridSystemGem5::CBandsRequest dft_req;
  dft_req.n = req.n;
  dft_req.m = req.m;
  dft_req.k = req.k;
  dft_req.h_matrix_addr = req.h_matrix_addr;
  dft_req.s_matrix_addr = req.s_matrix_addr;
  dft_req.result_addr = req.result_addr;
  
  dft_system_->execute_c_bands_from_gem5(dft_req);
}

void Gem5Bridge::monitor_compute_requests() {
  while (true) {
    wait(100, sc_core::SC_NS);
  }
}
