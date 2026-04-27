#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class DigitSerialInputBoundary : public sc_core::sc_module {
 public:
  explicit DigitSerialInputBoundary(sc_core::sc_module_name name);
  DigitStreamSlice pack_project_stream(const WavePanel& panel,
                                       const RowBlockWindowDesc& window) const;
};

}  // namespace qebs
