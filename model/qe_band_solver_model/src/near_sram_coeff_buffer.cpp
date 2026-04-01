#include "near_sram_coeff_buffer.hpp"

namespace qebs {

NearSRAMCoeffBuffer::NearSRAMCoeffBuffer(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

ProjectCoeffPacket NearSRAMCoeffBuffer::store_and_transform(
    const EpisodeConfig& config, const ResidentContextDesc& context,
    const ProjectCoeffPacket& coeff) const {
  sc_core::wait(4.0, sc_core::SC_NS);

  ProjectCoeffPacket transformed = coeff;
  transformed.coeff_energy *= 1.0 + 0.015 * static_cast<double>(context.generation);
  transformed.coeff_condition *= 1.0 + 0.01 * static_cast<double>(config.band_count);

  log_line(name(), "NearSRAMCoeffBuffer stored/transformed " + transformed.brief());
  return transformed;
}

}  // namespace qebs
