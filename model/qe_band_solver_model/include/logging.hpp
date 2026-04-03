#pragma once

#include <iostream>
#include <string>

#include "systemc_compat.hpp"

namespace qebs {

inline std::string yes_no(bool value) { return value ? "yes" : "no"; }

inline void log_line(const std::string& who, const std::string& message) {
  std::cout << "[" << sc_core::sc_time_stamp() << "] [" << who << "] " << message
            << std::endl;
}

}  // namespace qebs
