#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class FFTCompanion : public sc_core::sc_module {
 public:
  explicit FFTCompanion(sc_core::sc_module_name name);
  void transform(WavePanel& panel) const;
};

}  // namespace qebs
