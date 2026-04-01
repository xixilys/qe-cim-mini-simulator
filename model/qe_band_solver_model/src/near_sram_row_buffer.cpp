#include "near_sram_row_buffer.hpp"

namespace qebs {

NearSRAMRowBuffer::NearSRAMRowBuffer(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

PartialHS NearSRAMRowBuffer::commit_partial(const EpisodeConfig& config,
                                            const ResidentContextDesc& context,
                                            const PartialHS& partial) const {
  sc_core::wait(3.0, sc_core::SC_NS);

  PartialHS committed = partial;
  committed.h_contrib *= 1.0 + 0.005 * static_cast<double>(config.scf_iteration);
  committed.s_contrib *= 1.0 + 0.004 * static_cast<double>(context.generation);

  log_line(name(), "NearSRAMRowBuffer committed panel=" +
                       std::to_string(committed.panel_id) +
                       ", h=" + std::to_string(committed.h_contrib) +
                       ", s=" + std::to_string(committed.s_contrib));
  return committed;
}

}  // namespace qebs
