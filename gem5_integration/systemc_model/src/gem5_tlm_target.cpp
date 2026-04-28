#include "gem5_tlm_target.hpp"
#include "dft_hybrid_system_gem5.hpp"
#include <iostream>
#include <iomanip>
#include <cstring>
#include <algorithm>

// Timing parameters for timed-functional proxy model
// All times in nanoseconds
namespace TimingParams {
    // Register access latencies
    constexpr double CTRL_REG_LATENCY = 5.0;      // Control/status registers
    constexpr double DMA_REG_LATENCY = 10.0;       // DMA configuration registers
    constexpr double ELECTRONS_CMD_LATENCY = 50.0; // Electrons command trigger

    // Computation latencies (per iteration)
    constexpr double C_BANDS_TIME_PER_KPOINT = 100000.0;  // 100 μs per k-point (cluster A/B/C/D)
    constexpr double SUM_BAND_TIME = 1000.0;               // 1 μs sum band
    constexpr double MIX_RHO_TIME = 500.0;                 // 0.5 μs mix rho

    // DMA transfer bandwidth: 4 GB/s = 0.25 ns/byte
    constexpr double DMA_BW_NS_PER_BYTE = 0.25;

    // Interrupt latency
    constexpr double INTERRUPT_LATENCY = 100.0;  // 100 ns
}

Gem5TLMTarget::Gem5TLMTarget(sc_module_name name, qebs::DFTHybridSystemGem5* dft_system)
    : sc_module(name),
      target_socket("target_socket"),
      dft_system_(dft_system),
      control_reg_(0),
      status_reg_(0x00000001),
      interrupt_reg_(0),
      dma_src_addr_(0),
      dma_dst_addr_(0),
      dma_size_(0),
      electrons_command_count_(0),
      host_launch_count_(0),
      completion_count_(0),
      fallback_count_(0),
      polling_read_count_(0),
      interrupt_count_(0),
      dma_read_bytes_(0),
      dma_write_bytes_(0),
      bytes_moved_to_convergence_(0),
      resident_reuse_ratio_(0.0),
      spill_ratio_(0.0),
      fallback_ratio_(0.0),
      last_control_policy_("sync")
{
  target_socket.register_b_transport(this, &Gem5TLMTarget::b_transport);
  target_socket.register_transport_dbg(this, &Gem5TLMTarget::transport_dbg);
  target_socket.register_get_direct_mem_ptr(this, &Gem5TLMTarget::get_direct_mem_ptr);

  device_memory_.resize(DEVICE_MEMORY_SIZE, 0);

  std::cout << "[" << sc_time_stamp() << "] " << name
            << ": TLM target initialized (timed-functional proxy mode, "
            << "registers=0x0000-0x013f, hbm=0x" << std::hex
            << DEVICE_MEMORY_BASE << "-0x" << (DEVICE_MEMORY_BASE + DEVICE_MEMORY_SIZE - 1)
            << std::dec << ")" << std::endl;
}

Gem5TLMTarget::~Gem5TLMTarget() {
}

void Gem5TLMTarget::b_transport(tlm_generic_payload& trans, sc_time& delay) {
  log_transaction(trans, "b_transport");

  tlm_command cmd = trans.get_command();
  uint64_t addr = trans.get_address();
  unsigned int data_length = trans.get_data_length();

  if (cmd != TLM_READ_COMMAND && cmd != TLM_WRITE_COMMAND) {
    trans.set_response_status(TLM_COMMAND_ERROR_RESPONSE);
    return;
  }

  if (is_register_address(addr)) {
    if (cmd == TLM_READ_COMMAND) {
      handle_read(trans, delay);
    } else {
      handle_write(trans, delay);
    }
    return;
  }

  if (is_device_memory_range(addr, data_length)) {
    unsigned char* data_ptr = trans.get_data_ptr();
    size_t offset = device_memory_offset(addr);

    if (cmd == TLM_READ_COMMAND) {
      memcpy(data_ptr, &device_memory_[offset], data_length);
      // Memory read: 10 ns base + 1 ns per 32-bit word
      delay += sc_time(10.0 + data_length / 4.0, SC_NS);
    } else {
      memcpy(&device_memory_[offset], data_ptr, data_length);
      // Memory write: 10 ns base + 1 ns per 32-bit word
      delay += sc_time(10.0 + data_length / 4.0, SC_NS);
    }
    trans.set_response_status(TLM_OK_RESPONSE);
    return;
  }

  trans.set_response_status(TLM_ADDRESS_ERROR_RESPONSE);
}

