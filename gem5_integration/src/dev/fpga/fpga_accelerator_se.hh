#ifndef __DEV_FPGA_FPGA_ACCELERATOR_SE_HH__
#define __DEV_FPGA_FPGA_ACCELERATOR_SE_HH__

#include "dev/io_device.hh"
#include "params/FPGAAcceleratorSE.hh"

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

    uint32_t controlReg;
    uint32_t statusReg;
    uint32_t nBands;
    uint32_t nBasis;
    uint32_t cycles;

  public:
    typedef FPGAAcceleratorSEParams Params;
    FPGAAcceleratorSE(const Params &p);

    Tick read(PacketPtr pkt) override;
    Tick write(PacketPtr pkt) override;

  private:
    void executeComputation();
};

}

#endif
