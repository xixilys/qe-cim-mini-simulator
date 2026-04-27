#include "context_loader.hpp"

namespace qebs {

ContextLoader::ContextLoader(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

WavePanel ContextLoader::load_row_window(const WavePanel& panel,
                                         const ResidentContextDesc& context,
                                         const RowBlockWindowDesc& window) const {
  sc_core::wait(2.0, sc_core::SC_NS);

  WavePanel loaded;
  loaded.panel_id = panel.panel_id;
  loaded.resident_slot = context.resident_context_id;
  loaded.amplitude_norm = panel.amplitude_norm * (1.0 + 0.01 * window.row_block_id);
  for (int index = 0; index < window.row_count; ++index) {
    const int source_index = window.row_begin + index;
    if (source_index >= 0 &&
        source_index < static_cast<int>(panel.samples.size())) {
      loaded.samples.push_back(panel.samples[static_cast<std::size_t>(source_index)]);
    }
  }

  log_line(name(), "ContextLoader materialized row window from panel=" +
                       std::to_string(panel.panel_id) + " using " + window.brief());
  return loaded;
}

}  // namespace qebs
