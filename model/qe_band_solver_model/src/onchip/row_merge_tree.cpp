#include "row_merge_tree.hpp"

namespace qebs {

RowMergeTree::RowMergeTree(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

PartialHS RowMergeTree::merge(const EpisodeConfig& config,
                              const RowBlockWindowDesc& window,
                              const BackprojectRowPacket& row) const {
  sc_core::wait(3.0, sc_core::SC_NS);

  PartialHS partial;
  partial.panel_id = row.panel_id;
  partial.h_contrib = row.row_energy * (0.11 + 0.01 * static_cast<double>(config.scf_iteration));
  partial.s_contrib = row.overlap_energy * (0.72 + 0.03 * static_cast<double>(window.row_count));
  partial.local_condition = 1.0 / (1.0 + static_cast<double>(window.row_block_id + 1));

  log_line(name(), "RowMergeTree emitted partial panel=" + std::to_string(partial.panel_id) +
                       ", h=" + std::to_string(partial.h_contrib) +
                       ", s=" + std::to_string(partial.s_contrib));
  return partial;
}

}  // namespace qebs
