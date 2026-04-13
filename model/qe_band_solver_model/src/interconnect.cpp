#include "interconnect.hpp"

#include <algorithm>
#include <cmath>
#include <sstream>

namespace qebs {

Interconnect::Interconnect(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      host_control_channel_{"host-control->device-runtime",
                            sc_core::sc_time(28.0, sc_core::SC_NS),
                            0.0,
                            0x1000},
      host_to_device_dma_channel_{"host-dma->device-memory",
                                  sc_core::sc_time(20.0, sc_core::SC_NS),
                                  24.0,
                                  0x2000},
      device_to_host_dma_channel_{"device-dma->host-memory",
                                  sc_core::sc_time(18.0, sc_core::SC_NS),
                                  24.0,
                                  0x3000},
      device_completion_channel_{"device-completion->host",
                                 sc_core::sc_time(22.0, sc_core::SC_NS),
                                 0.0,
                                 0x4000} {}

int Interconnect::b_transport(const ChannelProfile& channel,
                              const std::string& semantic,
                              unsigned int bytes) const {
  tlm::tlm_generic_payload payload;
  payload.set_command(tlm::TLM_WRITE_COMMAND);
  payload.set_address(channel.address_base);
  payload.set_data_length(bytes);
  payload.set_streaming_width(bytes);
  payload.set_response_status(tlm::TLM_INCOMPLETE_RESPONSE);

  double total_delay_ns = channel.base_latency.to_double();
  if (channel.gib_per_s > 0.0 && bytes > 0) {
    const double bytes_per_ns =
        channel.gib_per_s * static_cast<double>(1ull << 30) / 1.0e9;
    total_delay_ns += static_cast<double>(bytes) / std::max(1e-9, bytes_per_ns);
  }

  const auto delay = sc_core::sc_time(total_delay_ns, sc_core::SC_NS);
  std::ostringstream oss;
  oss << "TLM b_transport channel=" << channel.name
      << ", semantic=" << semantic
      << ", addr=0x" << std::hex << channel.address_base << std::dec
      << ", bytes=" << bytes
      << ", delay=" << delay.to_string();
  log_line(name(), oss.str());
  sc_core::wait(delay);
  payload.set_response_status(tlm::TLM_OK_RESPONSE);
  return std::max(1, static_cast<int>(std::lround(total_delay_ns)));
}

int Interconnect::transport_control(const ChannelProfile& channel,
                                    const std::string& semantic,
                                    unsigned int bytes) const {
  return b_transport(channel, semantic, bytes);
}

int Interconnect::transport_dma(const ChannelProfile& channel,
                                const DmaTransferDesc& transfer) const {
  const auto bytes =
      static_cast<unsigned int>(std::max(0.0, transfer.kib) * 1024.0);
  return b_transport(channel, transfer.brief(), bytes);
}

int Interconnect::submit_iteration_request(
    const ScfIterationRequest& request) const {
  return transport_control(host_control_channel_,
                           "ScfIterationRequest {" + request.brief() + "}",
                           192);
}

int Interconnect::preload_resident_set(const ResidentSetDesc& resident_set) const {
  DmaTransferDesc transfer;
  transfer.transfer_id = resident_set.resident_set_id + "-preload";
  transfer.channel_kind = "H2D_DMA";
  transfer.payload_kind = "resident_set";
  transfer.src_scope = "HOST_DRAM";
  transfer.dst_scope = "DEVICE_HBM";
  transfer.kib = resident_set.preload_kib;
  transfer.double_buffered = false;
  return transport_dma(host_to_device_dma_channel_, transfer);
}

int Interconnect::stream_band_batch(const BandBatchDesc& batch) const {
  DmaTransferDesc transfer;
  transfer.transfer_id = "batch-" + std::to_string(batch.batch_id) + "-wave";
  transfer.channel_kind = "H2D_DMA";
  transfer.payload_kind = "band_batch";
  transfer.src_scope = "HOST_DRAM";
  transfer.dst_scope = "DEVICE_HBM";
  transfer.kib = batch.input_wave_kib;
  transfer.double_buffered = batch.double_buffered;
  return transport_dma(host_to_device_dma_channel_, transfer);
}

int Interconnect::dma_to_device(const DmaTransferDesc& transfer) const {
  return transport_dma(host_to_device_dma_channel_, transfer);
}

int Interconnect::dma_to_host(const DmaTransferDesc& transfer) const {
  return transport_dma(device_to_host_dma_channel_, transfer);
}

int Interconnect::notify_completion(const CompletionSummary& completion) const {
  return transport_control(device_completion_channel_,
                           "CompletionSummary {" + completion.brief() + "}",
                           224);
}

int Interconnect::host_to_fpga(const std::string& payload) const {
  return transport_control(host_control_channel_, payload, 128);
}

int Interconnect::fpga_to_chip(const std::string& payload) const {
  return transport_control(host_control_channel_, payload, 128);
}

int Interconnect::chip_to_fpga(const std::string& payload) const {
  return transport_control(device_completion_channel_, payload, 128);
}

int Interconnect::fpga_to_host(const std::string& payload) const {
  return transport_control(device_completion_channel_, payload, 128);
}

}  // namespace qebs
