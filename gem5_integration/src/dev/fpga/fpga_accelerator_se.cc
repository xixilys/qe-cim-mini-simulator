#include "dev/fpga/fpga_accelerator_se.hh"

#include <algorithm>
#include <fstream>
#include <limits>
#include <string>

#include "base/trace.hh"
#include "debug/FPGAAccel.hh"
#include "mem/packet.hh"
#include "mem/packet_access.hh"
#include "sim/cur_tick.hh"

namespace gem5
{

namespace
{

std::string
json_escape(const std::string &value)
{
    std::string escaped;
    escaped.reserve(value.size());
    for (char ch : value) {
        switch (ch) {
          case '\\':
            escaped += "\\\\";
            break;
          case '"':
            escaped += "\\\"";
            break;
          case '\n':
            escaped += "\\n";
            break;
          case '\r':
            escaped += "\\r";
            break;
          case '\t':
            escaped += "\\t";
            break;
          default:
            escaped += ch;
            break;
        }
    }
    return escaped;
}

} // anonymous namespace

FPGAAcceleratorSE::FPGAAcceleratorSE(const Params &p)
    : BasicPioDevice(p, 0x1000),
      controlReg(0),
      statusReg(0),
      nBands(0),
      nBasis(0),
      cycles(0),
      observedReadCount(0),
      observedWriteCount(0),
      pollingReadCount(0),
      commandIssueTick(0),
      deviceAcceptTick(0),
      completionTick(0),
      eventDeltaTicks(0),
      strictEventTiming(p.strict_event_timing),
      candidateProfileRef(p.candidate_profile_ref),
      candidateEventDelayTicks(p.candidate_event_delay_ticks),
      candidateDmaReadBytes(p.candidate_dma_read_bytes),
      candidateDmaWriteBytes(p.candidate_dma_write_bytes),
      strictEventReportPath(p.strict_event_report_path),
      completionEvent([this]{ completeComputation(); }, name())
{
    DPRINTF(FPGAAccel,
            "FPGAAcceleratorSE created at address %#x strict_event_timing=%d "
            "candidate_event_delay_ticks=%llu profile=%s\n",
            pioAddr, strictEventTiming,
            (unsigned long long)candidateEventDelayTicks,
            candidateProfileRef.c_str());
}

Tick
FPGAAcceleratorSE::read(PacketPtr pkt)
{
    Addr offset = pkt->getAddr() - pioAddr;
    uint32_t value = 0;
    observedReadCount++;
    if (offset == REG_STATUS) {
        pollingReadCount++;
    }

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
        case REG_OBSERVED_READ_COUNT:
            value = static_cast<uint32_t>(observedReadCount & 0xFFFFFFFF);
            break;
        case REG_OBSERVED_WRITE_COUNT:
            value = static_cast<uint32_t>(observedWriteCount & 0xFFFFFFFF);
            break;
        case REG_POLLING_READ_COUNT:
            value = static_cast<uint32_t>(pollingReadCount & 0xFFFFFFFF);
            break;
        case REG_COMMAND_ISSUE_TICK_LO:
            value = tickLow(commandIssueTick);
            break;
        case REG_COMMAND_ISSUE_TICK_HI:
            value = tickHigh(commandIssueTick);
            break;
        case REG_DEVICE_ACCEPT_TICK_LO:
            value = tickLow(deviceAcceptTick);
            break;
        case REG_DEVICE_ACCEPT_TICK_HI:
            value = tickHigh(deviceAcceptTick);
            break;
        case REG_COMPLETION_TICK_LO:
            value = tickLow(completionTick);
            break;
        case REG_COMPLETION_TICK_HI:
            value = tickHigh(completionTick);
            break;
        case REG_EVENT_DELTA_TICKS_LO:
            value = tickLow(eventDeltaTicks);
            break;
        case REG_EVENT_DELTA_TICKS_HI:
            value = tickHigh(eventDeltaTicks);
            break;
        default:
            panic("Invalid FPGA register read at offset %#x\n", offset);
    }

    pkt->setLE<uint32_t>(value);
    pkt->makeResponse();

    if (strictEventTiming && completionTick != 0) {
        writeStrictEventReport();
    }

    DPRINTF(FPGAAccel, "Read register offset=%#x value=%#x\n", offset, value);

    return pioDelay;
}

