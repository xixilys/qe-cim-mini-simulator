#include "fpga_orchestrator.hpp"

namespace qebs {

FPGAOrchestrator::FPGAOrchestrator(sc_core::sc_module_name name, Interconnect& fabric,
                                   ChipTop& chip)
    : sc_core::sc_module(name), fabric_(fabric), chip_(chip) {}

EpisodeResult FPGAOrchestrator::execute_episode(
    const EpisodeDescriptor& descriptor) const {
  log_line(name(), "FPGA orchestrator forwards cluster-first episode: " +
                       descriptor.brief());
  fabric_.fpga_to_chip("dispatch cluster-first episode " + descriptor.brief());
  auto result = chip_.run_episode(descriptor);
  fabric_.chip_to_fpga("cluster-first episode complete " + result.brief());
  log_line(name(), "FPGA orchestrator collected result: " + result.brief());
  return result;
}

}  // namespace qebs
