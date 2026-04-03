#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class RowMergeTree : public sc_core::sc_module {
 public:
  explicit RowMergeTree(sc_core::sc_module_name name);
  PartialHS merge(const EpisodeConfig& config,
                  const RowBlockWindowDesc& window,
                  const BackprojectRowPacket& row) const;
};

}  // namespace qebs
