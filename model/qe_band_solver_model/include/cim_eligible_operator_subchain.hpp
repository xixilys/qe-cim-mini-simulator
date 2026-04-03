#pragma once

#include <vector>

#include "cim_array_core.hpp"
#include "command_scheduler.hpp"
#include "conjugate_sign_selector.hpp"
#include "context_loader.hpp"
#include "digit_serial_input_boundary.hpp"
#include "near_sram_coeff_buffer.hpp"
#include "near_sram_row_buffer.hpp"
#include "resident_context_controller.hpp"

namespace qebs {

class CIMEligibleOperatorSubchain : public sc_core::sc_module {
 public:
  explicit CIMEligibleOperatorSubchain(sc_core::sc_module_name name);
  OperatorChainReport run(const EpisodeConfig& config,
                          const std::vector<WavePanel>& panels,
                          int inner_step) const;

 private:
  CommandScheduler command_scheduler_;
  ResidentContextController resident_context_controller_;
  ContextLoader context_loader_;
  DigitSerialInputBoundary digit_serial_input_boundary_;
  ConjugateSignSelector conjugate_sign_selector_;
  NearSRAMCoeffBuffer near_sram_coeff_buffer_;
  NearSRAMRowBuffer near_sram_row_buffer_;
  CIMArrayCore cim_array_core_;
};

}  // namespace qebs
