#include "near_sram_support.hpp"

namespace qebs {

NearSRAMSupport::NearSRAMSupport(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

WavePanel NearSRAMSupport::stage_panel(const EpisodeConfig& config, int panel_id) const {
  sc_core::wait(6.0, sc_core::SC_NS);

  WavePanel panel;
  panel.panel_id = panel_id;
  panel.resident_slot = panel_id % 2;
  panel.amplitude_norm = 1.0 + 0.08 * panel_id + 0.02 * config.scf_iteration;
  panel.samples.reserve(static_cast<std::size_t>(config.panel_size));
  for (int i = 0; i < config.panel_size; ++i) {
    panel.samples.push_back(0.12 * (panel_id + 1) + 0.01 * (i + 1) + 0.02 * config.scf_iteration);
  }

  log_line(name(), "Near-SRAM staged " + panel.brief());
  return panel;
}

FullHS NearSRAMSupport::aggregate(const EpisodeConfig& config,
                                  const std::vector<PartialHS>& partials) const {
  sc_core::wait(8.0, sc_core::SC_NS);

  FullHS full;
  full.episode_id = config.episode_id;
  full.aggregated_panels = static_cast<int>(partials.size());

  double locality_acc = 0.0;
  for (const auto& partial : partials) {
    full.h_total += partial.h_contrib;
    full.s_total += partial.s_contrib;
    locality_acc += partial.local_condition;
  }
  if (!partials.empty()) {
    full.locality_score = locality_acc / static_cast<double>(partials.size());
  }

  log_line(name(), "Near-SRAM aggregated partial H/S for episode " +
                       std::to_string(config.episode_id));
  return full;
}

}  // namespace qebs