void Gem5TLMTarget::handle_read(tlm_generic_payload& trans, sc_time& delay) {
  uint64_t addr = trans.get_address();
  unsigned char* data_ptr = trans.get_data_ptr();
  unsigned int data_length = trans.get_data_length();

  if (data_length != 4) {
    trans.set_response_status(TLM_BURST_ERROR_RESPONSE);
    return;
  }

  uint32_t value = read_register(addr);
  if (addr == REG_STATUS || addr == REG_ELECTRONS_CONVERGED) {
    ++polling_read_count_;
  }
  memcpy(data_ptr, &value, sizeof(value));

  // Add timing annotation based on register type
  delay += sc_time(get_register_read_latency(addr), SC_NS);
  trans.set_response_status(TLM_OK_RESPONSE);

  std::cout << "[" << sc_time_stamp() << "] TLM READ: addr=0x"
            << std::hex << addr << std::dec
            << " value=0x" << std::hex << value << std::dec
            << " delay=" << delay.to_double() << "ns" << std::endl;
}

void Gem5TLMTarget::handle_write(tlm_generic_payload& trans, sc_time& delay) {
  uint64_t addr = trans.get_address();
  unsigned char* data_ptr = trans.get_data_ptr();
  unsigned int data_length = trans.get_data_length();

  if (data_length != 4) {
    trans.set_response_status(TLM_BURST_ERROR_RESPONSE);
    return;
  }

  uint32_t value = 0;
  memcpy(&value, data_ptr, sizeof(value));
  write_register(addr, value);

  // Add timing annotation based on register type
  delay += sc_time(get_register_write_latency(addr), SC_NS);
  trans.set_response_status(TLM_OK_RESPONSE);

  std::cout << "[" << sc_time_stamp() << "] TLM WRITE: addr=0x"
            << std::hex << addr << std::dec
            << " value=0x" << std::hex << value << std::dec
            << " delay=" << delay.to_double() << "ns" << std::endl;
}

double Gem5TLMTarget::get_register_read_latency(uint64_t addr) {
  // Return latency in nanoseconds based on register address
  if (addr >= CONTROL_WINDOW_BASE && addr < CONTROL_WINDOW_BASE + CONTROL_WINDOW_SIZE) {
    // Control/Status/Interrupt: fast access
    return TimingParams::CTRL_REG_LATENCY;
  } else if (addr >= DMA_DESC_WINDOW_BASE && addr < DMA_DESC_WINDOW_BASE + DMA_DESC_WINDOW_SIZE) {
    // DMA descriptor/control registers
    return TimingParams::DMA_REG_LATENCY;
  } else if (addr >= COMMAND_WINDOW_BASE && addr < COMMAND_WINDOW_BASE + COMMAND_WINDOW_SIZE) {
    // Command registers: medium latency
    return TimingParams::CTRL_REG_LATENCY * 2;
  } else if (addr >= RESULT_MAILBOX_WINDOW_BASE && addr < RESULT_MAILBOX_WINDOW_BASE + RESULT_MAILBOX_WINDOW_SIZE) {
    // Result/mailbox registers: medium latency
    return TimingParams::CTRL_REG_LATENCY * 2;
  }
  return TimingParams::CTRL_REG_LATENCY;
}

double Gem5TLMTarget::get_register_write_latency(uint64_t addr) {
  // Write latency typically same as read for most registers
  if (addr == REG_ELECTRONS_CMD) {
    // Command trigger has higher latency (may initiate computation)
    return TimingParams::ELECTRONS_CMD_LATENCY;
  } else if (addr == REG_DMA_CONTROL) {
    // DMA control triggers DMA transfer
    return TimingParams::DMA_REG_LATENCY;
  }
  return get_register_read_latency(addr);
}


bool Gem5TLMTarget::is_register_address(uint64_t addr) const {
  switch (addr) {
    case REG_CONTROL:
    case REG_STATUS:
    case REG_INTERRUPT:
    case REG_DMA_SRC_LO:
    case REG_DMA_SRC_HI:
    case REG_DMA_DST_LO:
    case REG_DMA_DST_HI:
    case REG_DMA_SIZE:
    case REG_DMA_CONTROL:
    case REG_ELECTRONS_CMD:
    case REG_ELECTRONS_CONVERGED:
      return true;
    default:
      return false;
  }
}

