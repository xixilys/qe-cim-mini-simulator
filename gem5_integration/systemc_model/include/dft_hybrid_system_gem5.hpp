#ifndef DFT_HYBRID_SYSTEM_GEM5_HPP
#define DFT_HYBRID_SYSTEM_GEM5_HPP

#include "architecture_config.hpp"
#include "chip_top.hpp"
#include "interconnect.hpp"

class Gem5Bridge;

namespace qebs {

class DFTHybridSystemGem5 : public sc_core::sc_module {
 public:
  DFTHybridSystemGem5(sc_core::sc_module_name name, 
                      const ArchitectureConfig& config,
                      bool enable_gem5_bridge = true);
  
  explicit DFTHybridSystemGem5(sc_core::sc_module_name name);
  
  SCFState run_demo(const SystemRunConfig& run_config) const;
  SCFRunReport run_scf(const SystemRunConfig& run_config) const;

  Gem5Bridge* get_gem5_bridge() { return gem5_bridge_; }

  struct CBandsRequest {
    uint32_t n, m, k;
    uint64_t h_matrix_addr;
    uint64_t s_matrix_addr;
    uint64_t result_addr;
  };

  struct ElectronsRequest {
    int n_bands;
    int n_basis;
    int n_kpoints;
    int n_spin;
    int max_iterations;
    double conv_threshold;
    double diag_threshold;
    double mixing_beta;
    int mixing_ndim;
    bool enable_cim;
  };

  struct ElectronsResult {
    bool converged;
    int iterations;
    double final_error;
    double total_energy;
    double total_time_ns;
    double c_bands_time_ns;
    double sum_band_time_ns;
    double mix_rho_time_ns;
  };

  void execute_c_bands_from_gem5(const CBandsRequest& req);
  
  ElectronsResult execute_electrons_from_gem5(const ElectronsRequest& req);

 private:
  ArchitectureConfig config_;
  Interconnect fabric_;
  ChipTop chip_;
  
  Gem5Bridge* gem5_bridge_;
};

}

#endif
