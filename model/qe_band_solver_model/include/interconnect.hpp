#pragma once

#include <string>

#include "logging.hpp"
#include "systemc_compat.hpp"

namespace qebs {

struct ChannelProfile {
  std::string name;
  sc_core::sc_time latency;
};

class Interconnect : public sc_core::sc_module {
 public:
  explicit Interconnect(sc_core::sc_module_name name);

  void host_to_fpga(const std::string& payload) const;
  void fpga_to_chip(const std::string& payload) const;
  void chip_to_fpga(const std::string& payload) const;
  void fpga_to_host(const std::string& payload) const;

 private:
  void transfer(const ChannelProfile& channel, const std::string& payload) const;

  ChannelProfile host_to_fpga_channel_;
  ChannelProfile fpga_to_chip_channel_;
  ChannelProfile chip_to_fpga_channel_;
  ChannelProfile fpga_to_host_channel_;
};

}  // namespace qebs
