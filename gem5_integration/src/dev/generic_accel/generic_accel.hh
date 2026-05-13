#pragma once

#include "dev/io_device.hh"
#include "params/GenericAccel.hh"
#include "sim/eventq.hh"

#include <string>
#include <vector>

namespace gem5 {

class GenericAccel : public BasicPioDevice {
public:
    GenericAccel(const GenericAccelParams &p);
    
    void init() override;
    
    Tick read(PacketPtr pkt) override;
    Tick write(PacketPtr pkt) override;
    
    AddrRangeList getAddrRanges() const override;

    struct ScheduledMicroOp {
        std::string kind;
        std::string nodeId;
        std::string device;
        std::string opType;
        uint64_t bytes = 0;
        uint64_t cycles = 0;
        Tick startTick = 0;
        Tick endTick = 0;
        double startNs = 0.0;
        double endNs = 0.0;
    };

private:
    // Register offsets
    static constexpr Addr REG_CONTROL = 0x0000;
    static constexpr Addr REG_STATUS = 0x0004;
    static constexpr Addr REG_VERSION = 0x0008;
    static constexpr Addr REG_CAPABILITIES = 0x000C;
    static constexpr Addr REG_CMD_DOORBELL = 0x1000;
    static constexpr Addr REG_CMD_DESC_ADDR_LO = 0x1004;
    static constexpr Addr REG_CMD_DESC_ADDR_HI = 0x1008;
    static constexpr Addr REG_CMD_DESC_SIZE = 0x100C;
    static constexpr Addr REG_COMP_STATUS = 0x3000;
    static constexpr Addr REG_COMP_DESC_ADDR_LO = 0x3004;
    static constexpr Addr REG_COMP_DESC_ADDR_HI = 0x3008;
    static constexpr Addr REG_COMP_ERROR_CODE = 0x300C;
    static constexpr Addr REG_METRIC_CYCLES = 0x4000;
    static constexpr Addr REG_METRIC_OPS = 0x4004;
    
    // Device state
    uint32_t control_reg = 0;
    uint32_t status_reg = 0;
    uint32_t version_reg = 0x00010000;  // Version 1.0
    uint32_t capabilities_reg = 0;
    
    // Command queue
    uint32_t cmd_desc_addr_lo = 0;
    uint32_t cmd_desc_addr_hi = 0;
    uint32_t cmd_desc_size = 0;
    
    // Completion
    uint32_t comp_status = 0;
    uint32_t comp_desc_addr_lo = 0;
    uint32_t comp_desc_addr_hi = 0;
    uint32_t comp_error_code = 0;
    
    // Metrics
    uint64_t metric_cycles = 0;
    uint64_t metric_ops = 0;
    
    // Configuration
    const float clockMhz;
    const float peakGops;
    const float staticPower;
    const float dynamicPower;
    const bool supportsGemm;
    const bool supportsFft;
    const bool supportsEigen;
    const bool useSystemC;
    const std::string systemcExecutable;
    
    // Simulation state

    bool busy = false;
    uint64_t pendingCycles = 0;
    uint64_t pendingResultAddr = 0;
    uint64_t pendingCompletionAddr = 0;
    std::string pendingResultJson;
    std::string pendingResultPath;
    std::vector<ScheduledMicroOp> pendingMicroOps;
    size_t pendingMicroOpIndex = 0;
    EventFunctionWrapper microOpEvent;
    EventFunctionWrapper completionEvent;
    
    void processCommand();
    void advanceMicroOp();
    void completeCommand();
    uint64_t estimateCycles(uint32_t opType, uint64_t flops);
};

} // namespace gem5
