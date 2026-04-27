#include "dev/fpga/fpga_accelerator_se.hh"

#include "base/trace.hh"
#include "debug/FPGAAccel.hh"
#include "mem/packet.hh"
#include "mem/packet_access.hh"

namespace gem5
{

FPGAAcceleratorSE::FPGAAcceleratorSE(const Params &p)
    : BasicPioDevice(p, 0x1000),
      controlReg(0),
      statusReg(0),
      nBands(0),
      nBasis(0),
      cycles(0)
{
    DPRINTF(FPGAAccel, "FPGAAcceleratorSE created at address %#x\n", pioAddr);
}

Tick
FPGAAcceleratorSE::read(PacketPtr pkt)
{
    Addr offset = pkt->getAddr() - pioAddr;
    uint32_t value = 0;

    switch (offset) {
        case REG_CONTROL:
            value = controlReg;
            break;
        case REG_STATUS:
            value = statusReg;
            break;
        case REG_N_BANDS:
            value = nBands;
            break;
        case REG_N_BASIS:
            value = nBasis;
            break;
        case REG_CYCLES:
            value = cycles;
            break;
        default:
            panic("Invalid FPGA register read at offset %#x\n", offset);
    }

    pkt->setLE<uint32_t>(value);
    pkt->makeResponse();

    DPRINTF(FPGAAccel, "Read register offset=%#x value=%#x\n", offset, value);

    return pioDelay;
}

Tick
FPGAAcceleratorSE::write(PacketPtr pkt)
{
    Addr offset = pkt->getAddr() - pioAddr;
    uint32_t value = pkt->getLE<uint32_t>();

    DPRINTF(FPGAAccel, "Write register offset=%#x value=%#x\n", offset, value);

    switch (offset) {
        case REG_CONTROL:
            controlReg = value;
            if (value & 0x1) {
                executeComputation();
            }
            break;
        case REG_N_BANDS:
            nBands = value;
            break;
        case REG_N_BASIS:
            nBasis = value;
            break;
        default:
            panic("Invalid FPGA register write at offset %#x\n", offset);
    }

    pkt->makeResponse();
    return pioDelay;
}

void
FPGAAcceleratorSE::executeComputation()
{
    DPRINTF(FPGAAccel, "Starting computation: nBands=%d nBasis=%d\n",
            nBands, nBasis);

    uint64_t n = nBands;
    uint64_t m = nBasis;
    
    cycles = 3246 + (n * m * m) / 100;

    statusReg = 0x1;
    controlReg &= ~0x1;

    DPRINTF(FPGAAccel, "Computation complete: cycles=%d\n", cycles);
}

}
