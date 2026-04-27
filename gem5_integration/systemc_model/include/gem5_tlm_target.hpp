#ifndef GEM5_TLM_TARGET_HPP
#define GEM5_TLM_TARGET_HPP

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>
#include <vector>
#include <cstdint>

using namespace sc_core;
using namespace tlm;

namespace qebs {
  class DFTHybridSystemGem5;
}

class Gem5TLMTarget : public sc_module {
 public:
  tlm_utils::simple_target_socket<Gem5TLMTarget> target_socket;

  SC_HAS_PROCESS(Gem5TLMTarget);

  Gem5TLMTarget(sc_module_name name, qebs::DFTHybridSystemGem5* dft_system);
  ~Gem5TLMTarget();

  void b_transport(tlm_generic_payload& trans, sc_time& delay);
  unsigned int transport_dbg(tlm_generic_payload& trans);
  bool get_direct_mem_ptr(tlm_generic_payload& trans, tlm_dmi& dmi_data);

 private:
  enum Registers {
    REG_CONTROL       = 0x0000,
    REG_STATUS        = 0x0004,
    REG_INTERRUPT     = 0x0008,
    REG_DMA_SRC_LO    = 0x0010,
    REG_DMA_SRC_HI    = 0x0014,
    REG_DMA_DST_LO    = 0x0018,
    REG_DMA_DST_HI    = 0x001C,
    REG_DMA_SIZE      = 0x0020,
    REG_DMA_CONTROL   = 0x0024,

    REG_ELECTRONS_CMD = 0x0128,
    REG_ELECTRONS_CONVERGED = 0x0130,
  };

  qebs::DFTHybridSystemGem5* dft_system_;

  uint32_t control_reg_;
  uint32_t status_reg_;
  uint32_t interrupt_reg_;
  uint64_t dma_src_addr_;
  uint64_t dma_dst_addr_;
  uint32_t dma_size_;

  static const size_t DEVICE_MEMORY_SIZE = 1024 * 1024 * 1024;
  std::vector<uint8_t> device_memory_;

  void handle_read(tlm_generic_payload& trans, sc_time& delay);
  void handle_write(tlm_generic_payload& trans, sc_time& delay);
  uint32_t read_register(uint64_t addr);
  void write_register(uint64_t addr, uint32_t value);

  // Timing annotation methods
  double get_register_read_latency(uint64_t addr);
  double get_register_write_latency(uint64_t addr);

  void handle_dma_transfer();
  void handle_electrons_command(const uint8_t* request_data, size_t request_size);
  void log_transaction(const tlm_generic_payload& trans, const char* phase);
};

#endif
