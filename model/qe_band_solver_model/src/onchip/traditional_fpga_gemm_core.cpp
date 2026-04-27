#include "traditional_fpga_gemm_core.hpp"

namespace qebs {

TraditionalFPGAGEMMCore::TraditionalFPGAGEMMCore(sc_core::sc_module_name name)
    : ComputeUnitBase(name),
      gemm_engine_(sc_core::sc_module_name("blocked_gemm_engine")),
      coefficient_accumulator_(sc_core::sc_module_name("coefficient_accumulator")),
      row_merge_tree_(sc_core::sc_module_name("row_merge_tree")),
      stats_() {
  log_line(this->name(), "TraditionalFPGAGEMMCore initialized");
}

ProjectCoeffPacket TraditionalFPGAGEMMCore::project(
    const EpisodeConfig& config,
    const ResidentContextDesc& context,
    const RowBlockWindowDesc& window,
    const DigitStreamSlice& slice) const {
  
  BlockedGEMMEngine::GEMMConfig gemm_config;
  gemm_config.m = window.row_count;
  gemm_config.n = slice.digit_count > 0 ? slice.digit_count : 128;
  gemm_config.k = context.row_block_count > 0 ? context.row_block_count : 256;
  gemm_config.block_size = 32;
  gemm_config.dsp_array_dim = 16;
  gemm_config.clock_freq_mhz = 300;
  
  int64_t cycles = gemm_engine_.estimate_cycles(gemm_config);
  
  update_stats(cycles);
  
  ProjectCoeffPacket coeff;
  coeff.panel_id = slice.panel_id;
  coeff.resident_context_id = context.resident_context_id;
  coeff.resident_generation = context.generation;
  coeff.row_block_id = window.row_block_id;
  coeff.coeff_energy = slice.magnitude_checksum;
  coeff.coeff_condition = 1.0;
  
  auto accumulated = coefficient_accumulator_.accumulate(config, window, coeff);
  
  log_line(name(), "TraditionalFPGAGEMMCore PROJECT: panel=" +
                   std::to_string(slice.panel_id) +
                   ", row_block=" + std::to_string(window.row_block_id) +
                   ", cycles=" + std::to_string(cycles));
  
  return accumulated;
}

PartialHS TraditionalFPGAGEMMCore::backproject(
    const EpisodeConfig& config,
    const ResidentContextDesc& context,
    const RowBlockWindowDesc& window,
    const ProjectCoeffPacket& coeff) const {
  
  BlockedGEMMEngine::GEMMConfig gemm_config;
  gemm_config.m = window.row_count;
  gemm_config.n = 128;
  gemm_config.k = context.row_block_count > 0 ? context.row_block_count : 256;
  gemm_config.block_size = 32;
  gemm_config.dsp_array_dim = 16;
  gemm_config.clock_freq_mhz = 300;
  
  int64_t cycles = gemm_engine_.estimate_cycles(gemm_config);
  
  update_stats(cycles);
  
  BackprojectRowPacket row;
  row.panel_id = coeff.panel_id;
  row.resident_context_id = coeff.resident_context_id;
  row.resident_generation = coeff.resident_generation;
  row.row_block_id = coeff.row_block_id;
  row.row_energy = coeff.coeff_energy;
  row.overlap_energy = coeff.coeff_energy * 0.5;
  
  auto merged = row_merge_tree_.merge(config, window, row);
  
  log_line(name(), "TraditionalFPGAGEMMCore BACKPROJECT: panel=" +
                   std::to_string(coeff.panel_id) +
                   ", row_block=" + std::to_string(coeff.row_block_id) +
                   ", cycles=" + std::to_string(cycles));
  
  return merged;
}

void TraditionalFPGAGEMMCore::update_stats(int64_t cycles) const {
  stats_.total_cycles += cycles;
  stats_.gemm_cycles += cycles;
  stats_.dsp_utilization_percent = 75;
  stats_.bram_utilization_percent = 60;
}

}  // namespace qebs
