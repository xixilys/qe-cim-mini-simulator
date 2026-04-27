#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "tlm_compat.hpp"
#include "types.hpp"

namespace qebs {

struct ChannelProfile {
  std::string name;
  sc_core::sc_time base_latency;
  double gib_per_s = 0.0;
  std::uint64_t address_base = 0;
};

class Interconnect : public sc_core::sc_module {
 public:
  explicit Interconnect(sc_core::sc_module_name name);

  int submit_iteration_request(const ScfIterationRequest& request) const;
  int preload_resident_set(const ResidentSetDesc& resident_set) const;
  int stream_band_batch(const BandBatchDesc& batch) const;
  int dma_to_device(const DmaTransferDesc& transfer) const;
  int dma_to_host(const DmaTransferDesc& transfer) const;
  int notify_completion(const CompletionSummary& completion) const;

  // Legacy string transports retained so archive-era support paths still compile.
  int host_to_fpga(const std::string& payload) const;
  int fpga_to_chip(const std::string& payload) const;
  int chip_to_fpga(const std::string& payload) const;
  int fpga_to_host(const std::string& payload) const;

 private:
  int transport_control(const ChannelProfile& channel,
                        const std::string& semantic,
                        unsigned int bytes) const;
  int transport_dma(const ChannelProfile& channel,
                    const DmaTransferDesc& transfer) const;
  int b_transport(const ChannelProfile& channel,
                  const std::string& semantic,
                  unsigned int bytes) const;

  ChannelProfile host_control_channel_;
  ChannelProfile host_to_device_dma_channel_;
  ChannelProfile device_to_host_dma_channel_;
  ChannelProfile device_completion_channel_;
};

}  // namespace qebs
