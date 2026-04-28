// src/dev/fpga/fpga_accelerator.hh
// FPGA Accelerator PCIe Device for gem5
// Uses internal sc_module to hold TLM socket per gem5 SystemC integration rules

#ifndef __DEV_FPGA_FPGA_ACCELERATOR_HH__
#define __DEV_FPGA_FPGA_ACCELERATOR_HH__

#include "dev/pci/device.hh"
#include "dev/dma_device.hh"
#include "params/FPGAAccelerator.hh"
#include <string>
#include <vector>

#ifdef USE_SYSTEMC
#include "systemc/core/kernel.hh"
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>
#endif

namespace gem5 {

#ifdef USE_SYSTEMC
// Internal sc_module to hold TLM socket, since sc_port must live inside sc_module
class FPGATLMMediator : public sc_core::sc_module {
  public:
    tlm_utils::simple_initiator_socket<FPGATLMMediator> tlmSocket;

    FPGATLMMediator(sc_core::sc_module_name name)
        : sc_core::sc_module(name), tlmSocket("tlm_socket") {}
};

// Stub target to satisfy SystemC binding
// Note: For real model integration, rebuild libgem5_systemc_bridge.a for host arch
class FPGATLMStub : public sc_core::sc_module {
  public:
    tlm_utils::simple_target_socket<FPGATLMStub> tlmSocket;

    FPGATLMStub(sc_core::sc_module_name name);

    void b_transport(tlm::tlm_generic_payload &trans,
                     sc_core::sc_time &delay);
};
#endif

class FPGAAccelerator : public PciEndpoint {
  public:
    typedef FPGAAcceleratorParams Params;
    FPGAAccelerator(const Params &p);
    ~FPGAAccelerator();

    Tick readConfig(PacketPtr pkt) override;
    Tick writeConfig(PacketPtr pkt) override;

    Tick readDevice(PacketPtr pkt) override;
    Tick writeDevice(PacketPtr pkt) override;

    void init() override;
    void startup() override;

    void serialize(CheckpointOut &cp) const override;
    void unserialize(CheckpointIn &cp) override;

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

        REG_ELECTRONS_N_BANDS     = 0x0100,
        REG_ELECTRONS_N_BASIS     = 0x0104,
        REG_ELECTRONS_N_KPOINTS   = 0x0108,
        REG_ELECTRONS_N_SPIN      = 0x010C,
        REG_ELECTRONS_MAX_ITER    = 0x0110,
        REG_ELECTRONS_CONV_THR    = 0x0114,
        REG_ELECTRONS_DIAG_THR    = 0x0118,
        REG_ELECTRONS_MIXING_BETA = 0x011C,
        REG_ELECTRONS_MIXING_NDIM = 0x0120,
        REG_ELECTRONS_ENABLE_CIM  = 0x0124,
        REG_ELECTRONS_CMD         = 0x0128,
        REG_ELECTRONS_STATUS      = 0x012C,

        REG_ELECTRONS_CONVERGED   = 0x0130,
        REG_ELECTRONS_ITERATIONS  = 0x0134,
        REG_ELECTRONS_FINAL_ERROR = 0x0138,
        REG_ELECTRONS_TOTAL_ENERGY= 0x013C,
        REG_ELECTRONS_TOTAL_TIME  = 0x0140,
        REG_ELECTRONS_CBANDS_TIME = 0x0144,
        REG_ELECTRONS_SUMBAND_TIME= 0x0148,
        REG_ELECTRONS_MIXRHO_TIME = 0x014C,

        REG_H_MATRIX_ADDR_LO      = 0x0200,
        REG_H_MATRIX_ADDR_HI      = 0x0204,
        REG_S_MATRIX_ADDR_LO      = 0x0208,
        REG_S_MATRIX_ADDR_HI      = 0x020C,
        REG_RHO_ADDR_LO           = 0x0210,
        REG_RHO_ADDR_HI           = 0x0214,
        REG_VEFF_ADDR_LO          = 0x0218,
        REG_VEFF_ADDR_HI          = 0x021C,
    };