Tick
FPGAAcceleratorSE::write(PacketPtr pkt)
{
    Addr offset = pkt->getAddr() - pioAddr;
    uint32_t value = pkt->getLE<uint32_t>();
    observedWriteCount++;

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
    uint64_t formula_cycles = 3246 + (n * m * m) / 100;

    commandIssueTick = curTick();
    deviceAcceptTick = commandIssueTick;
    completionTick = 0;
    eventDeltaTicks = 0;
    statusReg = 0x0;

    if (completionEvent.scheduled()) {
        deschedule(completionEvent);
    }

    if (strictEventTiming) {
        Tick delay = static_cast<Tick>(std::max<uint64_t>(
            1, candidateEventDelayTicks));
        cycles = static_cast<uint32_t>(std::min<uint64_t>(
            delay, std::numeric_limits<uint32_t>::max()));
        schedule(completionEvent, curTick() + delay);
        DPRINTF(FPGAAccel,
                "Strict event computation scheduled: issue=%llu delay=%llu "
                "profile=%s\n",
                (unsigned long long)commandIssueTick,
                (unsigned long long)delay,
                candidateProfileRef.c_str());
        return;
    }

    cycles = static_cast<uint32_t>(std::min<uint64_t>(
        formula_cycles, std::numeric_limits<uint32_t>::max()));
    completeComputation();
}

void
FPGAAcceleratorSE::completeComputation()
{
    completionTick = curTick();
    if (commandIssueTick == 0) {
        commandIssueTick = completionTick;
        deviceAcceptTick = completionTick;
    }
    eventDeltaTicks = completionTick >= commandIssueTick
        ? completionTick - commandIssueTick
        : 0;
    if (eventDeltaTicks > 0) {
        cycles = static_cast<uint32_t>(std::min<uint64_t>(
            eventDeltaTicks, std::numeric_limits<uint32_t>::max()));
    }

    statusReg = 0x1;
    controlReg &= ~0x1;

    DPRINTF(FPGAAccel,
            "Computation complete: cycles=%d reads=%llu writes=%llu delta=%llu\n",
            cycles,
            (unsigned long long)observedReadCount,
            (unsigned long long)observedWriteCount,
            (unsigned long long)eventDeltaTicks);

    writeStrictEventReport();
}

void
FPGAAcceleratorSE::writeStrictEventReport() const
{
    if (!strictEventTiming || strictEventReportPath.empty()) {
        return;
    }

    std::ofstream out(strictEventReportPath);
    if (!out) {
        DPRINTF(FPGAAccel, "Could not write strict event report: %s\n",
                strictEventReportPath.c_str());
        return;
    }

    out << "{\n";
    out << "  \"schema_version\": \"qebs_gem5_fpga_se_event_report_v0\",\n";
    out << "  \"source\": \"FPGAAcceleratorSE\",\n";
    out << "  \"strict_event_timing\": true,\n";
    out << "  \"event_activity_source\": \"gem5_simobject_counters\",\n";
    out << "  \"mmio_activity_source\": \"gem5_simobject_counters\",\n";
    out << "  \"candidate_profile_ref\": \""
        << json_escape(candidateProfileRef) << "\",\n";
    out << "  \"candidate_event_delay_ticks\": "
        << candidateEventDelayTicks << ",\n";
    out << "  \"observed_read_count\": " << observedReadCount << ",\n";
    out << "  \"observed_write_count\": " << observedWriteCount << ",\n";
    out << "  \"polling_read_count\": " << pollingReadCount << ",\n";
    out << "  \"command_issue_tick\": " << commandIssueTick << ",\n";
    out << "  \"device_accept_tick\": " << deviceAcceptTick << ",\n";
    out << "  \"systemc_start_tick\": " << deviceAcceptTick << ",\n";
    out << "  \"systemc_end_tick\": " << completionTick << ",\n";
    out << "  \"completion_tick\": " << completionTick << ",\n";
    out << "  \"candidate_device_event_delta_ticks\": "
        << eventDeltaTicks << ",\n";
    out << "  \"candidate_dma_read_bytes\": "
        << candidateDmaReadBytes << ",\n";
    out << "  \"candidate_dma_write_bytes\": "
        << candidateDmaWriteBytes << ",\n";
    out << "  \"completion_source\": "
        << "\"FPGAAcceleratorSE_strict_event_scheduled_completion\"\n";
    out << "}\n";
}

uint32_t
FPGAAcceleratorSE::tickLow(Tick value) const
{
    return static_cast<uint32_t>(value & 0xFFFFFFFF);
}

uint32_t
FPGAAcceleratorSE::tickHigh(Tick value) const
{
    return static_cast<uint32_t>((value >> 32) & 0xFFFFFFFF);
}

}
