#pragma once

#include <memory>
#include <string>

#include "architecture_config.hpp"
#include "compute_unit_base.hpp"
#include "systemc_compat.hpp"

namespace qebs {

class ComputeUnitFactory {
 public:
  static std::unique_ptr<ComputeUnitBase> create(
      const std::string& module_name,
      const ComputeUnitConfig& config);
  
  static std::unique_ptr<ComputeUnitBase> create_cim_array(
      const std::string& module_name,
      const ComputeUnitConfig& config);
  
  static std::unique_ptr<ComputeUnitBase> create_traditional_fpga(
      const std::string& module_name,
      const ComputeUnitConfig& config);
  
  static std::unique_ptr<ComputeUnitBase> create_pim(
      const std::string& module_name,
      const ComputeUnitConfig& config);
};

}  // namespace qebs
