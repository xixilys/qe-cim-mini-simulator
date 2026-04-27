#include <systemc>
#include "dft_hybrid_system_gem5.hpp"

using namespace sc_core;
using namespace qebs;

SC_MODULE(TestBench) {
  DFTHybridSystemGem5* dft_system;
  
  SC_CTOR(TestBench) {
    ArchitectureConfig config = ArchitectureConfig::create_default();
    
    // Create DFT system without gem5 bridge for standalone testing
    dft_system = new DFTHybridSystemGem5("dft_system", config, false);
    
    SC_THREAD(run_test);
  }
  
  void run_test() {
    wait(10, SC_NS);
    
    std::cout << "\n=== Test 1: c_bands computation ===" << std::endl;
    
    DFTHybridSystemGem5::CBandsRequest c_bands_req;
    c_bands_req.n = 32;
    c_bands_req.m = 128;
    c_bands_req.k = 1;
    c_bands_req.h_matrix_addr = 0x100000000ULL;
    c_bands_req.s_matrix_addr = 0x200000000ULL;
    c_bands_req.result_addr = 0x300000000ULL;
    
    dft_system->execute_c_bands_from_gem5(c_bands_req);
    
    wait(1000, SC_NS);
    
    std::cout << "\n=== Test 2: Full electrons loop ===" << std::endl;
    
    DFTHybridSystemGem5::ElectronsRequest electrons_req;
    electrons_req.n_bands = 32;
    electrons_req.n_basis = 128;
    electrons_req.n_kpoints = 4;
    electrons_req.n_spin = 1;
    electrons_req.max_iterations = 10;
    electrons_req.conv_threshold = 1e-6;
    electrons_req.diag_threshold = 1e-2;
    electrons_req.mixing_beta = 0.7;
    electrons_req.mixing_ndim = 8;
    electrons_req.enable_cim = true;
    
    auto result = dft_system->execute_electrons_from_gem5(electrons_req);
    
    std::cout << "\n=== Electrons loop results ===" << std::endl;
    std::cout << "  Converged: " << (result.converged ? "YES" : "NO") << std::endl;
    std::cout << "  Iterations: " << result.iterations << std::endl;
    std::cout << "  Final error: " << result.final_error << std::endl;
    std::cout << "  Total energy: " << result.total_energy << " Ry" << std::endl;
    std::cout << "  Total time: " << result.total_time_ns / 1e6 << " ms" << std::endl;
    
    wait(100, SC_NS);
    
    std::cout << "\n=== All tests completed successfully ===" << std::endl;
    sc_stop();
  }
};

int sc_main(int argc, char* argv[]) {
  std::cout << "=== gem5-SystemC Integration Standalone Test ===" << std::endl;
  std::cout << "This test validates the SystemC model without gem5 TLM connection" << std::endl;
  
  TestBench tb("testbench");
  
  std::cout << "\nSystemC modules instantiated successfully" << std::endl;
  std::cout << "Starting simulation...\n" << std::endl;
  
  sc_start();
  
  std::cout << "\nSimulation completed at " << sc_time_stamp() << std::endl;
  
  return 0;
}
