#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class ResidentContextController : public sc_core::sc_module {
 public:
  explicit ResidentContextController(sc_core::sc_module_name name);
  ResidentContextDesc bind_context(const EpisodeConfig& config, int inner_step) const;
  RowBlockWindowDesc open_row_block(const EpisodeConfig& config,
                                    const ResidentContextDesc& context,
                                    int row_block_id) const;
  void release_context(const ResidentContextDesc& context) const;
};

}  // namespace qebs
