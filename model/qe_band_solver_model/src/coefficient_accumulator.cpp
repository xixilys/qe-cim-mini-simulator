#include "coefficient_accumulator.hpp"

namespace qebs {

CoefficientAccumulator::CoefficientAccumulator(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

ProjectCoeffPacket CoefficientAccumulator::accumulate(
    const EpisodeConfig& config, const RowBlockWindowDesc& window,
    const ProjectCoeffPacket& coeff) const {
  sc_core::wait(3.0, sc_core::SC_NS);

  ProjectCoeffPacket accumulated = coeff;
  accumulated.coeff_energy *= (1.0 + 0.01 * static_cast<double>(config.scf_iteration));
  accumulated.coeff_condition *= (1.0 + 0.02 * static_cast<double>(window.row_count));

  log_line(name(), "CoefficientAccumulator refined " + accumulated.brief());
  return accumulated;
}

}  // namespace qebs
