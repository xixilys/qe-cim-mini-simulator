#include "resident_context_controller.hpp"

namespace qebs {

ResidentContextController::ResidentContextController(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

ResidentContextDesc ResidentContextController::bind_context(const EpisodeConfig& config,
                                                            int inner_step) const {
  sc_core::wait(2.0, sc_core::SC_NS);

  ResidentContextDesc context;
  context.resident_context_id = 2000 + config.episode_id;
  context.generation = inner_step + 1;
  context.row_block_count =
      (config.panel_size + config.resident_row_block_size - 1) /
      config.resident_row_block_size;
  context.column_group_count = 3 + (config.band_count > 16 ? 1 : 0);
  context.resident_words = context.column_group_count * config.panel_size;
  context.software_family = config.software_family;
  context.projector_family =
      (config.software_family == "QE") ? "uspp-projector-family" : "grid-projector-family";
  context.lifecycle_state = "READY";

  log_line(name(), "ResidentContextController bound " + context.brief());
  return context;
}

RowBlockWindowDesc ResidentContextController::open_row_block(
    const EpisodeConfig& config, const ResidentContextDesc& context,
    int row_block_id) const {
  sc_core::wait(1.0, sc_core::SC_NS);

  RowBlockWindowDesc window;
  window.row_block_id = row_block_id;
  window.row_begin = row_block_id * config.resident_row_block_size;
  const int remaining = config.panel_size - window.row_begin;
  window.row_count = remaining > config.resident_row_block_size
                         ? config.resident_row_block_size
                         : remaining;
  if (window.row_count < 0) {
    window.row_count = 0;
  }
  window.active_mod_group_mask = (row_block_id + context.generation) % 2 == 0 ? 0x7 : 0x3;
  window.fft_preconditioned = config.enable_fft;
  window.conjugate_policy = (config.software_family == "QE") ? "PROJECT_CONJ" : "PROJECT_CONJ";

  log_line(name(), "ResidentContextController opened " + window.brief());
  return window;
}

void ResidentContextController::release_context(const ResidentContextDesc& context) const {
  sc_core::wait(1.0, sc_core::SC_NS);
  log_line(name(), "ResidentContextController released ctx=" +
                       std::to_string(context.resident_context_id) +
                       ", gen=" + std::to_string(context.generation));
}

}  // namespace qebs
