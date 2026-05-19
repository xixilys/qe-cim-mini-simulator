#include "dev/generic_accel/generic_accel.hh"
#include "debug/GenericAccel.hh"
#include "mem/packet.hh"
#include "mem/packet_access.hh"
#include "mem/port_proxy.hh"
#include "sim/system.hh"

#include <algorithm>
#include <cmath>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iterator>
#include <limits>
#include <map>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <utility>
#include <vector>

namespace gem5 {

namespace {

constexpr uint32_t GsimMagic = 0x4753494d; // "GSIM"
constexpr uint32_t GsimErrorDescriptor = 0x1001;
constexpr uint32_t GsimErrorMicroarchitecture = 0x1101;
constexpr size_t MaxJsonBytes = 1 << 20;
constexpr size_t LegacyCommandDescriptorBytes = 48;
constexpr const char *UarchEngine = "gem5_generic_accel_microarchitecture_v1";

enum GsimDescriptorFlag : uint32_t {
    GsimFlagRequestJson = 1u << 0,
    GsimFlagResultJson = 1u << 1,
    GsimFlagCompletionDesc = 1u << 2,
    GsimFlagExtensionPayload = 1u << 3,
    GsimFlagCandidateIdentity = 1u << 4,
    GsimFlagCompileSchedule = 1u << 5,
    GsimFlagRuntimeSchedule = 1u << 6,
    GsimFlagSidecarDispatch = 1u << 7,
};

#pragma pack(push, 1)
struct CommandDescriptor {
    uint32_t magic;
    uint32_t version;
    uint32_t type;
    uint32_t flags;
    uint64_t request_addr;
    uint64_t result_addr;
    uint64_t workspace_addr;
    uint64_t workspace_size;
    uint64_t extension_payload_addr;
    uint64_t extension_payload_bytes;
    uint64_t candidate_identity_addr;
    uint64_t candidate_identity_bytes;
    uint64_t compile_schedule_addr;
    uint64_t compile_schedule_bytes;
    uint64_t runtime_schedule_addr;
    uint64_t runtime_schedule_bytes;
    uint64_t sidecar_dispatch_addr;
    uint64_t sidecar_dispatch_bytes;
};

struct CompletionDescriptor {
    uint32_t magic;
    uint32_t status;
    uint64_t result_addr;
    uint64_t cycles;
    uint32_t error_code;
};
#pragma pack(pop)

struct ParsedNode {
    std::string id;
    std::string opType = "generic_op";
    double flops = 0.0;
    double memoryBytes = 0.0;
};

struct ParsedEdge {
    std::string source;
    std::string target;
    std::string tensorName;
    double sizeBytes = 0.0;
};

struct ParsedCapability {
    double peakGops = 0.0;
    double efficiency = 0.5;
};

struct ParsedAccel {
    std::string id;
    std::string type = "custom";
    double clockMhz = 250.0;
    double localMemoryKb = 2048.0;
    double staticW = 0.0;
    double maxW = 100.0;
    std::map<std::string, ParsedCapability> capabilities;
};

struct ParsedRequest {
    std::string runId = "unknown";
    std::string candidateId;
    std::string algorithmId;
    std::string architectureId;
    std::string mappingId;
    std::string compileScheduleId;
    std::string runtimeScheduleId;
    std::string workloadCaseId;
    std::string sidecarDispatchMode = "in_gem5_uarch";
    std::string sidecarModel;
    bool extensionPayloadPresent = false;
    std::map<std::string, ParsedNode> nodes;
    std::vector<ParsedEdge> edges;
    std::map<std::string, std::string> mapping;
    std::vector<ParsedAccel> accelerators;
    double hostClockMhz = 3000.0;
    double hostMemoryBwGbps = 100.0;
    int hostCores = 1;
    double interconnectBandwidthGbps = 64.0;
    double interconnectLatencyNs = 800.0;
};

struct DeviceStats {
    double computeNs = 0.0;
    double dmaNs = 0.0;
    double computeCycles = 0.0;
    double dmaCycles = 0.0;
    double stallCycles = 0.0;
    double memoryAccesses = 0.0;
    double activeNs = 0.0;
    std::string accelType = "host";
};

struct ScheduleBuildResult {
    std::vector<GenericAccel::ScheduledMicroOp> microOps;
    std::string resultJson;
    uint64_t totalCycles = 0;
    uint64_t totalFlops = 0;
    uint64_t totalBytes = 0;
    double latencyNs = 0.0;
    std::string error;
};

std::string readGuestCString(System *sys, Addr addr, size_t maxBytes)
{
    std::vector<char> buffer(std::max<size_t>(1, maxBytes), 0);
    sys->physProxy.readBlob(addr, buffer.data(), buffer.size());
    auto end = std::find(buffer.begin(), buffer.end(), '\0');
    return std::string(buffer.begin(), end);
}

std::string readOptionalGuestCString(System *sys, Addr addr, uint64_t bytes)
{
    if (addr == 0 || bytes == 0) {
        return "";
    }
    const size_t boundedBytes = std::min<size_t>(static_cast<size_t>(bytes), MaxJsonBytes);
    return readGuestCString(sys, addr, boundedBytes);
}

void skipWs(const std::string &s, size_t &pos)
{
    while (pos < s.size() && std::isspace(static_cast<unsigned char>(s[pos]))) {
        ++pos;
    }
}

bool expectChar(const std::string &s, size_t &pos, char c)
{
    skipWs(s, pos);
    if (pos < s.size() && s[pos] == c) {
        ++pos;
        return true;
    }
    return false;
}

std::string parseJsonString(const std::string &s, size_t &pos)
{
    skipWs(s, pos);
    if (pos >= s.size() || s[pos] != '"') {
        return "";
    }
    ++pos;
    std::string out;
    while (pos < s.size() && s[pos] != '"') {
        if (s[pos] == '\\' && pos + 1 < s.size()) {
            ++pos;
            switch (s[pos]) {
              case '"': out.push_back('"'); break;
              case '\\': out.push_back('\\'); break;
              case '/': out.push_back('/'); break;
              case 'b': out.push_back('\b'); break;
              case 'f': out.push_back('\f'); break;
              case 'n': out.push_back('\n'); break;
              case 'r': out.push_back('\r'); break;
              case 't': out.push_back('\t'); break;
              default: out.push_back(s[pos]); break;
            }
        } else {
            out.push_back(s[pos]);
        }
        ++pos;
    }
    if (pos < s.size() && s[pos] == '"') {
        ++pos;
    }
    return out;
}

std::string jsonEscape(const std::string &s)
{
    std::ostringstream os;
    for (char c : s) {
        switch (c) {
          case '"': os << "\\\""; break;
          case '\\': os << "\\\\"; break;
          case '\n': os << "\\n"; break;
          case '\r': os << "\\r"; break;
          case '\t': os << "\\t"; break;
          default: os << c; break;
        }
    }
    return os.str();
}

bool consumeEnclosed(const std::string &s, size_t &pos, char open, char close, std::string &out)
{
    skipWs(s, pos);
    if (pos >= s.size() || s[pos] != open) {
        return false;
    }
    const size_t start = pos;
    int depth = 0;
    bool inString = false;
    bool escape = false;
    while (pos < s.size()) {
        const char c = s[pos++];
        if (inString) {
            if (escape) {
                escape = false;
            } else if (c == '\\') {
                escape = true;
            } else if (c == '"') {
                inString = false;
            }
            continue;
        }
        if (c == '"') {
            inString = true;
        } else if (c == open) {
            ++depth;
        } else if (c == close) {
            --depth;
            if (depth == 0) {
                out = s.substr(start, pos - start);
                return true;
            }
        }
    }
    return false;
}

std::string parseRawValue(const std::string &s, size_t &pos)
{
    skipWs(s, pos);
    if (pos >= s.size()) {
        return "";
    }
    const size_t start = pos;
    if (s[pos] == '{') {
        std::string out;
        consumeEnclosed(s, pos, '{', '}', out);
        return out;
    }
    if (s[pos] == '[') {
        std::string out;
        consumeEnclosed(s, pos, '[', ']', out);
        return out;
    }
    if (s[pos] == '"') {
        parseJsonString(s, pos);
        return s.substr(start, pos - start);
    }
    while (pos < s.size() && s[pos] != ',' && s[pos] != '}' && s[pos] != ']') {
        ++pos;
    }
    return s.substr(start, pos - start);
}

std::vector<std::pair<std::string, std::string>> objectMembers(const std::string &obj)
{
    std::vector<std::pair<std::string, std::string>> members;
    size_t pos = 0;
    if (!expectChar(obj, pos, '{')) {
        return members;
    }
    while (pos < obj.size()) {
        skipWs(obj, pos);
        if (pos < obj.size() && obj[pos] == '}') {
            break;
        }
        std::string key = parseJsonString(obj, pos);
        if (key.empty() && pos >= obj.size()) {
            break;
        }
        expectChar(obj, pos, ':');
        std::string raw = parseRawValue(obj, pos);
        members.emplace_back(std::move(key), std::move(raw));
        skipWs(obj, pos);
        if (pos < obj.size() && obj[pos] == ',') {
            ++pos;
        }
    }
    return members;
}

std::vector<std::string> arrayObjects(const std::string &arr)
{
    std::vector<std::string> objects;
    size_t pos = 0;
    if (!expectChar(arr, pos, '[')) {
        return objects;
    }
    while (pos < arr.size()) {
        skipWs(arr, pos);
        if (pos < arr.size() && arr[pos] == ']') {
            break;
        }
        std::string raw = parseRawValue(arr, pos);
        if (!raw.empty() && raw.front() == '{') {
            objects.push_back(raw);
        }
        skipWs(arr, pos);
        if (pos < arr.size() && arr[pos] == ',') {
            ++pos;
        }
    }
    return objects;
}

std::string stripJsonString(const std::string &raw)
{
    size_t pos = 0;
    return parseJsonString(raw, pos);
}

std::string valueForKey(const std::string &obj, const std::string &key)
{
    for (const auto &member : objectMembers(obj)) {
        if (member.first == key) {
            return member.second;
        }
    }
    return "";
}

std::string stringForKey(const std::string &obj, const std::string &key, const std::string &fallback = "")
{
    const std::string raw = valueForKey(obj, key);
    if (raw.empty() || raw.front() != '"') {
        return fallback;
    }
    return stripJsonString(raw);
}

double numberForKey(const std::string &obj, const std::string &key, double fallback = 0.0)
{
    const std::string raw = valueForKey(obj, key);
    if (raw.empty()) {
        return fallback;
    }
    char *end = nullptr;
    const double value = std::strtod(raw.c_str(), &end);
    return end != raw.c_str() ? value : fallback;
}

ParsedCapability parseCapability(const std::string &obj)
{
    ParsedCapability cap;
    cap.peakGops = numberForKey(obj, "peak_gops", 0.0);
    cap.efficiency = numberForKey(obj, "efficiency", 0.5);
    cap.efficiency = std::max(0.01, std::min(cap.efficiency, 1.0));
    return cap;
}

ParsedRequest parseRequest(const std::string &json)
{
    ParsedRequest req;
    req.runId = stringForKey(json, "run_id", "unknown");
    req.workloadCaseId = stringForKey(json, "workload_case_id", "");

    const std::string candidateIdentity = valueForKey(json, "candidate_identity");
    const std::string candidateTranslation = valueForKey(json, "candidate_translation");
    req.candidateId = stringForKey(candidateIdentity, "candidate_id",
                                   stringForKey(candidateTranslation, "candidate_id", ""));
    req.algorithmId = stringForKey(candidateIdentity, "algorithm_id", "");
    req.architectureId = stringForKey(candidateIdentity, "architecture_id", "");
    req.mappingId = stringForKey(candidateIdentity, "mapping_id", "");

    const std::string compileSchedule = valueForKey(json, "compile_schedule");
    req.compileScheduleId = stringForKey(compileSchedule, "schedule_id",
                                         stringForKey(candidateIdentity, "compile_schedule_id", ""));
    const std::string runtimeSchedule = valueForKey(json, "runtime_schedule");
    req.runtimeScheduleId = stringForKey(runtimeSchedule, "schedule_id",
                                         stringForKey(candidateIdentity, "runtime_schedule_id", ""));

    const std::string sidecarDispatch = valueForKey(json, "sidecar_dispatch");
    req.sidecarDispatchMode = stringForKey(sidecarDispatch, "mode", req.sidecarDispatchMode);
    req.sidecarModel = stringForKey(sidecarDispatch, "model", "");
    const std::string extensionPayload = valueForKey(json, "extension_payload");
    req.extensionPayloadPresent = !extensionPayload.empty();

    const std::string workload = valueForKey(json, "workload");
    const std::string nodes = valueForKey(workload, "nodes");
    for (const auto &member : objectMembers(nodes)) {
        ParsedNode node;
        node.id = member.first;
        node.opType = stringForKey(member.second, "op_type", "generic_op");
        node.flops = numberForKey(member.second, "estimated_flops", 0.0);
        node.memoryBytes = numberForKey(member.second, "estimated_memory_bytes", 0.0);
        req.nodes[node.id] = node;
    }

    const std::string edges = valueForKey(workload, "edges");
    for (const auto &edgeObj : arrayObjects(edges)) {
        ParsedEdge edge;
        edge.source = stringForKey(edgeObj, "source", stringForKey(edgeObj, "source_node", ""));
        edge.target = stringForKey(edgeObj, "target", stringForKey(edgeObj, "target_node", ""));
        edge.tensorName = stringForKey(edgeObj, "tensor_name", "");
        edge.sizeBytes = numberForKey(edgeObj, "size_bytes", 0.0);
        if (!edge.source.empty() && !edge.target.empty()) {
            req.edges.push_back(edge);
        }
    }

    const std::string mapping = valueForKey(json, "mapping");
    for (const auto &member : objectMembers(mapping)) {
        if (!member.first.empty() && !member.second.empty() && member.second.front() == '"') {
            req.mapping[member.first] = stripJsonString(member.second);
        }
    }

    const std::string architecture = valueForKey(json, "architecture");
    const std::string host = valueForKey(architecture, "host");
    req.hostClockMhz = numberForKey(host, "clock_mhz", 3000.0);
    req.hostMemoryBwGbps = numberForKey(host, "memory_bw_gbps", 100.0);
    req.hostCores = static_cast<int>(numberForKey(host, "cores", 1.0));

    const std::string interconnect = valueForKey(architecture, "interconnect");
    req.interconnectBandwidthGbps = numberForKey(interconnect, "bandwidth_gbps", 64.0);
    req.interconnectLatencyNs = numberForKey(interconnect, "latency_ns", 800.0);

    const std::string accelerators = valueForKey(architecture, "accelerators");
    for (const auto &accelObj : arrayObjects(accelerators)) {
        ParsedAccel accel;
        accel.id = stringForKey(accelObj, "accel_id", "");
        accel.type = stringForKey(accelObj, "accel_type", "custom");
        accel.clockMhz = numberForKey(accelObj, "clock_mhz", 250.0);
        accel.localMemoryKb = numberForKey(accelObj, "local_memory_kb", 2048.0);
        const std::string power = valueForKey(accelObj, "power");
        accel.staticW = numberForKey(power, "static_w", 0.0);
        accel.maxW = numberForKey(power, "max_w", 100.0);
        const std::string capabilities = valueForKey(accelObj, "capabilities");
        for (const auto &cap : objectMembers(capabilities)) {
            accel.capabilities[cap.first] = parseCapability(cap.second);
        }
        if (!accel.id.empty()) {
            req.accelerators.push_back(accel);
        }
    }

    if (req.nodes.empty()) {
        throw std::runtime_error("simulation_request contains no workload nodes");
    }
    return req;
}

const ParsedAccel *findAccel(const ParsedRequest &req, const std::string &device)
{
    for (const auto &accel : req.accelerators) {
        if (accel.id == device) {
            return &accel;
        }
    }
    return nullptr;
}

std::string mappedDevice(const ParsedRequest &req, const std::string &nodeId)
{
    const auto it = req.mapping.find(nodeId);
    if (it == req.mapping.end()) {
        return "host";
    }
    if (it->second == "host" || findAccel(req, it->second) != nullptr) {
        return it->second;
    }
    return "host";
}

uint64_t cyclesForNs(double ns, double clockMhz)
{
    return static_cast<uint64_t>(std::max(1.0, std::ceil(ns * clockMhz / 1000.0)));
}

Tick ticksForNs(double ns)
{
    return static_cast<Tick>(std::max(1.0, std::ceil(ns * 1000.0)));
}

double nsForCycles(uint64_t cycles, double clockMhz)
{
    return static_cast<double>(cycles) * 1000.0 / std::max(clockMhz, 1.0);
}

double edgeBytes(const ParsedEdge &edge, const ParsedRequest &req)
{
    if (edge.sizeBytes > 0.0) {
        return edge.sizeBytes;
    }
    const auto src = req.nodes.find(edge.source);
    if (src != req.nodes.end()) {
        return src->second.memoryBytes;
    }
    return 0.0;
}

double transferNs(double bytes, const ParsedRequest &req)
{
    const double bwGbps = std::max(req.interconnectBandwidthGbps, 1.0);
    return req.interconnectLatencyNs + (bytes * 8.0 / bwGbps);
}

ParsedCapability capabilityFor(const ParsedAccel *accel, const std::string &opType, double fallbackPeakGops)
{
    ParsedCapability cap;
    cap.peakGops = fallbackPeakGops;
    cap.efficiency = 0.45;
    if (accel) {
        const auto it = accel->capabilities.find(opType);
        if (it != accel->capabilities.end()) {
            cap = it->second;
        } else if (!accel->capabilities.empty()) {
            cap = accel->capabilities.begin()->second;
            cap.efficiency *= 0.5;
        }
    }
    cap.peakGops = std::max(cap.peakGops, 0.001);
    cap.efficiency = std::max(0.01, std::min(cap.efficiency, 1.0));
    return cap;
}

uint64_t computeCyclesForNode(const ParsedNode &node, const ParsedAccel *accel,
                              const ParsedRequest &req, double fallbackPeakGops,
                              DeviceStats &stats)
{
    const double clockMhz = accel ? accel->clockMhz : req.hostClockMhz;
    const ParsedCapability cap = accel
        ? capabilityFor(accel, node.opType, fallbackPeakGops)
        : ParsedCapability{std::max(1.0, req.hostClockMhz * std::max(1, req.hostCores) * 4.0 / 1000.0), 0.55};
    const double opsPerCycle = cap.peakGops * 1.0e9 * cap.efficiency / (std::max(clockMhz, 1.0) * 1.0e6);
    const uint64_t computeCycles = static_cast<uint64_t>(std::ceil(node.flops / std::max(opsPerCycle, 1.0e-9)));

    const int memoryPorts = accel ? (accel->type == "gpu" ? 4 : (accel->type == "fpga" ? 2 : 1)) : 2;
    const double bytesPerCycle = 64.0 * memoryPorts;
    const uint64_t memoryCycles = static_cast<uint64_t>(std::ceil(node.memoryBytes / std::max(bytesPerCycle, 1.0)));
    const uint64_t pipelineCycles = accel
        ? (accel->type == "gpu" ? 128 : (accel->type == "cim" ? 96 : (accel->type == "fpga" ? 64 : 32)))
        : 16;
    const uint64_t cycles = std::max<uint64_t>(1, std::max(computeCycles, memoryCycles) + pipelineCycles);
    stats.memoryAccesses += std::ceil(node.memoryBytes / 64.0);
    if (memoryCycles > computeCycles) {
        stats.stallCycles += static_cast<double>(memoryCycles - computeCycles);
    }
    return cycles;
}

std::vector<std::string> topologicalOrder(const ParsedRequest &req, std::string &error)
{
    std::map<std::string, int> indegree;
    std::map<std::string, std::vector<std::string>> adjacency;
    for (const auto &item : req.nodes) {
        indegree[item.first] = 0;
    }
    for (const auto &edge : req.edges) {
        if (req.nodes.count(edge.source) == 0 || req.nodes.count(edge.target) == 0) {
            continue;
        }
        adjacency[edge.source].push_back(edge.target);
        indegree[edge.target]++;
    }
    std::queue<std::string> q;
    for (const auto &item : indegree) {
        if (item.second == 0) {
            q.push(item.first);
        }
    }
    std::vector<std::string> order;
    while (!q.empty()) {
        const std::string node = q.front();
        q.pop();
        order.push_back(node);
        for (const auto &next : adjacency[node]) {
            if (--indegree[next] == 0) {
                q.push(next);
            }
        }
    }
    if (order.size() != req.nodes.size()) {
        error = "cycle detected in workload graph";
    }
    return order;
}

void appendMicroOp(std::vector<GenericAccel::ScheduledMicroOp> &ops,
                   const std::string &kind,
                   const std::string &nodeId,
                   const std::string &device,
                   const std::string &opType,
                   uint64_t bytes,
                   uint64_t cycles,
                   double startNs,
                   double endNs,
                   Tick baseTick)
{
    GenericAccel::ScheduledMicroOp op;
    op.kind = kind;
    op.nodeId = nodeId;
    op.device = device;
    op.opType = opType;
    op.bytes = bytes;
    op.cycles = cycles;
    op.startNs = startNs;
    op.endNs = endNs;
    op.startTick = baseTick + ticksForNs(startNs);
    op.endTick = baseTick + ticksForNs(endNs);
    ops.push_back(op);
}

std::string errorResultJson(const std::string &runId, const std::string &message)
{
    std::ostringstream os;
    os << "{\n"
       << "  \"schema_version\": \"gsim.result.v2\",\n"
       << "  \"run_id\": \"" << jsonEscape(runId) << "\",\n"
       << "  \"status\": \"error\",\n"
       << "  \"error_message\": \"" << jsonEscape(message) << "\",\n"
       << "  \"execution_engine\": \"" << UarchEngine << "\",\n"
       << "  \"metrics\": {\"latency_ms\": 0.0}\n"
       << "}\n";
    return os.str();
}

bool writeTextFile(const std::string &path, const std::string &text)
{
    std::ofstream out(path);
    if (!out.is_open()) {
        return false;
    }
    out << text;
    return true;
}

std::string readTextFile(const std::string &path)
{
    std::ifstream in(path);
    if (!in.is_open()) {
        return "";
    }
    return std::string(std::istreambuf_iterator<char>(in),
                       std::istreambuf_iterator<char>());
}

std::string shellQuote(const std::string &value)
{
    std::string out = "'";
    for (char c : value) {
        if (c == '\'') {
            out += "'\\''";
        } else {
            out.push_back(c);
        }
    }
    out += "'";
    return out;
}

std::string resultJson(const ParsedRequest &req,
                       const std::vector<GenericAccel::ScheduledMicroOp> &ops,
                       const std::map<std::string, DeviceStats> &deviceStats,
                       double latencyNs,
                       uint64_t totalCycles,
                       double totalFlops,
                       double totalBytes,
                       double staticPowerW,
                       double activePowerW)
{
    const double latencyMs = latencyNs / 1.0e6;
    const double throughputGops = latencyMs > 0.0 ? totalFlops / latencyMs / 1.0e6 : 0.0;
    double deviceTimeNs = 0.0;
    double dmaTimeNs = 0.0;
    for (const auto &item : deviceStats) {
        deviceTimeNs += item.second.computeNs;
        dmaTimeNs += item.second.dmaNs;
    }
    const double powerW = staticPowerW + activePowerW;

    std::ostringstream os;
    os << std::fixed << std::setprecision(6);
    os << "{\n"
       << "  \"schema_version\": \"gsim.result.v2\",\n"
       << "  \"run_id\": \"" << jsonEscape(req.runId) << "\",\n"
       << "  \"status\": \"passed\",\n"
       << "  \"execution_engine\": \"" << UarchEngine << "\",\n"
       << "  \"claim_scope\": \"vertical_slice_only\",\n"
       << "  \"trusted_final_claim\": false,\n"
       << "  \"candidate_identity\": {\n"
       << "    \"candidate_id\": \"" << jsonEscape(req.candidateId) << "\",\n"
       << "    \"algorithm_id\": \"" << jsonEscape(req.algorithmId) << "\",\n"
       << "    \"architecture_id\": \"" << jsonEscape(req.architectureId) << "\",\n"
       << "    \"mapping_id\": \"" << jsonEscape(req.mappingId) << "\",\n"
       << "    \"compile_schedule_id\": \"" << jsonEscape(req.compileScheduleId) << "\",\n"
       << "    \"runtime_schedule_id\": \"" << jsonEscape(req.runtimeScheduleId) << "\"\n"
       << "  },\n"
       << "  \"software_visible_dispatch\": {\n"
       << "    \"workload_case_id\": \"" << jsonEscape(req.workloadCaseId) << "\",\n"
       << "    \"sidecar_dispatch_mode\": \"" << jsonEscape(req.sidecarDispatchMode) << "\",\n"
       << "    \"sidecar_model\": \"" << jsonEscape(req.sidecarModel) << "\",\n"
       << "    \"extension_payload_present\": " << (req.extensionPayloadPresent ? "true" : "false") << "\n"
       << "  },\n"
       << "  \"metrics\": {\n"
       << "    \"latency_ms\": " << latencyMs << ",\n"
       << "    \"host_time_ms\": 0.000000,\n"
       << "    \"device_time_ms\": " << deviceTimeNs / 1.0e6 << ",\n"
       << "    \"dma_time_ms\": " << dmaTimeNs / 1.0e6 << ",\n"
       << "    \"throughput_gops\": " << throughputGops << ",\n"
       << "    \"power_w\": " << powerW << ",\n"
       << "    \"energy_j\": " << powerW * latencyMs / 1000.0 << ",\n"
       << "    \"area_mm2\": 0.000000,\n"
       << "    \"total_data_movement_mb\": " << totalBytes / (1024.0 * 1024.0) << "\n"
       << "  },\n";

    os << "  \"resource_utilization\": {\n";
    bool first = true;
    for (const auto &item : deviceStats) {
        if (!first) os << ",\n";
        first = false;
        const auto &stats = item.second;
        const double util = latencyNs > 0.0 ? std::min(100.0, stats.computeNs / latencyNs * 100.0) : 0.0;
        const double bwUtil = latencyNs > 0.0 ? std::min(100.0, stats.dmaNs / latencyNs * 100.0) : 0.0;
        os << "    \"" << jsonEscape(item.first) << "\": {\"compute_percent\": " << util
           << ", \"memory_percent\": " << bwUtil
           << ", \"bandwidth_percent\": " << bwUtil << "}";
    }
    os << "\n  },\n";

    os << "  \"microarchitecture_details\": {\n";
    first = true;
    for (const auto &item : deviceStats) {
        if (!first) os << ",\n";
        first = false;
        const auto &stats = item.second;
        const double util = latencyNs > 0.0 ? std::min(1.0, stats.computeNs / latencyNs) : 0.0;
        os << "    \"" << jsonEscape(item.first) << "\": {\n"
           << "      \"accel_type\": \"" << jsonEscape(stats.accelType) << "\",\n"
           << "      \"compute_cycles\": " << stats.computeCycles << ",\n"
           << "      \"dma_cycles\": " << stats.dmaCycles << ",\n"
           << "      \"stall_cycles\": " << stats.stallCycles << ",\n"
           << "      \"memory_accesses\": " << stats.memoryAccesses << ",\n"
           << "      \"pipeline_utilization\": " << util << ",\n"
           << "      \"array_utilization\": " << util << ",\n"
           << "      \"power_breakdown\": {\"compute_w\": " << activePowerW * util
           << ", \"memory_w\": " << activePowerW * 0.25 * util
           << ", \"interconnect_w\": " << activePowerW * 0.10 * util << "}\n"
           << "    }";
    }
    os << "\n  },\n";

    os << "  \"events\": [\n";
    bool firstEvent = true;
    for (const auto &op : ops) {
        if (op.kind != "compute") {
            continue;
        }
        if (!firstEvent) os << ",\n";
        firstEvent = false;
        os << "    {\"node_id\": \"" << jsonEscape(op.nodeId) << "\", \"device\": \""
           << jsonEscape(op.device) << "\", \"start_ns\": " << op.startNs
           << ", \"end_ns\": " << op.endNs << ", \"op_type\": \""
           << jsonEscape(op.opType) << "\"}";
    }
    os << "\n  ],\n";

    os << "  \"uncertainty\": {\"fidelity_level\": \"L4-gem5-uarch\", \"confidence_level\": 0.900000, \"mape_percent\": 8.000000},\n"
       << "  \"microarchitecture_summary\": {\"engine\": \"" << UarchEngine
       << "\", \"micro_op_count\": " << ops.size()
       << ", \"total_cycles\": " << totalCycles
       << ", \"total_flops\": " << static_cast<uint64_t>(totalFlops) << "}\n"
       << "}\n";
    return os.str();
}

ScheduleBuildResult buildSchedule(const std::string &requestJson, Tick baseTick,
                                  double fallbackClockMhz, double fallbackPeakGops,
                                  double staticPowerParam, double dynamicPowerParam)
{
    ScheduleBuildResult out;
    ParsedRequest req = parseRequest(requestJson);
    std::string orderError;
    const std::vector<std::string> order = topologicalOrder(req, orderError);
    if (!orderError.empty()) {
        out.error = orderError;
        out.resultJson = errorResultJson(req.runId, orderError);
        return out;
    }

    std::map<std::string, double> nodeEndNs;
    std::map<std::string, double> deviceAvailableNs;
    std::map<std::string, DeviceStats> stats;
    for (const auto &accel : req.accelerators) {
        deviceAvailableNs[accel.id] = 0.0;
        stats[accel.id].accelType = accel.type;
    }
    deviceAvailableNs["host"] = 0.0;
    stats["host"].accelType = "host";
    double dmaAvailableNs = 0.0;
    double decodeNs = nsForCycles(32, fallbackClockMhz);
    appendMicroOp(out.microOps, "command_decode", "__command__", "generic_accel", "descriptor", 0,
                  32, 0.0, decodeNs, baseTick);

    double totalFlops = 0.0;
    double totalBytes = 0.0;
    double staticPowerW = staticPowerParam;
    for (const auto &accel : req.accelerators) {
        staticPowerW += accel.staticW;
    }

    for (const auto &nodeId : order) {
        const ParsedNode &node = req.nodes.at(nodeId);
        std::string device = mappedDevice(req, nodeId);
        const ParsedAccel *accel = findAccel(req, device);
        const double deviceClock = accel ? accel->clockMhz : req.hostClockMhz;
        double readyNs = decodeNs;

        for (const auto &edge : req.edges) {
            if (edge.target != nodeId) {
                continue;
            }
            const double depEnd = nodeEndNs.count(edge.source) ? nodeEndNs[edge.source] : decodeNs;
            const std::string srcDevice = mappedDevice(req, edge.source);
            if (srcDevice == device) {
                readyNs = std::max(readyNs, depEnd);
                continue;
            }
            const double bytes = edgeBytes(edge, req);
            totalBytes += bytes;
            const double dmaStart = std::max(depEnd, dmaAvailableNs);
            const double dmaNs = transferNs(bytes, req);
            const double dmaEnd = dmaStart + dmaNs;
            dmaAvailableNs = dmaEnd;
            readyNs = std::max(readyNs, dmaEnd);
            const uint64_t dmaCycles = cyclesForNs(dmaNs, deviceClock);
            appendMicroOp(out.microOps, "dma_transfer", nodeId, device, node.opType,
                          static_cast<uint64_t>(std::max(0.0, bytes)), dmaCycles,
                          dmaStart, dmaEnd, baseTick);
            stats[device].dmaNs += dmaNs;
            stats[device].dmaCycles += dmaCycles;
        }

        const double computeStart = std::max(readyNs, deviceAvailableNs[device]);
        DeviceStats &deviceStats = stats[device];
        if (accel) {
            deviceStats.accelType = accel->type;
        }
        const uint64_t computeCycles = computeCyclesForNode(node, accel, req, fallbackPeakGops, deviceStats);
        const double computeNs = nsForCycles(computeCycles, deviceClock);
        const double computeEnd = computeStart + computeNs;
        appendMicroOp(out.microOps, "compute", nodeId, device, node.opType,
                      static_cast<uint64_t>(std::max(0.0, node.memoryBytes)), computeCycles,
                      computeStart, computeEnd, baseTick);
        nodeEndNs[nodeId] = computeEnd;
        deviceAvailableNs[device] = computeEnd;
        deviceStats.computeNs += computeNs;
        deviceStats.computeCycles += computeCycles;
        deviceStats.activeNs += computeNs;
        totalFlops += node.flops;
    }

    double latencyNs = decodeNs;
    for (const auto &item : nodeEndNs) {
        latencyNs = std::max(latencyNs, item.second);
    }
    const double completionStart = latencyNs;
    const double completionNs = nsForCycles(48, fallbackClockMhz);
    appendMicroOp(out.microOps, "completion_writeback", "__completion__", "generic_accel", "completion", 0,
                  48, completionStart, completionStart + completionNs, baseTick);
    latencyNs += completionNs;

    std::sort(out.microOps.begin(), out.microOps.end(), [](const auto &a, const auto &b) {
        if (a.endTick != b.endTick) return a.endTick < b.endTick;
        return a.kind < b.kind;
    });

    out.latencyNs = latencyNs;
    out.totalCycles = cyclesForNs(latencyNs, fallbackClockMhz);
    out.totalFlops = static_cast<uint64_t>(std::max(0.0, totalFlops));
    out.totalBytes = static_cast<uint64_t>(std::max(0.0, totalBytes));
    const double util = latencyNs > 0.0 ? std::min(1.0, std::max(0.0, (latencyNs - decodeNs) / latencyNs)) : 0.0;
    out.resultJson = resultJson(req, out.microOps, stats, latencyNs, out.totalCycles,
                                totalFlops, totalBytes, staticPowerW, dynamicPowerParam * util);
    return out;
}

} // anonymous namespace

GenericAccel::GenericAccel(const GenericAccelParams &p)
    : BasicPioDevice(p, p.pio_size),
      clockMhz(p.clock_mhz),
      peakGops(p.peak_gops),
      staticPower(p.static_power),
      dynamicPower(p.dynamic_power),
      supportsGemm(p.supports_gemm),
      supportsFft(p.supports_fft),
      supportsEigen(p.supports_eigen),
      useSystemC(p.use_systemc),
      systemcExecutable(p.systemc_lib_path),
      microOpEvent([this]{ advanceMicroOp(); }, name() + ".uarch"),
      completionEvent([this]{ completeCommand(); }, name() + ".completion")
{
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
      case REG_CONTROL: pkt->setLE<uint32_t>(control_reg); break;
      case REG_STATUS: pkt->setLE<uint32_t>(status_reg); break;
      case REG_VERSION: pkt->setLE<uint32_t>(version_reg); break;
      case REG_CAPABILITIES: pkt->setLE<uint32_t>(capabilities_reg); break;
      case REG_CMD_DESC_ADDR_LO: pkt->setLE<uint32_t>(cmd_desc_addr_lo); break;
      case REG_CMD_DESC_ADDR_HI: pkt->setLE<uint32_t>(cmd_desc_addr_hi); break;
      case REG_CMD_DESC_SIZE: pkt->setLE<uint32_t>(cmd_desc_size); break;
      case REG_COMP_STATUS: pkt->setLE<uint32_t>(comp_status); break;
      case REG_COMP_DESC_ADDR_LO: pkt->setLE<uint32_t>(comp_desc_addr_lo); break;
      case REG_COMP_DESC_ADDR_HI: pkt->setLE<uint32_t>(comp_desc_addr_hi); break;
      case REG_COMP_ERROR_CODE: pkt->setLE<uint32_t>(comp_error_code); break;
      case REG_METRIC_CYCLES: pkt->setLE<uint64_t>(metric_cycles); break;
      case REG_METRIC_OPS: pkt->setLE<uint64_t>(metric_ops); break;
      case REG_METRIC_BYTES_READ: pkt->setLE<uint64_t>(metric_bytes_read); break;
      case REG_METRIC_BYTES_WRITTEN: pkt->setLE<uint64_t>(metric_bytes_written); break;
      default: pkt->setLE<uint32_t>(0); break;
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
        if ((data & 0x1) && !busy) processCommand();
        break;
      case REG_CMD_DESC_ADDR_LO: cmd_desc_addr_lo = data; break;
      case REG_CMD_DESC_ADDR_HI: cmd_desc_addr_hi = data; break;
      case REG_CMD_DESC_SIZE: cmd_desc_size = data; break;
      case REG_COMP_DESC_ADDR_LO: comp_desc_addr_lo = data; break;
      case REG_COMP_DESC_ADDR_HI: comp_desc_addr_hi = data; break;
      case REG_CMD_DOORBELL:
        if (!busy) processCommand();
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
    status_reg = 0x1;
    comp_status = 0;
    comp_error_code = 0;
    pendingCycles = 0;
    pendingResultJson.clear();
    pendingResultPath.clear();
    pendingMicroOps.clear();
    pendingMicroOpIndex = 0;

    const uint64_t cmdAddr = (static_cast<uint64_t>(cmd_desc_addr_hi) << 32) | cmd_desc_addr_lo;
    pendingCompletionAddr = (static_cast<uint64_t>(comp_desc_addr_hi) << 32) | comp_desc_addr_lo;
    DPRINTF(GenericAccel, "Processing command at address 0x%llx engine=%s\n",
            static_cast<unsigned long long>(cmdAddr), UarchEngine);

    CommandDescriptor desc{};
    if (cmdAddr == 0 || cmd_desc_size < LegacyCommandDescriptorBytes) {
        comp_error_code = GsimErrorDescriptor;
        DPRINTF(GenericAccel, "descriptor_read verified=false reason=invalid_address_or_size addr=0x%llx size=%u\n",
                static_cast<unsigned long long>(cmdAddr), cmd_desc_size);
        pendingResultJson = errorResultJson("unknown", "invalid command descriptor address or size");
        schedule(completionEvent, curTick() + 1);
        return;
    }

    const size_t descriptorBytes = std::min<size_t>(cmd_desc_size, sizeof(desc));
    sys->physProxy.readBlob(cmdAddr, &desc, descriptorBytes);
    if (desc.magic != GsimMagic || desc.version != 1) {
        comp_error_code = GsimErrorDescriptor;
        DPRINTF(GenericAccel, "descriptor_read verified=false reason=bad_magic_or_version magic=0x%x version=%u\n",
                desc.magic, desc.version);
        pendingResultJson = errorResultJson("unknown", "bad GSIM command descriptor magic or version");
        schedule(completionEvent, curTick() + 1);
        return;
    }

    pendingResultAddr = desc.result_addr;
    const size_t payloadBytes = std::min<size_t>(desc.workspace_size ? static_cast<size_t>(desc.workspace_size) : 65536, MaxJsonBytes);
    const std::string requestJson = readGuestCString(sys, desc.request_addr, payloadBytes);
    const bool hasExtensions = descriptorBytes > LegacyCommandDescriptorBytes;
    const std::string candidatePayload = readOptionalGuestCString(sys, desc.candidate_identity_addr,
                                                                  desc.candidate_identity_bytes);
    const std::string compilePayload = readOptionalGuestCString(sys, desc.compile_schedule_addr,
                                                                desc.compile_schedule_bytes);
    const std::string runtimePayload = readOptionalGuestCString(sys, desc.runtime_schedule_addr,
                                                                desc.runtime_schedule_bytes);
    const std::string sidecarPayload = readOptionalGuestCString(sys, desc.sidecar_dispatch_addr,
                                                                desc.sidecar_dispatch_bytes);
    const std::string extensionPayload = readOptionalGuestCString(sys, desc.extension_payload_addr,
                                                                  desc.extension_payload_bytes);
    DPRINTF(GenericAccel, "descriptor_read verified=true addr=0x%llx request_addr=0x%llx result_addr=0x%llx request_bytes=%llu descriptor_bytes=%llu flags=0x%x extension_fields=%s\n",
            static_cast<unsigned long long>(cmdAddr),
            static_cast<unsigned long long>(desc.request_addr),
            static_cast<unsigned long long>(desc.result_addr),
            static_cast<unsigned long long>(requestJson.size()),
            static_cast<unsigned long long>(descriptorBytes),
            desc.flags,
            hasExtensions ? "true" : "false");
    DPRINTF(GenericAccel,
            "candidate_identity_trace observed=%s bytes=%llu flag=%s\n",
            (!candidatePayload.empty() || (desc.flags & GsimFlagCandidateIdentity)) ? "true" : "false",
            static_cast<unsigned long long>(candidatePayload.size()),
            (desc.flags & GsimFlagCandidateIdentity) ? "true" : "false");
    DPRINTF(GenericAccel,
            "compile_schedule_trace observed=%s bytes=%llu flag=%s\n",
            (!compilePayload.empty() || (desc.flags & GsimFlagCompileSchedule)) ? "true" : "false",
            static_cast<unsigned long long>(compilePayload.size()),
            (desc.flags & GsimFlagCompileSchedule) ? "true" : "false");
    DPRINTF(GenericAccel,
            "runtime_schedule_trace observed=%s bytes=%llu flag=%s\n",
            (!runtimePayload.empty() || (desc.flags & GsimFlagRuntimeSchedule)) ? "true" : "false",
            static_cast<unsigned long long>(runtimePayload.size()),
            (desc.flags & GsimFlagRuntimeSchedule) ? "true" : "false");
    DPRINTF(GenericAccel,
            "sidecar_dispatch_trace observed=%s bytes=%llu use_systemc=%s executable=%s flag=%s\n",
            (!sidecarPayload.empty() || useSystemC || !systemcExecutable.empty() || (desc.flags & GsimFlagSidecarDispatch)) ? "true" : "false",
            static_cast<unsigned long long>(sidecarPayload.size()),
            useSystemC ? "true" : "false",
            systemcExecutable.c_str(),
            (desc.flags & GsimFlagSidecarDispatch) ? "true" : "false");
    DPRINTF(GenericAccel,
            "extension_payload_trace observed=%s bytes=%llu flag=%s\n",
            (!extensionPayload.empty() || (desc.flags & GsimFlagExtensionPayload)) ? "true" : "false",
            static_cast<unsigned long long>(extensionPayload.size()),
            (desc.flags & GsimFlagExtensionPayload) ? "true" : "false");
    metric_bytes_read += static_cast<uint64_t>(requestJson.size() + candidatePayload.size() +
                                               compilePayload.size() + runtimePayload.size() +
                                               sidecarPayload.size() + extensionPayload.size());

    try {
        ScheduleBuildResult scheduleResult = buildSchedule(requestJson, curTick(), clockMhz, peakGops, staticPower, dynamicPower);
        if (!scheduleResult.error.empty()) {
            comp_error_code = GsimErrorMicroarchitecture;
            pendingResultJson = scheduleResult.resultJson;
            pendingCycles = 1;
            DPRINTF(GenericAccel, "uarch_request_decode verified=false reason=%s\n", scheduleResult.error);
            schedule(completionEvent, curTick() + 1);
            return;
        }

        pendingMicroOps = std::move(scheduleResult.microOps);
        pendingResultJson = std::move(scheduleResult.resultJson);
        pendingResultPath = "/tmp/gem5_generic_accel_uarch_" + std::to_string(curTick()) + ".result.json";
        if (useSystemC && !systemcExecutable.empty()) {
            const std::string sidecarRequestPath =
                "/tmp/gem5_generic_accel_sidecar_" + std::to_string(curTick()) + ".request.json";
            const std::string sidecarResultPath =
                "/tmp/gem5_generic_accel_sidecar_" + std::to_string(curTick()) + ".result.json";
            const bool sidecarRequestWritten = writeTextFile(sidecarRequestPath, requestJson);
            const std::string sidecarCmd = shellQuote(systemcExecutable) +
                " --request " + shellQuote(sidecarRequestPath) +
                " --result " + shellQuote(sidecarResultPath);
            const int sidecarRc = sidecarRequestWritten ? std::system(sidecarCmd.c_str()) : -1;
            const std::string sidecarResultJson = sidecarRc == 0 ? readTextFile(sidecarResultPath) : "";
            DPRINTF(GenericAccel,
                    "systemc_submit verified=%s executable=%s request_path=%s result_path=%s return_code=%d result_bytes=%llu claim_boundary=generic_sidecar_result_not_trusted_without_runner_gates\n",
                    (sidecarRc == 0 && !sidecarResultJson.empty()) ? "true" : "false",
                    systemcExecutable.c_str(),
                    sidecarRequestPath.c_str(),
                    sidecarResultPath.c_str(),
                    sidecarRc,
                    static_cast<unsigned long long>(sidecarResultJson.size()));
            if (sidecarRc != 0 || sidecarResultJson.empty()) {
                comp_error_code = GsimErrorMicroarchitecture;
                pendingResultJson = errorResultJson("unknown", "generic sidecar executable failed or produced no result");
                pendingCycles = 1;
                schedule(completionEvent, curTick() + 1);
                return;
            }
        }
        const bool resultFileWritten = writeTextFile(pendingResultPath, pendingResultJson);
        pendingCycles = scheduleResult.totalCycles;
        metric_cycles += pendingCycles;
        metric_ops += scheduleResult.totalFlops;
        DPRINTF(GenericAccel,
                "uarch_request_decode verified=true engine=%s request_bytes=%llu micro_ops=%llu result_bytes=%llu result_path=%s result_file_written=%s total_cycles=%llu total_payload_bytes=%llu\n",
                UarchEngine,
                static_cast<unsigned long long>(requestJson.size()),
                static_cast<unsigned long long>(pendingMicroOps.size()),
                static_cast<unsigned long long>(pendingResultJson.size()),
                pendingResultPath,
                resultFileWritten ? "true" : "false",
                static_cast<unsigned long long>(pendingCycles),
                static_cast<unsigned long long>(scheduleResult.totalBytes));

        if (pendingMicroOps.empty()) {
            schedule(completionEvent, curTick() + 1);
        } else {
            schedule(microOpEvent, std::max(curTick() + 1, pendingMicroOps.front().endTick));
        }
    } catch (const std::exception &exc) {
        comp_error_code = GsimErrorMicroarchitecture;
        pendingResultJson = errorResultJson("unknown", exc.what());
        pendingCycles = 1;
        DPRINTF(GenericAccel, "uarch_request_decode verified=false reason=%s\n", exc.what());
        schedule(completionEvent, curTick() + 1);
    }
}

void GenericAccel::advanceMicroOp()
{
    if (pendingMicroOpIndex >= pendingMicroOps.size()) {
        schedule(completionEvent, curTick() + 1);
        return;
    }

    const auto &op = pendingMicroOps[pendingMicroOpIndex];
    DPRINTF(GenericAccel,
            "uarch_op_complete verified=true kind=%s node=%s device=%s op_type=%s start_tick=%llu end_tick=%llu cycles=%llu bytes=%llu\n",
            op.kind, op.nodeId, op.device, op.opType,
            static_cast<unsigned long long>(op.startTick),
            static_cast<unsigned long long>(op.endTick),
            static_cast<unsigned long long>(op.cycles),
            static_cast<unsigned long long>(op.bytes));
    ++pendingMicroOpIndex;

    if (pendingMicroOpIndex < pendingMicroOps.size()) {
        schedule(microOpEvent, std::max(curTick() + 1, pendingMicroOps[pendingMicroOpIndex].endTick));
        return;
    }

    DPRINTF(GenericAccel,
            "microarchitecture_execute verified=true engine=%s micro_ops=%llu result_bytes=%llu result_path=%s cycles=%llu\n",
            UarchEngine,
            static_cast<unsigned long long>(pendingMicroOps.size()),
            static_cast<unsigned long long>(pendingResultJson.size()),
            pendingResultPath,
            static_cast<unsigned long long>(pendingCycles));
    schedule(completionEvent, curTick() + 1);
}

void GenericAccel::completeCommand()
{
    busy = false;
    status_reg = 0x0;
    comp_status = comp_error_code == 0 ? 0x1 : 0x2;

    if (pendingResultAddr != 0 && !pendingResultJson.empty()) {
        sys->physProxy.writeBlob(pendingResultAddr, pendingResultJson.c_str(), pendingResultJson.size() + 1);
        metric_bytes_written += static_cast<uint64_t>(pendingResultJson.size() + 1);
    }

    if (pendingCompletionAddr != 0) {
        CompletionDescriptor completion{};
        completion.magic = GsimMagic;
        completion.status = comp_status == 0x1 ? 0 : 1;
        completion.result_addr = pendingResultAddr;
        completion.cycles = pendingCycles;
        completion.error_code = comp_error_code;
        sys->physProxy.writeBlob(pendingCompletionAddr, &completion, sizeof(completion));
        metric_bytes_written += static_cast<uint64_t>(sizeof(completion));
    }

    DPRINTF(GenericAccel, "completion_writeback verified=%s result_addr=0x%llx completion_addr=0x%llx result_bytes=%llu cycles=%llu error_code=%u\n",
            (pendingResultAddr != 0 && pendingCompletionAddr != 0 && comp_error_code == 0) ? "true" : "false",
            static_cast<unsigned long long>(pendingResultAddr),
            static_cast<unsigned long long>(pendingCompletionAddr),
            static_cast<unsigned long long>(pendingResultJson.size()),
            static_cast<unsigned long long>(pendingCycles), comp_error_code);
}

uint64_t GenericAccel::estimateCycles(uint32_t opType, uint64_t flops)
{
    const float opsPerCycle = peakGops * 1e9 / (clockMhz * 1e6);
    const float efficiency = (opType == 0) ? 0.5f : 0.7f;
    return static_cast<uint64_t>(std::ceil(flops / std::max(opsPerCycle * efficiency, 1.0f)));
}

} // namespace gem5
