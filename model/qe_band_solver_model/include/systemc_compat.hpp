#pragma once

#include <cstdint>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

#if defined(QE_BAND_SOLVER_USE_SYSTEMC) && QE_BAND_SOLVER_USE_SYSTEMC
#include <systemc>
#else
namespace sc_core {

enum sc_time_unit { SC_FS, SC_PS, SC_NS, SC_US, SC_MS, SC_SEC };

inline double unit_scale_ns(sc_time_unit unit) {
  switch (unit) {
    case SC_FS: return 1e-6;
    case SC_PS: return 1e-3;
    case SC_NS: return 1.0;
    case SC_US: return 1e3;
    case SC_MS: return 1e6;
    case SC_SEC: return 1e9;
  }
  return 1.0;
}

class sc_time {
 public:
  sc_time() : value_ns_(0.0) {}
  sc_time(double value, sc_time_unit unit) : value_ns_(value * unit_scale_ns(unit)) {}

  double to_double() const { return value_ns_; }
  std::string to_string() const {
    std::ostringstream oss;
    oss << std::fixed << std::setprecision(1) << value_ns_ << " ns";
    return oss.str();
  }

 private:
  double value_ns_;
};

class sc_module_name {
 public:
  explicit sc_module_name(const char* name) : name_(name) {}
  operator const char*() const { return name_; }

 private:
  const char* name_;
};

class sc_module {
 public:
  explicit sc_module(const sc_module_name& module_name)
      : name_(static_cast<const char*>(module_name)) {}
  virtual ~sc_module() = default;
  const char* name() const { return name_.c_str(); }

 private:
  std::string name_;
};

inline double& current_time_ns_ref() {
  static double now_ns = 0.0;
  return now_ns;
}

inline sc_time sc_time_stamp() { return sc_time(current_time_ns_ref(), SC_NS); }
inline void wait(const sc_time& delta) { current_time_ns_ref() += delta.to_double(); }
inline void wait(double value, sc_time_unit unit) { current_time_ns_ref() += value * unit_scale_ns(unit); }
inline void sc_start() {}
inline void sc_stop() {}

}  // namespace sc_core

inline std::ostream& operator<<(std::ostream& os, const sc_core::sc_time& time) {
  os << time.to_string();
  return os;
}

#define SC_HAS_PROCESS(module_type)
#endif
