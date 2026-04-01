#include "interconnect.hpp"

namespace qebs {

Interconnect::Interconnect(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      host_to_fpga_channel_{"host->fpga", sc_core::sc_time(30.0, sc_core::SC_NS)},
      fpga_to_chip_channel_{"fpga->chip", sc_core::sc_time(18.0, sc_core::SC_NS)},
      chip_to_fpga_channel_{"chip->fpga", sc_core::sc_time(16.0, sc_core::SC_NS)},
      fpga_to_host_channel_{"fpga->host", sc_core::sc_time(24.0, sc_core::SC_NS)} {}

void Interconnect::transfer(const ChannelProfile& channel,
                            const std::string& payload) const {
  log_line(name(), "channel " + channel.name + " payload: " + payload);
  sc_core::wait(channel.latency);
}

void Interconnect::host_to_fpga(const std::string& payload) const {
  transfer(host_to_fpga_channel_, payload);
}

void Interconnect::fpga_to_chip(const std::string& payload) const {
  transfer(fpga_to_chip_channel_, payload);
}

void Interconnect::chip_to_fpga(const std::string& payload) const {
  transfer(chip_to_fpga_channel_, payload);
}

void Interconnect::fpga_to_host(const std::string& payload) const {
  transfer(fpga_to_host_channel_, payload);
}

}  // namespace qebs
