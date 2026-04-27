#include "onchip/compute_unit_factory.hpp"

#include "onchip/cim_array_core.hpp"
#include "onchip/traditional_fpga_gemm_core.hpp"
#include "logging.hpp"

namespace qebs {

std::unique_ptr<ComputeUnitBase> ComputeUnitFactory::create(
    const std::string& module_name,
    const ComputeUnitConfig& config) {
  
  switch (config.type) {
    case ComputeUnitType::CIM_ARRAY:
      return create_cim_array(module_name, config);
    
    case ComputeUnitType::TRADITIONAL_FPGA:
      return create_traditional_fpga(module_name, config);
    
    case ComputeUnitType::PIM:
      return create_pim(module_name, config);
    
    case ComputeUnitType::HYBRID:
      log_line("ComputeUnitFactory", 
               "HYBRID compute unit not yet implemented, falling back to CIM_ARRAY");
      return create_cim_array(module_name, config);
    
    default:
      log_line("ComputeUnitFactory", 
               "Unknown compute unit type, falling back to CIM_ARRAY");
      return create_cim_array(module_name, config);
  }
}

std::unique_ptr<ComputeUnitBase> ComputeUnitFactory::create_cim_array(
    const std::string& module_name,
    const ComputeUnitConfig& config) {
  
  log_line("ComputeUnitFactory", 
           "Creating CIM Array: moduli=" + std::to_string(config.cim_moduli_count) +
           ", array=" + std::to_string(config.cim_array_rows) + "x" + 
           std::to_string(config.cim_array_cols) +
           ", freq=" + std::to_string(config.cim_frequency_mhz) + "MHz");
  
  auto unit = std::make_unique<CIMArrayCore>(sc_core::sc_module_name(module_name.c_str()));
  
  return unit;
}

std::unique_ptr<ComputeUnitBase> ComputeUnitFactory::create_traditional_fpga(
    const std::string& module_name,
    const ComputeUnitConfig& config) {
  
  log_line("ComputeUnitFactory", 
           "Creating Traditional FPGA: tile=" + std::to_string(config.fpga_tile_size) +
           ", dsp=" + std::to_string(config.fpga_dsp_count) +
           ", freq=" + std::to_string(config.fpga_frequency_mhz) + "MHz");
  
  auto unit = std::make_unique<TraditionalFPGAGEMMCore>(
      sc_core::sc_module_name(module_name.c_str()));
  
  return unit;
}

std::unique_ptr<ComputeUnitBase> ComputeUnitFactory::create_pim(
    const std::string& module_name,
    const ComputeUnitConfig& config) {
  
  log_line("ComputeUnitFactory", 
           "PIM compute unit not yet implemented, falling back to Traditional FPGA");
  
  return create_traditional_fpga(module_name, config);
}

}  // namespace qebs