bool Gem5TLMTarget::is_device_memory_range(uint64_t addr, unsigned int length) const {
  if (length == 0 || addr < DEVICE_MEMORY_BASE) {
    return false;
  }
  uint64_t offset = addr - DEVICE_MEMORY_BASE;
  return offset < DEVICE_MEMORY_SIZE && length <= DEVICE_MEMORY_SIZE - offset;
}

size_t Gem5TLMTarget::device_memory_offset(uint64_t addr) const {
  return static_cast<size_t>(addr - DEVICE_MEMORY_BASE);
}

uint32_t Gem5TLMTarget::read_register(uint64_t addr) {
  switch (addr) {
    case REG_CONTROL:
      return control_reg_;
    case REG_STATUS:
      return status_reg_;
    case REG_INTERRUPT:
      return interrupt_reg_;
    case REG_DMA_SRC_LO:
      return (uint32_t)(dma_src_addr_ & 0xFFFFFFFF);
    case REG_DMA_SRC_HI:
      return (uint32_t)(dma_src_addr_ >> 32);
    case REG_DMA_DST_LO:
      return (uint32_t)(dma_dst_addr_ & 0xFFFFFFFF);
    case REG_DMA_DST_HI:
      return (uint32_t)(dma_dst_addr_ >> 32);
    case REG_DMA_SIZE:
      return dma_size_;
    case REG_ELECTRONS_CMD:
      return electrons_command_count_;
    case REG_ELECTRONS_CONVERGED:
      return (status_reg_ & 0x00000010) ? 1 : 0;
    default:
      std::cerr << "Warning: read from unknown register 0x"
                << std::hex << addr << std::dec << std::endl;
      return 0;
  }
}

void Gem5TLMTarget::write_register(uint64_t addr, uint32_t value) {
  switch (addr) {
    case REG_CONTROL:
      control_reg_ = value;
      if (value & 0x01) {
        status_reg_ = 0x00000001;
        control_reg_ &= ~0x01;
        std::cout << "[" << sc_time_stamp() << "] Device reset" << std::endl;
      }
      break;

    case REG_DMA_SRC_LO:
      dma_src_addr_ = (dma_src_addr_ & 0xFFFFFFFF00000000ULL) | value;
      break;

    case REG_DMA_SRC_HI:
      dma_src_addr_ = (dma_src_addr_ & 0xFFFFFFFF) | ((uint64_t)value << 32);
      break;

    case REG_DMA_DST_LO:
      dma_dst_addr_ = (dma_dst_addr_ & 0xFFFFFFFF00000000ULL) | value;
      break;

    case REG_DMA_DST_HI:
      dma_dst_addr_ = (dma_dst_addr_ & 0xFFFFFFFF) | ((uint64_t)value << 32);
      break;

    case REG_DMA_SIZE:
      dma_size_ = value;
      break;

    case REG_DMA_CONTROL:
      if (value == 1) {
        dma_read_bytes_ += dma_size_;
        handle_dma_transfer();
      } else if (value == 2) {
        dma_write_bytes_ += dma_size_;
        handle_dma_transfer();
      }
      break;

    case REG_ELECTRONS_CMD:
      if (value == 1) {
        ++electrons_command_count_;
        if (dma_src_addr_ != 0 && dma_size_ > 0) {
          if (is_device_memory_range(dma_src_addr_, dma_size_)) {
            handle_electrons_command(&device_memory_[device_memory_offset(dma_src_addr_)], dma_size_);
          } else {
            std::cerr << "Error: electrons request data not in device memory" << std::endl;
          }
        }
      }
      break;

    default:
      std::cerr << "Warning: write to unknown register 0x"
                << std::hex << addr << std::dec << std::endl;
      break;
  }
}

void Gem5TLMTarget::handle_dma_transfer() {
  sc_time start_time = sc_time_stamp();

  std::cout << "[" << start_time << "] DMA transfer started: "
            << "src=0x" << std::hex << dma_src_addr_
            << " dst=0x" << dma_dst_addr_
            << " size=" << std::dec << dma_size_ << std::endl;

  // Calculate transfer time based on bandwidth
  double transfer_time_ns = dma_size_ * TimingParams::DMA_BW_NS_PER_BYTE;
  transfer_time_ns = std::max(transfer_time_ns, 100.0);  // Minimum 100ns

  // Simulate DMA transfer with timing
  wait(transfer_time_ns, SC_NS);

  sc_time end_time = sc_time_stamp();
  status_reg_ |= 0x00000008;  // DMA done flag
  interrupt_reg_ = 1;
  ++interrupt_count_;

  std::cout << "[" << end_time << "] DMA transfer complete: "
            << "time=" << (end_time - start_time).to_double() << "ns" << std::endl;
}

