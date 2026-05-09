#include "dev/generic_accel/generic_accel.hh"
#include "debug/GenericAccel.hh"
#include "mem/packet.hh"
#include "mem/packet_access.hh"
#include "sim/system.hh"

namespace gem5 {

GenericAccel::GenericAccel(const GenericAccelParams &p)
    : BasicPioDevice(p, p.pio_size),
      clockMhz(p.clock_mhz),
      peakGops(p.peak_gops),
      staticPower(p.static_power),
      dynamicPower(p.dynamic_power),
      supportsGemm(p.supports_gemm),
      supportsFft(p.supports_fft),
      supportsEigen(p.supports_eigen),
      completionEvent([this]{ completeCommand(); }, name())
{
    // Set capabilities register
    capabilities_reg = 0;
    if (supportsGemm) capabilities_reg |= 0x1;
    if (supportsFft) capabilities_reg |= 0x2;
    if (supportsEigen) capabilities_reg |= 0x4;
}

void GenericAccel::init()
{
    BasicPioDevice::init();
}

Tick GenericAccel::read(PacketPtr pkt)
{
    assert(pkt->getAddr() >= pioAddr && pkt->getAddr() < pioAddr + pioSize);
    
    Addr offset = pkt->getAddr() - pioAddr;
    
    switch (offset) {
        case REG_CONTROL:
            pkt->setLE<uint32_t>(control_reg);
            break;
        case REG_STATUS:
            pkt->setLE<uint32_t>(status_reg);
            break;
        case REG_VERSION:
            pkt->setLE<uint32_t>(version_reg);
            break;
        case REG_CAPABILITIES:
            pkt->setLE<uint32_t>(capabilities_reg);
            break;
        case REG_CMD_DESC_ADDR_LO:
            pkt->setLE<uint32_t>(cmd_desc_addr_lo);
            break;
        case REG_CMD_DESC_ADDR_HI:
            pkt->setLE<uint32_t>(cmd_desc_addr_hi);
            break;
        case REG_CMD_DESC_SIZE:
            pkt->setLE<uint32_t>(cmd_desc_size);
            break;
        case REG_COMP_STATUS:
            pkt->setLE<uint32_t>(comp_status);
            break;
        case REG_COMP_ERROR_CODE:
            pkt->setLE<uint32_t>(comp_error_code);
            break;
        case REG_METRIC_CYCLES:
            pkt->setLE<uint64_t>(metric_cycles);
            break;
        case REG_METRIC_OPS:
            pkt->setLE<uint64_t>(metric_ops);
            break;
        default:
            pkt->setLE<uint32_t>(0);
            break;
    }
    
    pkt->makeResponse();
    return pioDelay;
}

Tick GenericAccel::write(PacketPtr pkt)
{
    assert(pkt->getAddr() >= pioAddr && pkt->getAddr() < pioAddr + pioSize);
    
    Addr offset = pkt->getAddr() - pioAddr;
    uint32_t data = pkt->getLE<uint32_t>();
    
    switch (offset) {
        case REG_CONTROL:
            control_reg = data;
            if (data & 0x1) {
                // Start command
                if (!busy) {
                    processCommand();
                }
            }
            break;
        case REG_CMD_DESC_ADDR_LO:
            cmd_desc_addr_lo = data;
            break;
        case REG_CMD_DESC_ADDR_HI:
            cmd_desc_addr_hi = data;
            break;
        case REG_CMD_DESC_SIZE:
            cmd_desc_size = data;
            break;
        case REG_CMD_DOORBELL:
            if (!busy) {
                processCommand();
            }
            break;
        default:
            break;
    }
    
    pkt->makeResponse();
    return pioDelay;
}

AddrRangeList GenericAccel::getAddrRanges() const
{
    AddrRangeList ranges;
    ranges.push_back(RangeSize(pioAddr, pioSize));
    return ranges;
}

void GenericAccel::processCommand()
{
    busy = true;
    status_reg = 0x1;  // Busy
    
    // Calculate command descriptor address
    uint64_t cmdAddr = ((uint64_t)cmd_desc_addr_hi << 32) | cmd_desc_addr_lo;
    
    DPRINTF(GenericAccel, "Processing command at address 0x%x\n", cmdAddr);
    
    // For now, simulate a simple GEMM operation
    // In full implementation, this would:
    // 1. Read command descriptor from memory
    // 2. Parse simulation request JSON
    // 3. Call SystemC backend or local timing model
    // 4. Write result JSON
    // 5. Update completion status
    
    // Simple timing model: estimate cycles based on FLOPS
    uint64_t flops = 1e9;  // Default 1 GFLOP
    uint64_t cycles = estimateCycles(1, flops);  // 1 = GEMM
    
    metric_cycles += cycles;
    metric_ops += flops;
    
    // Schedule completion
    Tick completionTick = cycles * 1000 / clockMhz;  // Convert to ticks (1ps = 1tick)
    schedule(completionEvent, curTick() + completionTick);
}

void GenericAccel::completeCommand()
{
    busy = false;
    status_reg = 0x0;  // Idle
    comp_status = 0x1;  // Success
    comp_error_code = 0;
    
    DPRINTF(GenericAccel, "Command completed\n");
    
    // Trigger interrupt if enabled
    if (control_reg & 0x2) {
        // Raise interrupt
        // TODO: Implement interrupt handling
    }
}

uint64_t GenericAccel::estimateCycles(uint32_t opType, uint64_t flops)
{
    // Simple timing model
    // cycles = flops / (ops_per_cycle)
    // ops_per_cycle = peak_gops * 1e9 / (clock_mhz * 1e6)
    
    float opsPerCycle = peakGops * 1e9 / (clockMhz * 1e6);
    float efficiency = 0.7;  // 70% efficiency
    
    return (uint64_t)(flops / (opsPerCycle * efficiency));
}

} // namespace gem5
