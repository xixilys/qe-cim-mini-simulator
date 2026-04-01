#include "near_memory_domain.hpp"

namespace qebs {

NearMemoryDomain::NearMemoryDomain(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      near_sram_support_(sc_core::sc_module_name("near_sram_support")) {}

std::vector<WavePanel> NearMemoryDomain::stage_panels(const EpisodeConfig& config) const {
  log_line(name(), "Near-memory domain preparing resident panels for episode " +
                       std::to_string(config.episode_id));
  std::vector<WavePanel> panels;
  panels.reserve(static_cast<std::size_t>(config.panel_count));
  for (int panel_id = 0; panel_id < config.panel_count; ++panel_id) {
    panels.push_back(near_sram_support_.stage_panel(config, panel_id));
  }
  return panels;
}

FullHS NearMemoryDomain::local_aggregate(const EpisodeConfig& config,
                                         const std::vector<PartialHS>& partials) const {
  return near_sram_support_.aggregate(config, partials);
}

}  // namespace qebs