void Gem5TLMTarget::handle_electrons_command(const uint8_t* request_data, size_t request_size) {
  if (!dft_system_) {
    std::cerr << "Error: DFT system not connected" << std::endl;
    return;
  }

  sc_time start_time = sc_time_stamp();

  std::cout << "[" << start_time << "] Electrons command received, size="
            << request_size << " bytes" << std::endl;

  status_reg_ |= 0x00000002;  // Busy flag
  status_reg_ &= ~0x00000010;  // Clear done flag
  ++host_launch_count_;

  qebs::DFTHybridSystemGem5::ElectronsRequest req;
  if (request_size >= sizeof(req)) {
    memcpy(&req, request_data, sizeof(req));
    last_control_policy_ = "sync";
    switch (req.control_policy) {
      case 1:
        last_control_policy_ = "async_queue";
        break;
      case 2:
        last_control_policy_ = "polling";
        break;
      case 3:
        last_control_policy_ = "interrupt_ready";
        break;
      default:
        last_control_policy_ = "sync";
        break;
    }

    std::cout << "  n_bands=" << req.n_bands
              << " max_iter=" << req.max_iterations
              << " conv_thr=" << req.conv_threshold
              << " control_policy=" << last_control_policy_ << std::endl;

    // Execute with timing - this will consume SystemC time
    qebs::DFTHybridSystemGem5::ElectronsResult result =
        dft_system_->execute_electrons_from_gem5(req);

    // Copy result to device memory
    if (is_device_memory_range(dma_dst_addr_, sizeof(result))) {
      memcpy(&device_memory_[device_memory_offset(dma_dst_addr_)], &result, sizeof(result));
    }

    dma_read_bytes_ += result.dma_read_bytes;
    dma_write_bytes_ += result.dma_write_bytes;
    bytes_moved_to_convergence_ = result.bytes_moved_to_convergence;
    fallback_ratio_ = result.fallback_ratio;
    resident_reuse_ratio_ = result.resident_reuse_ratio;
    spill_ratio_ = result.spill_ratio;
    fallback_count_ += static_cast<uint32_t>(result.fallback_ratio > 0.0 ? 1 : 0);
    ++completion_count_;

    if (result.converged) {
      status_reg_ |= 0x00000010;  // Done flag
    }

    sc_time end_time = sc_time_stamp();
    std::cout << "[" << end_time << "] Electrons loop complete: "
              << "converged=" << result.converged
              << " iterations=" << result.iterations
              << " energy=" << result.total_energy << " Ry"
              << " time=" << (end_time - start_time).to_double() / 1e6 << " ms" << std::endl;
  } else {
    std::cerr << "Error: invalid request size" << std::endl;
  }

  status_reg_ &= ~0x00000002;  // Clear busy flag
  interrupt_reg_ = 1;
  ++interrupt_count_;
}

unsigned int Gem5TLMTarget::transport_dbg(tlm_generic_payload& trans) {
  tlm_command cmd = trans.get_command();
  uint64_t addr = trans.get_address();
  unsigned char* data_ptr = trans.get_data_ptr();
  unsigned int data_length = trans.get_data_length();

  if (is_device_memory_range(addr, data_length)) {
    size_t offset = device_memory_offset(addr);
    if (cmd == TLM_READ_COMMAND) {
      memcpy(data_ptr, &device_memory_[offset], data_length);
    } else if (cmd == TLM_WRITE_COMMAND) {
      memcpy(&device_memory_[offset], data_ptr, data_length);
    } else {
      return 0;
    }
    return data_length;
  }

  return 0;
}

bool Gem5TLMTarget::get_direct_mem_ptr(tlm_generic_payload& trans,
                                       tlm_dmi& dmi_data) {
  return false;
}

void Gem5TLMTarget::log_transaction(const tlm_generic_payload& trans,
                                    const char* phase) {
  std::cout << "[" << sc_time_stamp() << "] " << phase << ": "
            << (trans.get_command() == TLM_READ_COMMAND ? "READ" : "WRITE")
            << " addr=0x" << std::hex << trans.get_address()
            << " len=" << std::dec << trans.get_data_length()
            << std::endl;
}
