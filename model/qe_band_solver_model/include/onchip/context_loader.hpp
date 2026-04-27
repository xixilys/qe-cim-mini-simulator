#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class ContextLoader : public sc_core::sc_module {
 public:
  explicit ContextLoader(sc_core::sc_module_name name);
  WavePanel load_row_window(const WavePanel& panel,
                            const ResidentContextDesc& context,
                            const RowBlockWindowDesc& window) const;
};

}  // namespace qebs
