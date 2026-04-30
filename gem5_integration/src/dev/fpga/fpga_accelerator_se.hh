#ifndef __DEV_FPGA_FPGA_ACCELERATOR_SE_HH__
#define __DEV_FPGA_FPGA_ACCELERATOR_SE_HH__

#include "dev/io_device.hh"
#include "params/FPGAAcceleratorSE.hh"
#include "sim/eventq.hh"

#include <string>

namespace gem5
{

class FPGAAcceleratorSE : public BasicPioDevice
{
  private:
    static const int REG_CONTROL = 0x00;
    static const int REG_STATUS = 0x04;
    static const int REG_N_BANDS = 0x08;
    static const int REG_N_BASIS = 0x0C;
    static const int REG_CYCLES = 0x10;
    static const int REG_OBSERVED_READ_COUNT = 0x20;
    static const int REG_OBSERVED_WRITE_COUNT = 0x24;
    static const int REG_POLLING_READ_COUNT = 0x28;
    static const int REG_COMMAND_ISSUE_TICK_LO = 0x2C;
    static const int REG_COMMAND_ISSUE_TICK_HI = 0x30;
    static const int REG_DEVICE_ACCEPT_TICK_LO = 0x34;
    static const int REG_DEVICE_ACCEPT_TICK_HI = 0x38;
    static const int REG_COMPLETION_TICK_LO = 0x3C;
    static const int REG_COMPLETION_TICK_HI = 0x40;
    static const int REG_EVENT_DELTA_TICKS_LO = 0x44;
    static const int REG_EVENT_DELTA_TICKS_HI = 0x48;

    uint32_t controlReg;
    uint32_t statusReg;
    uint32_t nBands;
    uint32_t nBasis;
    uint32_t cycles;
    uint64_t observedReadCount;
    uint64_t observedWriteCount;
    uint64_t pollingReadCount;
    Tick commandIssueTick;
    Tick deviceAcceptTick;
    Tick completionTick;
    Tick eventDeltaTicks;

    const bool strictEventTiming;
    const std::string candidateProfileRef;
    const uint64_t candidateEventDelayTicks;
    const uint64_t candidateDmaReadBytes;
    const uint64_t candidateDmaWriteBytes;
    const std::string strictEventReportPath;
    EventFunctionWrapper completionEvent;

  public:
    typedef FPGAAcceleratorSEParams Params;
    FPGAAcceleratorSE(const Params &p);

    Tick read(PacketPtr pkt) override;
    Tick write(PacketPtr pkt) override;

  private:
    void executeComputation();
    void completeComputation();
    void writeStrictEventReport() const;
    uint32_t tickLow(Tick value) const;
    uint32_t tickHigh(Tick value) const;
};

}

#endif