    enum ControlBits {
        CTRL_RESET        = (1 << 0),
        CTRL_ENABLE       = (1 << 1),
        CTRL_IRQ_ENABLE   = (1 << 2),
    };

    enum StatusBits {
        STATUS_READY      = (1 << 0),
        STATUS_BUSY       = (1 << 1),
        STATUS_ERROR      = (1 << 2),
        STATUS_DMA_DONE   = (1 << 3),
        STATUS_COMPUTE_DONE = (1 << 4),
    };

    enum class ExecutionMode {
        Smoke,
        TimedProxy,
        RealBridge,
    };

    enum CompletionSource {
        COMPLETION_NONE = 0,
        COMPLETION_SMOKE_IMMEDIATE = 1,
        COMPLETION_TIMED_EVENT = 2,
        COMPLETION_REAL_BRIDGE_EVENT = 3,
    };

    uint32_t controlReg;
    uint32_t statusReg;
    uint32_t interruptReg;
    uint64_t dmaSrcAddr;
    uint64_t dmaDstAddr;
    uint32_t dmaSize;

    uint32_t electronsNBands;
    uint32_t electronsNBasis;
    uint32_t electronsNKpoints;
    uint32_t electronsNSpin;
    uint32_t electronsMaxIter;
    float electronsConvThr;
    float electronsDiagThr;
    float electronsMixingBeta;
    uint32_t electronsMixingNdim;
    uint32_t electronsEnableCim;

    uint32_t electronsConverged;
    uint32_t electronsIterations;
    float electronsFinalError;
    float electronsTotalEnergy;
    uint64_t electronsTotalTime;
    uint64_t electronsCbandsTime;
    uint64_t electronsSumbandTime;
    uint64_t electronsMixrhoTime;

    uint64_t hMatrixAddr;
    uint64_t sMatrixAddr;
    uint64_t rhoAddr;
    uint64_t veffAddr;

    ExecutionMode executionMode;
    bool realSystemCTarget;
    uint32_t electronsCommandCount;
    uint32_t electronsCompletionCount;
    Tick electronsLastCommandTick;
    Tick electronsLastDoneTick;
    uint32_t electronsCompletionSource;
    uint32_t pendingElectronsCompletionSource;

    class DMAEngine {
      private:
        enum class State { IDLE, DMA_READING, DMA_WRITING, COMPLETING };

        FPGAAccelerator *parent;
        State state;
        Addr curSrc;
        Addr curDst;
        size_t remaining;
        std::vector<uint8_t> buffer;
        bool toDevice;

        EventFunctionWrapper readCompleteEvent;
        EventFunctionWrapper writeCompleteEvent;

        void readComplete();
        void writeComplete();

      public:
        DMAEngine(FPGAAccelerator *p);
        void startTransfer(Addr src, Addr dst, size_t size, bool to_dev);
        void onTransferComplete();
        bool isBusy() const { return state != State::IDLE; }
    };

    DMAEngine *dmaEngine;

#ifdef USE_SYSTEMC
    FPGATLMMediator *tlmMediator;
    FPGATLMStub *tlmStub;

    void sendTLMTransaction(tlm::tlm_command cmd, uint64_t addr,
                           uint8_t *data, size_t size);
#endif

    void executeElectrons();
    void executeCompute();
    void completeElectrons(uint32_t completionSource);
    bool immediateElectronsCompletion() const;

    void raiseInterrupt();
    void clearInterrupt();

    uint32_t readRegister(Addr offset);
    void writeRegister(Addr offset, uint32_t value);

    EventFunctionWrapper dmaCompleteEvent;
    EventFunctionWrapper computeDoneEvent;
    EventFunctionWrapper electronsDoneEvent;
    EventFunctionWrapper tlmResponseEvent;
};

} // namespace gem5

#endif // __DEV_FPGA_FPGA_ACCELERATOR_HH__
